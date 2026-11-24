"""
schedule_health.py
Schedule health check for any project schedule:
  1. Read a schedule export (activities, durations, logic links).
  2. Run the Critical Path Method (forward pass, backward pass, float).
  3. Compare each key milestone with the date the next team needs it (optional).
  4. Compare forecast finishes with the baseline (slip).
  5. Run a few DCMA-style schedule quality checks.
  6. Write CSV files a Power BI or Tableau dashboard can refresh from, plus a
     short text health report for leadership.

Usage:
  python schedule_health.py SCHEDULE NEED_DATES [project_start]
  SCHEDULE and NEED_DATES are .csv or .xlsx files (see templates/). Use - for NEED_DATES
  when the project has no need dates.

Link syntax in the predecessors column, separated by ";" (or ","):
  A130        finish-to-start, no lag
  A110SS+15   start-to-start with a 15-day lag
  A420FS+2    finish-to-start with a 2-day lag
  A500FF-3    finish-to-finish with a 3-day lead
Spaces and lower case are fine (A110 ss + 15). Ids may contain - or . (CON-1010, 1.2.3):
the longest id in the schedule that starts a link wins, so CON-1010 is the activity, not
CON with a 1010-day lead.
Durations are calendar days to keep the demo simple. P6 and MS Project use
work calendars, which change the date math but not the logic.
"""
import io
import math
import re
import sys
from collections import deque
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent

# What may follow the predecessor id in a link: optional type, optional signed lag in days.
LINK_TAIL = r"(?:(FS|SS|FF|SF)\s*)?(?:([+-])\s*(\d+)\s*(?:d|days?)?)?"
TAIL = re.compile(LINK_TAIL, re.I)
LINK = re.compile(r"([A-Za-z0-9_]+?)\s*" + LINK_TAIL, re.I)   # used when the ids are not known
DURATION = re.compile(r"(\d+(?:\.\d*)?|\.\d+)\s*(?:e?d|e?days?)?\s*\??", re.I)  # 10, 10d, 10 days, 10 days?
WATCH_DAYS = 10        # margin below this many days = "watch"
HIGH_FLOAT = 44        # DCMA high-float threshold (working days in DCMA)


def _link(m, pred):
    kind = (m.group(1) or "FS").upper()
    lag = int(m.group(3) or 0) * (-1 if m.group(2) == "-" else 1)
    return pred, kind, lag


def parse_links(text, ids=None):
    """Read a predecessors cell into (predecessor, type, lag) tuples. With ids (the schedule's
    activity ids) the longest id that starts each link is used, so ids containing -, . or
    letters such as SS or FF are read correctly, and an unknown predecessor is reported."""
    links = []
    if not isinstance(text, str):
        return links
    for raw in re.split(r"[;,]", text):
        raw = raw.strip()
        if not raw:   # blank piece, e.g. a trailing ";"
            continue
        if ids is not None:
            for i in range(len(raw), 0, -1):
                pred = raw[:i].rstrip()
                m = TAIL.fullmatch(raw[i:].strip()) if pred in ids else None
                if m:
                    links.append(_link(m, pred))
                    break
            else:
                m = LINK.fullmatch(raw)
                pred = m.group(1) if m else raw
                raise ValueError(f"Unknown predecessor {pred}" + (f" (in link '{raw}')" if pred != raw else ""))
            continue
        m = LINK.fullmatch(raw)
        if not m:
            raise ValueError(f"Cannot read link '{raw}'")
        links.append(_link(m, m.group(1)))
    return links


def topo_order(acts):
    """Activities in logic order, every predecessor before its successors. Iterative (Kahn),
    so very long chains work in any row order. Raises ValueError naming a logic loop."""
    indeg = {a: 0 for a in acts}
    succ = {a: [] for a in acts}
    for a, A in acts.items():
        for p, _, _ in A["links"]:
            succ[p].append(a)
            indeg[a] += 1
    queue = deque(a for a in acts if indeg[a] == 0)
    order = []
    while queue:
        a = queue.popleft()
        order.append(a)
        for s in succ[a]:
            indeg[s] -= 1
            if indeg[s] == 0:
                queue.append(s)
    if len(order) < len(acts):
        # Walk back through unresolved predecessors until an activity repeats: that is a loop.
        rest = {a for a in acts if indeg[a] > 0}
        a, path, at = next(iter(rest)), [], {}
        while a not in at:
            at[a] = len(path)
            path.append(a)
            a = next(p for p, _, _ in acts[a]["links"] if p in rest)
        loop = path[at[a]:][::-1]
        raise ValueError("Logic loop: " + " > ".join(loop + [loop[0]]))
    return order


def cpm(df):
    ids = set(df["id"])
    acts = {}
    for r in df.itertuples():
        try:
            acts[r.id] = {"dur": int(r.duration), "links": parse_links(r.predecessors, ids)}
        except ValueError as e:
            raise ValueError(f"{r.id}: {e}") from None
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

    # Free float: how far an activity can slip without moving any successor or the project
    # finish (the finish bound keeps free float from exceeding total float when an activity
    # only has start-to-start or start-to-finish successors).
    for a in acts:
        A = acts[a]
        ff = min([end - A["ef"]] + [
            (acts[s]["es"] - lag - A["ef"]) if k == "FS" else
            (acts[s]["es"] - lag - A["es"]) if k == "SS" else
            (acts[s]["ef"] - lag - A["ef"]) if k == "FF" else
            (acts[s]["ef"] - lag - A["es"])
            for s, k, lag in succs[a]])
        A["tf"], A["ff"] = A["lf"] - A["ef"], ff
    return acts, succs, end


def read_table(src, sheet="schedule"):
    """Read a CSV or Excel (.xlsx) file, or an uploaded file object, as text columns.
    For a workbook, read the sheet with this name (schedule or need_dates, as in
    templates/schedule_template.xlsx); if there is none, read the first sheet.
    Returns None when a workbook asked for need_dates has no such sheet."""
    name = str(getattr(src, "name", src)).lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        book = pd.ExcelFile(src)
        if sheet in book.sheet_names:
            return book.parse(sheet, dtype=str).fillna("")
        if sheet == "need_dates":
            return None
        return book.parse(0, dtype=str).fillna("")
    # CSV: accept UTF-8 (with or without the BOM Excel adds) and the Windows encoding Excel
    # uses for plain "CSV", so names such as Café or an en dash do not stop the file.
    raw = (src.getvalue() if hasattr(src, "getvalue") else
           src.read() if hasattr(src, "read") else Path(src).read_bytes())
    if isinstance(raw, str):
        text = raw
    else:
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    return pd.read_csv(io.StringIO(text), dtype=str).fillna("")


TEXT_COLUMNS = ("id", "name", "area", "milestone", "needed_by", "predecessor", "successor")


def read_output(path):
    """Read a CSV written by this tool with ids and names kept as text, so 1000 stays "1000"
    and 0010 keeps its zeros (pandas would otherwise turn numeric-looking ids into numbers)."""
    df = pd.read_csv(path, dtype={c: str for c in TEXT_COLUMNS}, keep_default_na=False, na_values=[""])
    for c in TEXT_COLUMNS:
        if c in df.columns:
            df[c] = df[c].fillna("")
    return df


def _clean(table):
    t = table.copy()
    t.columns = [str(c).strip().lower().replace(" ", "_") for c in t.columns]
    t = t.astype(str).apply(lambda col: col.str.strip()).replace({"nan": "", "None": "", "NaT": ""})
    return t


def normalize_schedule(df):
    """Check and tidy a schedule table from any project. Only id and duration are required;
    name, area, predecessors and baseline_finish are optional. Raises ValueError with a
    plain message when something cannot be used."""
    df = _clean(df)
    missing = [c for c in ("id", "duration") if c not in df.columns]
    if missing:
        raise ValueError("Schedule file is missing column(s): " + ", ".join(missing)
                         + ". Start from templates/schedule_template.csv.")
    df = df[df["id"] != ""].copy()
    if df.empty:
        raise ValueError("The schedule has no activities.")
    for c in ("name", "area", "predecessors", "baseline_finish"):
        if c not in df.columns:
            df[c] = ""
    df.loc[df["name"] == "", "name"] = df["id"]
    dupes = df.loc[df["id"].duplicated(), "id"].unique()
    if len(dupes):
        raise ValueError("Duplicate activity id(s): " + ", ".join(dupes))
    # Plain numbers or text such as "10 days" / "10d" (MS Project). Part days round up to the
    # next whole calendar day, since the work cannot finish sooner.
    def days(text):
        m = DURATION.fullmatch(text.strip())
        return math.ceil(float(m.group(1)) - 1e-9) if m else None
    dur = df["duration"].map(days)
    bad = df.loc[dur.isna(), "id"].tolist()
    if bad:
        raise ValueError("Duration must be a number of calendar days, 0 or more (0 for a milestone). "
                         "Check: " + ", ".join(bad[:10]))
    df["duration"] = dur.astype(int).astype(str)
    return df[["id", "name", "area", "duration", "predecessors", "baseline_finish"]]


def normalize_needs(need):
    """Tidy a need-date table. The milestone column may be called milestone or
    utility_milestone; needed_by is optional. An empty or missing table is allowed, and rows
    with no milestone or no need date yet are skipped."""
    cols = ["milestone", "need_date", "needed_by"]
    if need is None or len(need) == 0:
        return pd.DataFrame(columns=cols)
    need = _clean(need).rename(columns={"utility_milestone": "milestone"})
    missing = [c for c in ("milestone", "need_date") if c not in need.columns]
    if missing:
        raise ValueError("Need-date file is missing column(s): " + ", ".join(missing)
                         + ". Start from templates/need_dates_template.csv.")
    if "needed_by" not in need.columns:
        need["needed_by"] = ""
    return need[(need["milestone"] != "") & (need["need_date"] != "")][cols]


def analyze(df, need, start, watch_days=WATCH_DAYS, title="SCHEDULE HEALTH REPORT"):
    """Run every check in memory. df and need are tables as read from the CSV or Excel files
    (need may be None). Returns a dict of DataFrames plus the text report; nothing is written
    to disk. Used by main() below, the Power BI pipeline and the Streamlit app."""
    df = normalize_schedule(df)
    need = normalize_needs(need)
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
    base = pd.to_datetime(df.baseline_finish, errors="coerce", format="mixed").dt.date
    out["baseline_finish"] = base
    out["slip_days"] = [(f - b).days if pd.notna(b) else None
                        for f, b in zip(out.early_finish, base)]

    # Milestone readiness versus the dates the next team needs them.
    rows = []
    for r in need.itertuples():
        if r.milestone not in acts:
            raise ValueError(f"Need-date milestone {r.milestone} is not in the schedule")
        fc = day(acts[r.milestone]["ef"])
        try:
            nd = pd.Timestamp(r.need_date).date()
        except ValueError:
            raise ValueError(f"Cannot read need date '{r.need_date}' for {r.milestone} (use YYYY-MM-DD)")
        margin = (nd - fc).days
        status = "CONFLICT" if margin < 0 else "WATCH" if margin < watch_days else "OK"
        name = df.loc[df.id == r.milestone, "name"].iloc[0]
        rows.append({"milestone": r.milestone, "name": name,
                     "forecast_ready": fc, "need_date": nd,
                     "margin_days": margin, "status": status,
                     "needed_by": r.needed_by})
    align = pd.DataFrame(rows, columns=["milestone", "name", "forecast_ready", "need_date",
                                        "margin_days", "status", "needed_by"]).sort_values("margin_days")

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
        ("Lags as % of links", round(100 * n_lag / max(n_links, 1), 1), "<= 5%"),
        ("Finish-to-start links as % of links", round(100 * n_fs / max(n_links, 1), 1), ">= 90%"),
        (f"High float (> {HIGH_FLOAT} d) as % of tasks", round(100 * len(hi_float) / max(len(task_ids), 1), 1), "<= 5%"),
        (f"High duration (> {HIGH_FLOAT} d) as % of tasks", round(100 * len(hi_dur) / max(len(task_ids), 1), 1), "<= 5%"),
        ("Negative float activities", sum(1 for a in acts if acts[a]["tf"] < 0), "0"),
    ], columns=["check", "value", "target"])
    checks["value"] = [f"{v:g}" for v in checks["value"]]

    # Logic links, for the network diagram. A link is driving when it sets the successor's
    # early dates (no gap); a driving link between two critical activities is on the critical path.
    def gap(p, kind, lag, s):
        P, S = acts[p], acts[s]
        return {"FS": S["es"] - P["ef"], "SS": S["es"] - P["es"],
                "FF": S["ef"] - P["ef"], "SF": S["ef"] - P["es"]}[kind] - lag
    links = pd.DataFrame([
        {"predecessor": p, "successor": s, "type": kind, "lag": lag,
         "driving": gap(p, kind, lag, s) == 0,
         "critical": gap(p, kind, lag, s) == 0 and acts[p]["tf"] <= 0 and acts[s]["tf"] <= 0}
        for s in df.id for p, kind, lag in acts[s]["links"]],
        columns=["predecessor", "successor", "type", "lag", "driving", "critical"])

    # Text health report for leadership.
    crit = out[out.critical].sort_values("early_start")
    lines = [
        title,
        f"Project start {start}, forecast finish {day(end)} ({end} days)",
        "",
        "Critical path: " + " > ".join(crit.id),
        "",
        "Milestone readiness vs need dates (worst first):",
    ]
    for r in align.itertuples():
        lines.append(f"  [{r.status:8}] {r.milestone} {r.name}: ready {r.forecast_ready}, "
                     f"needed {r.need_date}, margin {r.margin_days:+d} d")
    if align.empty:
        lines.append("  no need dates given")
    slips = out[out.slip_days.fillna(0) > 0].sort_values("slip_days", ascending=False)
    lines += ["", "Activities forecast to finish later than baseline:"]
    lines += [f"  {r.id} {r.name}: {int(r.slip_days)} d late (TF {r.total_float})"
              for r in slips.itertuples()] or ["  none"]
    lines += ["", "Schedule quality checks:"]
    lines += [f"  {r.check}: {r.value} (target {r.target})" for r in checks.itertuples()]
    report = "\n".join(lines)
    return {"activities": out, "need_dates": align, "quality_checks": checks, "links": links,
            "report": report, "finish": day(end), "duration_days": end}


def main():
    sched_file = sys.argv[1] if len(sys.argv) > 1 else HERE / "sample_infra_schedule.csv"
    need_file = sys.argv[2] if len(sys.argv) > 2 else HERE / "need_dates.csv"
    start = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else date(2026, 1, 5)

    df = read_table(sched_file)
    need = None if str(need_file) == "-" else read_table(need_file, "need_dates")
    r = analyze(df, need, start)
    r["activities"].to_csv(HERE / "out_activities.csv", index=False)
    r["need_dates"].to_csv(HERE / "out_need_date_alignment.csv", index=False)
    r["quality_checks"].to_csv(HERE / "out_quality_checks.csv", index=False)
    r["links"].to_csv(HERE / "out_links.csv", index=False)
    with open(HERE / "out_health_report.txt", "w", encoding="utf-8") as f:
        f.write(r["report"] + "\n")
    print(r["report"])


if __name__ == "__main__":
    main()
