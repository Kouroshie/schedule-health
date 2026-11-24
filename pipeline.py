"""
pipeline.py
Automated reporting pipeline into Power BI.

Each run:
  1. Runs the CPM and checks in schedule_health.py on the latest schedule export.
  2. Validates the results (a quality gate). If a check fails, nothing is published,
     so the dashboard keeps showing the last good data instead of wrong numbers.
  3. Publishes stable, tidy tables to powerbi/current/ (same file names every run, written
     atomically so Power BI never reads a half-written file).
  4. Appends a dated snapshot to powerbi/history/ (one snapshot per data date; a rerun on the
     same date replaces it), so Power BI can trend float erosion, slip and margins over time.
  5. Logs the run to powerbi/refresh_log.csv (time, status, key numbers, any error).

Power BI reads powerbi/current/ and powerbi/history/ (see powerbi/queries.pq). In Power BI
Desktop click Refresh; in the Power BI service, keep the folder in OneDrive or SharePoint
(or use a gateway) and set a scheduled refresh after the pipeline's run time.

Usage:
  python pipeline.py [--schedule FILE] [--needs FILE] [--start YYYY-MM-DD]
                     [--data-date YYYY-MM-DD] [--out FOLDER] [--charts]
Schedule it daily with Windows Task Scheduler (run_pipeline.bat) or cron.
"""
import argparse
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from schedule_health import normalize_needs, read_output, read_table

HERE = Path(__file__).resolve().parent
TABLES = {  # published name: output file from schedule_health.py
    "activities": "out_activities.csv",
    "need_dates": "out_need_date_alignment.csv",
    "quality_checks": "out_quality_checks.csv",
}


def run_engine(schedule, needs, start):
    cmd = [sys.executable, str(HERE / "schedule_health.py"), str(schedule), str(needs), start]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError("schedule_health.py failed: " + (res.stderr.strip().splitlines() or ["?"])[-1])


def load_outputs():
    t = {name: read_output(HERE / f) for name, f in TABLES.items()}  # ids stay text: 1000, 0010
    for c in ("early_start", "early_finish", "late_finish", "baseline_finish"):
        t["activities"][c] = pd.to_datetime(t["activities"][c], format="mixed").dt.date
    for c in ("forecast_ready", "need_date"):
        t["need_dates"][c] = pd.to_datetime(t["need_dates"][c], format="mixed").dt.date
    return t


def quality_gate(t, needs_file):
    """Checks that must pass before anything is published. Returns a list of problems."""
    act, nd = t["activities"], t["need_dates"]
    problems = []
    if act.empty:
        problems.append("no activities")
    if act["id"].duplicated().any():
        problems.append("duplicate activity ids: " + ", ".join(act.loc[act.id.duplicated(), "id"]))
    if act[["early_start", "early_finish", "late_finish"]].isna().any().any():
        problems.append("activities with missing calculated dates")
    if not act["critical"].astype(str).str.upper().eq("TRUE").any():
        problems.append("no critical path found")
    if (act["early_finish"] < act["early_start"]).any():
        problems.append("finish before start")
    expected = set() if str(needs_file) == "-" else set(normalize_needs(read_table(needs_file, "need_dates"))["milestone"])
    missing = expected - set(nd["milestone"])
    if missing:
        problems.append("need-date milestones missing from results: " + ", ".join(sorted(missing)))
    return problems


def kpis(t, data_date):
    act, nd, qc = t["activities"], t["need_dates"], t["quality_checks"]
    crit = act["critical"].astype(str).str.upper().eq("TRUE")
    return pd.DataFrame([{
        "data_date": data_date,
        "forecast_finish": act["early_finish"].max(),
        "critical_activities": int(crit.sum()),
        "worst_margin_days": int(nd["margin_days"].min()) if len(nd) else None,
        "conflicts": int((nd["status"] == "CONFLICT").sum()),
        "watch": int((nd["status"] == "WATCH").sum()),
        "max_slip_days": float(act["slip_days"].max()),
        "quality_checks": len(qc),
    }])


def write_atomic(df, path):
    tmp = path.with_suffix(".tmp")
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)  # Power BI sees either the old file or the new one, never half of one


def append_history(df, path, data_date):
    if path.exists():
        old = pd.read_csv(path, dtype=str, keep_default_na=False)  # keep earlier rows exactly as written
        old = old[old["data_date"] != str(data_date)]  # rerun on the same date replaces it
        df = pd.concat([old, df.astype({"data_date": str})], ignore_index=True)
    write_atomic(df, path)


def log_run(out, row):
    path = out / "refresh_log.csv"
    df = pd.DataFrame([row])
    df.to_csv(path, mode="a", header=not path.exists(), index=False)


def main():
    ap = argparse.ArgumentParser(description="Schedule health pipeline into Power BI")
    ap.add_argument("--schedule", default=HERE / "sample_infra_schedule.csv")
    ap.add_argument("--needs", default=HERE / "need_dates.csv")
    ap.add_argument("--start", default="2026-01-05", help="project start date")
    ap.add_argument("--data-date", default=str(date.today()), help="status date of this update")
    ap.add_argument("--out", default=HERE / "powerbi", help="folder Power BI reads")
    ap.add_argument("--charts", action="store_true", help="also redraw the PNG charts")
    a = ap.parse_args()

    out = Path(a.out)
    (out / "current").mkdir(parents=True, exist_ok=True)
    (out / "history").mkdir(parents=True, exist_ok=True)
    data_date = date.fromisoformat(a.data_date)
    log = {"run_at": datetime.now().isoformat(timespec="seconds"), "data_date": data_date,
           "schedule_file": Path(a.schedule).name, "status": "", "activities": "",
           "forecast_finish": "", "worst_margin_days": "", "message": ""}
    try:
        run_engine(a.schedule, a.needs, a.start)
        t = load_outputs()
        problems = quality_gate(t, a.needs)
        if problems:
            raise ValueError("quality gate failed: " + "; ".join(problems))
        for df in t.values():
            df.insert(0, "data_date", data_date)
        t["kpis"] = kpis(t, data_date)
        # Everything is built and checked; only now touch the published files.
        for name, df in t.items():
            write_atomic(df, out / "current" / f"{name}.csv")
            append_history(df, out / "history" / f"{name}_history.csv", data_date)
        message = "published"
        if a.charts:  # the data is already published; a chart problem is reported, not a failed run
            res = subprocess.run([sys.executable, str(HERE / "visualize.py")], capture_output=True, text=True)
            if res.returncode != 0:
                message += "; charts not redrawn: " + (res.stderr.strip().splitlines() or ["?"])[-1]
                print("WARNING  " + message, file=sys.stderr)
        k = t["kpis"].iloc[0]
        log.update(status="OK", activities=len(t["activities"]), forecast_finish=k.forecast_finish,
                   worst_margin_days=k.worst_margin_days, message=message)
        margin = "n/a" if pd.isna(k.worst_margin_days) else f"{int(k.worst_margin_days):+d} d"
        print(f"OK  data date {data_date}: {len(t['activities'])} activities, finish {k.forecast_finish}, "
              f"worst margin {margin}, {k.conflicts} conflict(s). Published to {out}")
    except Exception as e:  # log every failure, keep the last good data in place
        log.update(status="FAILED", message=str(e))
        print(f"FAILED  {e}. Last good data left in {out / 'current'}", file=sys.stderr)
        log_run(out, log)
        sys.exit(1)
    log_run(out, log)


if __name__ == "__main__":
    main()
