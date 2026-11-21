"""
schedule_health.py
A small prototype of the job's "Python Dev" half:
  1. Read a schedule export (activities, durations, logic links).
  2. Run the Critical Path Method (forward pass, backward pass, float).
  3. Compare each utility "available" milestone with the Fab Engineering need date.
  4. Compare forecast finishes with the baseline (slip).
  5. Run a few DCMA-style schedule quality checks.
  6. Write CSV files a Power BI or Tableau dashboard can refresh from, plus a
     short text health report for leadership.

Usage:
  python schedule_health.py sample_infra_schedule.csv need_dates.csv [project_start]

Link syntax in the predecessors column, separated by ";":
  A130        finish-to-start, no lag
  A110SS+15   start-to-start with a 15-day lag
  A420FS+2    finish-to-start with a 2-day lag
  A500FF-3    finish-to-finish with a 3-day lead
Durations are calendar days to keep the demo simple. P6 and MS Project use
work calendars, which change the date math but not the logic.
"""
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent

LINK = re.compile(r"^([A-Za-z0-9_]+?)(FS|SS|FF|SF)?([+-]\d+)?$")
WATCH_DAYS = 10        # margin below this many days = "watch"
HIGH_FLOAT = 44        # DCMA high-float threshold (working days in DCMA)


def parse_links(text):
    links = []
    if not isinstance(text, str) or not text.strip():
        return links
    for raw in text.split(";"):
        m = LINK.match(raw.strip())
        if not m:
            raise ValueError(f"Cannot read link '{raw}'")
        pred, kind, lag = m.group(1), m.group(2) or "FS", int(m.group(3) or 0)
        links.append((pred, kind, lag))
    return links


def topo_order(acts):
    order, seen, temp = [], set(), set()

    def visit(a):
        if a in seen:
            return
        if a in temp:
            raise ValueError(f"Logic loop found at {a}")
        temp.add(a)
        for p, _, _ in acts[a]["links"]:
            visit(p)
        temp.discard(a)
        seen.add(a)
        order.append(a)

    for a in acts:
        visit(a)
    return order


def cpm(df):
    acts = {r.id: {"dur": int(r.duration), "links": parse_links(r.predecessors)}
            for r in df.itertuples()}
    for a in acts.values():
        for p, _, _ in a["links"]:
            if p not in acts:
                raise ValueError(f"Unknown predecessor {p}")
    order = topo_order(acts)

    # Forward pass: earliest start (ES) and earliest finish (EF), in days.
    for a in order:
        d = acts[a]["dur"]
        es = 0
        for p, kind, lag in acts[a]["links"]:
            P = acts[p]
            if kind == "FS":
                es = max(es, P["ef"] + lag)
            elif kind == "SS":
                es = max(es, P["es"] + lag)
            elif kind == "FF":
                es = max(es, P["ef"] + lag - d)
            elif kind == "SF":
                es = max(es, P["es"] + lag - d)
        acts[a]["es"], acts[a]["ef"] = es, es + d

    # Backward pass: latest finish (LF) and latest start (LS).
    end = max(a["ef"] for a in acts.values())
    for a in acts.values():
        a["lf"] = end
    succs = {a: [] for a in acts}
    for a in acts:
        for p, kind, lag in acts[a]["links"]:
            succs[p].append((a, kind, lag))
    for a in reversed(order):
        d = acts[a]["dur"]
        lf = end
        for s, kind, lag in succs[a]:
            S = acts[s]
            if kind == "FS":
                lf = min(lf, S["ls"] - lag)
            elif kind == "SS":
                lf = min(lf, S["ls"] - lag + d)
            elif kind == "FF":
                lf = min(lf, S["lf"] - lag)
            elif kind == "SF":
                lf = min(lf, S["lf"] - lag + d)
        acts[a]["lf"], acts[a]["ls"] = lf, lf - d

    # Free float: how far an activity can slip without moving any successor.
    for a in acts:
        A = acts[a]
        ff = end - A["ef"] if not succs[a] else min(
            (acts[s]["es"] - lag - A["ef"]) if k == "FS" else
            (acts[s]["es"] - lag - A["es"]) if k == "SS" else
            (acts[s]["ef"] - lag - A["ef"]) if k == "FF" else
            (acts[s]["ef"] - lag - A["es"])
            for s, k, lag in succs[a])
        A["tf"], A["ff"] = A["lf"] - A["ef"], ff
    return acts, succs, end


def main():
    sched_file = sys.argv[1] if len(sys.argv) > 1 else HERE / "sample_infra_schedule.csv"
    need_file = sys.argv[2] if len(sys.argv) > 2 else HERE / "need_dates.csv"
    start = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else date(2026, 1, 5)

    df = pd.read_csv(sched_file, dtype=str).fillna("")
    acts, succs, end = cpm(df)
    day = lambda n: start + timedelta(days=n)

    out = df[["id", "name", "area"]].copy()
    out["duration"] = [acts[i]["dur"] for i in out.id]
    out["early_start"] = [day(acts[i]["es"]) for i in out.id]
    out["early_finish"] = [day(acts[i]["ef"]) for i in out.id]
    out["late_finish"] = [day(acts[i]["lf"]) for i in out.id]
    out["total_float"] = [acts[i]["tf"] for i in out.id]
    out["free_float"] = [acts[i]["ff"] for i in out.id]
    out["critical"] = out.total_float <= 0
    base = pd.to_datetime(df.baseline_finish, errors="coerce").dt.date
    out["baseline_finish"] = base
    out["slip_days"] = [(f - b).days if pd.notna(b) else None
                        for f, b in zip(out.early_finish, base)]
    out.to_csv(HERE / "out_activities.csv", index=False)

    # Utility readiness versus Fab Engineering need dates.
    need = pd.read_csv(need_file)
    rows = []
    for r in need.itertuples():
        fc = day(acts[r.utility_milestone]["ef"])
        nd = date.fromisoformat(r.need_date)
        margin = (nd - fc).days
        status = "CONFLICT" if margin < 0 else "WATCH" if margin < WATCH_DAYS else "OK"
        name = df.loc[df.id == r.utility_milestone, "name"].iloc[0]
        rows.append({"milestone": r.utility_milestone, "name": name,
                     "forecast_ready": fc, "need_date": nd,
                     "margin_days": margin, "status": status,
                     "needed_by": r.needed_by})
    align = pd.DataFrame(rows).sort_values("margin_days")
    align.to_csv(HERE / "out_need_date_alignment.csv", index=False)

    # DCMA-style quality checks (simplified subset of the 14-point assessment).
    n_links = sum(len(acts[a]["links"]) for a in acts)
    n_lag = sum(1 for a in acts for _, _, lag in acts[a]["links"] if lag > 0)
    n_lead = sum(1 for a in acts for _, _, lag in acts[a]["links"] if lag < 0)
    n_fs = sum(1 for a in acts for _, k, _ in acts[a]["links"] if k == "FS")
    no_pred = [a for a in acts if not acts[a]["links"]]
    no_succ = [a for a in acts if not succs[a]]
    task_ids = [a for a in acts if acts[a]["dur"] > 0]
    hi_float = [a for a in task_ids if acts[a]["tf"] > HIGH_FLOAT]
    hi_dur = [a for a in task_ids if acts[a]["dur"] > HIGH_FLOAT]
    checks = pd.DataFrame([
        ("Missing logic (open starts/ends beyond the 1 start and 1 finish)",
         max(len(no_pred) - 1, 0) + max(len(no_succ) - 1, 0), "0 ideal"),
        ("Leads (negative lags)", n_lead, "0"),
        ("Lags as % of links", round(100 * n_lag / n_links, 1), "<= 5%"),
        ("Finish-to-start links as % of links", round(100 * n_fs / n_links, 1), ">= 90%"),
        (f"High float (> {HIGH_FLOAT} d) as % of tasks", round(100 * len(hi_float) / len(task_ids), 1), "<= 5%"),
        (f"High duration (> {HIGH_FLOAT} d) as % of tasks", round(100 * len(hi_dur) / len(task_ids), 1), "<= 5%"),
        ("Negative float activities", sum(1 for a in acts if acts[a]["tf"] < 0), "0"),
    ], columns=["check", "value", "target"])
    checks["value"] = [f"{v:g}" for v in checks["value"]]
    checks.to_csv(HERE / "out_quality_checks.csv", index=False)

    # Text health report for leadership.
    crit = out[out.critical].sort_values("early_start")
    lines = [
        "INFRA SCHEDULE HEALTH REPORT (prototype)",
        f"Project start {start}, forecast finish {day(end)} ({end} days)",
        "",
        "Critical path: " + " > ".join(crit.id),
        "",
        "Utility readiness vs Fab Engineering need dates (worst first):",
    ]
    for r in align.itertuples():
        lines.append(f"  [{r.status:8}] {r.milestone} {r.name}: ready {r.forecast_ready}, "
                     f"needed {r.need_date}, margin {r.margin_days:+d} d")
    slips = out[out.slip_days.fillna(0) > 0].sort_values("slip_days", ascending=False)
    lines += ["", "Activities forecast to finish later than baseline:"]
    lines += [f"  {r.id} {r.name}: {int(r.slip_days)} d late (TF {r.total_float})"
              for r in slips.itertuples()] or ["  none"]
    lines += ["", "Schedule quality checks:"]
    lines += [f"  {r.check}: {r.value} (target {r.target})" for r in checks.itertuples()]
    report = "\n".join(lines)
    with open(HERE / "out_health_report.txt", "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(report)


if __name__ == "__main__":
    main()
