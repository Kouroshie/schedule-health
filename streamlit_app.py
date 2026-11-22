"""
streamlit_app.py
Interactive web version of schedule-health, for any project schedule.

    streamlit run streamlit_app.py

Download a template (Excel or CSV), fill it with your own activities, upload it, and the
app runs the Critical Path Method, checks key milestones against the dates other teams
need them, measures slip against the baseline and runs DCMA-style quality checks. Edit any
duration or link in the table to test a what-if; every result recalculates at once and is
compared with the schedule as loaded. The same engine (schedule_health.analyze) feeds the
command line tool, the Power BI pipeline and this app.
"""
import io
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import visualize as vz
from schedule_health import WATCH_DAYS, analyze, read_table

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
MAX_GANTT_ROWS = 150

SAMPLE_FAB = "Sample: semiconductor utility schedule"
SAMPLE_BUILD = "Sample: building project (the template)"
UPLOAD = "Upload my project"

st.set_page_config(page_title="Schedule health", layout="wide")

# ---- Help text (hover the "?" icons in the app) ----
COL_HELP = {
    "id": "Unique activity code from your schedule.",
    "name": "Activity or milestone description.",
    "area": "Grouping you gave the activity: discipline, area, contractor or phase.",
    "duration": "Calendar days. 0 means a milestone.",
    "predecessors": "Activities that must happen first. A100 = finish-to-start, A110SS+15 = "
                    "start-to-start with a 15-day lag, A130FF-3 = finish-to-finish with a 3-day lead.",
    "baseline_finish": "Finish date in the approved baseline schedule, used to measure slip.",
    "early_start": "Earliest date the activity can start, from the forward pass.",
    "early_finish": "Earliest date the activity can finish, from the forward pass.",
    "late_finish": "Latest date it can finish without delaying the project finish (backward pass).",
    "total_float": "Days the activity can slip before it delays the project finish. "
                   "0 = critical. Negative = already late against the finish.",
    "free_float": "Days the activity can slip before it delays any successor.",
    "critical": "True when total float is 0 or less: any delay here moves the project finish.",
    "slip_days": "Forecast finish minus baseline finish. Positive = later than planned.",
    "milestone": "Activity id another team is waiting for.",
    "forecast_ready": "Date the schedule says this milestone will be done (early finish).",
    "need_date": "Date the other team needs it.",
    "margin_days": "Need date minus forecast ready date. Negative = it will be late.",
    "status": "CONFLICT = late, WATCH = margin under the WATCH threshold, OK = enough margin.",
    "needed_by": "Team or contractor waiting for the milestone.",
    "check": "Schedule quality check (simplified DCMA 14-point assessment).",
    "value": "Result for this schedule.",
    "target": "Value a well-built schedule should meet.",
}
QC_HELP = {
    "Missing logic": "Activities with no predecessor or no successor, beyond the single project "
                     "start and finish. Open ends hide delays because nothing pushes them or is "
                     "pushed by them. Fix: link every activity into the network.",
    "Leads": "Links with negative lag (a successor starting before its predecessor ends). "
             "Leads make logic hard to follow and can hide real overlap. Fix: split the "
             "activity or use a start-to-start link instead.",
    "Lags": "Share of links that carry a positive lag. Lags are waiting time that is not an "
            "activity, so nobody owns it. Target 5% or less. Fix: replace long lags with real "
            "activities (cure time, delivery, review).",
    "Finish-to-start": "Share of links that are finish-to-start, the simplest and clearest "
                       "relationship. Target 90% or more. Too many SS/FF/SF links make the "
                       "critical path hard to read.",
    "High float": "Share of tasks with very large total float. High float usually means "
                  "missing successors, so the activity looks free to slip when it is not. "
                  "Target 5% or less.",
    "High duration": "Share of tasks longer than about two months. Long activities are hard "
                     "to status and hide progress. Target 5% or less. Fix: break them into "
                     "smaller pieces.",
    "Negative float": "Activities whose forecast already misses the finish they are tied to. "
                      "Target 0. Any count here means the plan cannot meet its dates without "
                      "recovery.",
}


def col_cfg(df):
    """Hover help on every known column header."""
    return {c: st.column_config.Column(help=COL_HELP[c]) for c in df.columns if c in COL_HELP}


def page_help(text):
    with st.expander("How to read this page", icon=":material/help:"):
        st.markdown(text)


def passes(value, target):
    v, t = float(value), target.replace("%", "").replace("ideal", "").strip()
    if t.startswith("<="):
        return v <= float(t[2:])
    if t.startswith(">="):
        return v >= float(t[2:])
    return v == float(t)


def run(schedule, needs, start, watch, title):
    try:
        return analyze(schedule, needs, start, watch_days=watch, title=title), None
    except Exception as e:  # logic loop, unknown predecessor, bad duration, missing column
        return None, str(e)


def show(fig):
    st.pyplot(fig, width="stretch")
    plt.close(fig)


def results_workbook(res):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        res["activities"].to_excel(xw, sheet_name="activities", index=False)
        res["need_dates"].to_excel(xw, sheet_name="need_dates", index=False)
        res["quality_checks"].to_excel(xw, sheet_name="quality_checks", index=False)
        pd.DataFrame({"report": res["report"].splitlines()}).to_excel(xw, sheet_name="report", index=False)
    return buf.getvalue()


# ---- Sidebar ----
with st.sidebar:
    st.header("1. Get a template")
    st.caption("Fill in your own activities, keep the column headers, then upload below.")
    st.download_button("Excel template (.xlsx)", (TEMPLATES / "schedule_template.xlsx").read_bytes(),
                       "schedule_template.xlsx", width="stretch",
                       help="Sheets: instructions, schedule, need_dates")
    t1, t2 = st.columns(2)
    t1.download_button("Schedule .csv", (TEMPLATES / "schedule_template.csv").read_bytes(),
                       "schedule_template.csv", width="stretch")
    t2.download_button("Need dates .csv", (TEMPLATES / "need_dates_template.csv").read_bytes(),
                       "need_dates_template.csv", width="stretch")

    st.header("2. Load a schedule")
    source = st.radio("Source", [SAMPLE_FAB, SAMPLE_BUILD, UPLOAD],
                      help="Try one of the two samples, or upload your own schedule built from the template.")
    if source == UPLOAD:
        up_s = st.file_uploader("Schedule (.xlsx or .csv)", type=["xlsx", "csv"],
                                help="Required columns: id, duration. Optional: name, area, "
                                     "predecessors, baseline_finish")
        up_n = st.file_uploader("Need dates (optional, .xlsx or .csv)", type=["xlsx", "csv"],
                                help="Columns: milestone, need_date, needed_by. Not needed if your "
                                     "Excel file already has a need_dates sheet.")
        if not up_s:
            st.info("Upload a schedule to start, or pick a sample above.")
            st.stop()
        try:
            schedule0 = read_table(up_s, "schedule")
            needs0 = read_table(up_n, "need_dates") if up_n else (
                read_table(up_s, "need_dates") if up_s.name.lower().endswith(".xlsx") else None)
        except Exception as e:
            st.error(f"Could not read the file: {e}")
            st.stop()
        if needs0 is None:
            needs0 = pd.DataFrame(columns=["milestone", "need_date", "needed_by"])
        default_name, default_start = Path(up_s.name).stem.replace("_", " "), date.today()
        data_key = f"up-{up_s.name}-{up_s.size}-{up_n.name if up_n else ''}"
    elif source == SAMPLE_BUILD:
        schedule0 = read_table(TEMPLATES / "schedule_template.csv")
        needs0 = read_table(TEMPLATES / "need_dates_template.csv")
        default_name, default_start, data_key = "Building project (template)", date(2026, 3, 2), "build"
    else:
        schedule0 = read_table(HERE / "sample_infra_schedule.csv")
        needs0 = read_table(HERE / "need_dates.csv")
        default_name, default_start, data_key = "Semiconductor utility schedule (sample)", date(2026, 1, 5), "fab"

    st.header("3. Settings")
    project = st.text_input("Project name", default_name, key=f"name-{data_key}",
                            help="Shown in the page title, chart titles and the report.")
    start = st.date_input("Project start (day 0)", default_start, key=f"start-{data_key}",
                          help="Date the first activity can start. All dates are counted from here.")
    watch = st.number_input("WATCH when need-date margin is under (days)", 1, 120, WATCH_DAYS,
                            help="A milestone that is on time but with less margin than this is "
                                 "flagged WATCH instead of OK.")
    st.caption("Durations are calendar days. Link syntax: A130 (finish-to-start), "
               "A110SS+15 (start-to-start, 15 d lag), A500FF-3 (finish-to-finish, 3 d lead). "
               "Separate links with ;")

st.title(project or "Schedule health")
st.caption("Critical path, float, milestone readiness against need dates, baseline slip and "
           "DCMA-style quality checks for any project schedule. Files you upload are used only "
           "in your session and are not stored.")

with st.expander("How to prepare your files"):
    st.markdown(
        "| File / sheet | Column | Required | What to enter |\n|---|---|---|---|\n"
        "| schedule | `id` | yes | Unique activity code, e.g. A100 (letters, digits, _) |\n"
        "| schedule | `name` | no | Activity description |\n"
        "| schedule | `area` | no | Any grouping: discipline, area, contractor, phase |\n"
        "| schedule | `duration` | yes | Whole calendar days, 0 for a milestone |\n"
        "| schedule | `predecessors` | no | Links separated by `;` such as `A100`, `A110SS+15`, `A120FS+2`, `A130FF-3` |\n"
        "| schedule | `baseline_finish` | no | Baseline finish date, YYYY-MM-DD |\n"
        "| need_dates | `milestone` | yes | Activity id another team is waiting for |\n"
        "| need_dates | `need_date` | yes | Date they need it, YYYY-MM-DD |\n"
        "| need_dates | `needed_by` | no | Who needs it |\n\n"
        "Exporting from Primavera P6 or MS Project: export activity ID, name, original duration, "
        "predecessors with relationship type and lag, and baseline finish to Excel, then rename the "
        "columns to match. Need dates are optional.")

# ---- Editable inputs: the what-if ----
with st.expander("Schedule and need dates (edit any cell to test a what-if)"):
    st.caption("Change a duration or a link, add or delete rows. Every number and chart below "
               "updates at once and shows the change against the schedule as loaded. Hover a "
               "column header to see what it means.")
    schedule = st.data_editor(schedule0, num_rows="dynamic", width="stretch", key=f"sched-{data_key}",
                              column_config=col_cfg(schedule0))
    needs = st.data_editor(needs0, num_rows="dynamic", width="stretch", key=f"needs-{data_key}",
                           column_config=col_cfg(needs0))
    if source == SAMPLE_FAB:
        st.caption("Example: set A210 (UPW polish loop) to 23 days and watch the UPW conflict clear.")

title = f"{project.upper()} SCHEDULE HEALTH REPORT" if project else "SCHEDULE HEALTH REPORT"
base, _ = run(schedule0, needs0, start, watch, title)
res, err = run(schedule, needs, start, watch, title)
if err:
    st.error(f"The schedule could not be calculated: {err}")
    st.stop()
edited = base is not None and not (schedule.equals(schedule0) and needs.equals(needs0))

act, nd = res["activities"], res["need_dates"]
pact, pnd = vz.prepare(act, nd)

# ---- Headline numbers ----
c1, c2, c3, c4 = st.columns(4)
c1.metric("Forecast finish", f"{res['finish']:%m/%d/%y}",
          delta=f"{(res['finish'] - base['finish']).days:+d} d vs as loaded" if edited else None,
          delta_color="inverse",
          help=f"Earliest date the whole project can finish: {res['duration_days']} days from the "
               "project start, set by the critical path.")
if len(nd):
    worst = nd.iloc[0]
    base_worst = base["need_dates"].margin_days.min() if edited and len(base["need_dates"]) else None
    c2.metric("Worst need-date margin", f"{int(worst.margin_days):+d} d",
              delta=f"{int(worst.margin_days) - int(base_worst):+d} d vs as loaded" if base_worst is not None else None,
              help="Smallest gap between a need date and the forecast ready date. Negative means "
                   "a milestone will be late for the team waiting on it.")
    c3.metric("Need-date conflicts", int((nd.status == "CONFLICT").sum()),
              help=f"Milestones forecast to be ready after their need date. "
                   f"{int((nd.status == 'WATCH').sum())} more are on WATCH (on time, small margin).")
else:
    c2.metric("Worst need-date margin", "n/a", help="No need dates given")
    c3.metric("Need-date conflicts", "n/a", help="No need dates given")
c4.metric("Critical activities", int(act.critical.sum()),
          help=f"Activities with zero float, out of {len(act)}. A delay to any of them delays the "
               "project finish one for one.")
summary = f"**Critical path:** {' > '.join(act[act.critical].sort_values('early_start').id)}"
if len(nd):
    summary = (f"**Worst:** {worst.milestone} {worst['name']}, ready {worst.forecast_ready:%m/%d/%Y}, "
               f"needed {worst.need_date:%m/%d/%Y} ({worst.status}).  " + summary)
st.markdown(summary)

# ---- Detail tabs ----
t_gantt, t_ready, t_slip, t_qc, t_report = st.tabs(
    ["Gantt chart", "Need-date readiness", "Baseline slip", "Quality checks", "Report and downloads"])

with t_gantt:
    page_help(
        "- Each bar is one activity, from its early start to its early finish.\n"
        "- **Red bars** are on the critical path: any delay there moves the project finish. "
        "**Blue bars** have float.\n"
        "- The **thin light bar** after an activity is its total float, the days it can slip "
        "before it delays the finish.\n"
        "- **Diamonds** are milestones (0-day activities). **Black ticks** mark the baseline "
        "finish, so a bar ending to the right of its tick has slipped.\n"
        "- **White triangles** are need dates from other teams, on the milestone's row. A "
        "diamond to the right of its triangle is late.\n"
        "- The **dashed vertical line** is the forecast project finish.\n"
        "- Use the filters to focus on one area or on activities close to critical. The table "
        "under the chart has every date; hover a column header for its meaning.")
    f1, f2 = st.columns([2, 1])
    areas = sorted(a for a in pact["area"].unique() if a)
    pick = f1.multiselect("Areas", areas, placeholder="All areas",
                          help="Show only the activities in these areas.") if areas else []
    near = f2.number_input("Show only activities with float up to (days, blank = all)", min_value=0,
                           value=10 if len(pact) > 60 else None, placeholder="all",
                           help="Hide activities with more float than this, to focus on the "
                                "critical and near-critical work.")
    view = pact
    if pick:
        view = view[view["area"].isin(pick)]
    if near is not None:
        view = view[view["total_float"] <= near]
    if view.empty:
        st.info("No activities match these filters.")
    else:
        if len(view) > MAX_GANTT_ROWS:
            st.warning(f"Showing the first {MAX_GANTT_ROWS} of {len(view)} activities by start date. "
                       "Use the filters to narrow the chart.")
            view = view.sort_values("early_start").head(MAX_GANTT_ROWS)
        show(vz.gantt(view, pnd, title=f"{project}: critical path, float and need dates"))
    st.dataframe(act, width="stretch", hide_index=True, column_config=col_cfg(act))

with t_ready:
    page_help(
        "Checks each key milestone against the date another team needs it (for example, a "
        "utility system the tool installers are waiting for).\n\n"
        "- **Margin** = need date minus forecast ready date.\n"
        f"- **CONFLICT** (red): margin below 0, the milestone will be late.\n"
        f"- **WATCH** (amber): on time but with less than {int(watch)} days of margin "
        "(change the threshold in the sidebar).\n"
        "- **OK** (green): enough margin.\n\n"
        "Worst margin is listed first. To clear a conflict, shorten or re-sequence the critical "
        "activities in front of that milestone, or agree a later need date.")
    if len(nd):
        show(vz.readiness(pnd, watch_days=int(watch)))
        st.dataframe(nd, width="stretch", hide_index=True, column_config=col_cfg(nd))
    else:
        st.info("No need dates given. Add a need_dates sheet or file (milestone, need_date, needed_by) "
                "to check key milestones against the dates other teams need them.")

with t_slip:
    page_help(
        "Compares each activity's forecast finish with its baseline finish (the approved plan).\n\n"
        "- **Bars to the right** (positive days) finish later than planned.\n"
        "- **Bars to the left** finish earlier than planned.\n"
        "- **Red** bars are critical activities: their slip moves the project finish. **Blue** "
        "bars have float, so their slip uses up that float first.\n\n"
        "Needs a `baseline_finish` column in your schedule.")
    if act["slip_days"].notna().any():
        show(vz.slip(pact))
    else:
        st.info("No baseline_finish dates given, so slip cannot be measured.")

with t_qc:
    page_help(
        "Tests whether the schedule is built well enough to trust its dates, using a simplified "
        "subset of the DCMA 14-point assessment (a standard US government schedule review).\n\n"
        "- Each row shows the result, the target and a pass or review mark.\n"
        "- **Hover the ? next to a check** to see what it tests, why it matters and how to fix it.\n"
        "- A failed check does not mean the dates are wrong, but it tells you where the logic "
        "needs a closer look before you rely on the critical path.")
    qc = res["quality_checks"]
    h1, h2, h3, h4 = st.columns([5, 1, 1, 1])
    h1.markdown("**Check**")
    h2.markdown("**Value**")
    h3.markdown("**Target**")
    h4.markdown("**Result**")
    for r in qc.itertuples():
        tip = next((t for k, t in QC_HELP.items() if r.check.startswith(k)), None)
        ok = passes(r.value, r.target)
        c1, c2, c3, c4 = st.columns([5, 1, 1, 1])
        c1.markdown(r.check, help=tip)
        c2.markdown(r.value)
        c3.markdown(r.target)
        c4.markdown(":green[:material/check_circle: Pass]" if ok else ":orange[:material/warning: Review]")
    st.caption(f"{sum(passes(r.value, r.target) for r in qc.itertuples())} of {len(qc)} checks pass.")

with t_report:
    page_help(
        "The same results as a short text report, ready to paste into an email or status "
        "update, plus downloads:\n\n"
        "- **All results (.xlsx)**: one workbook with activities, need dates, quality checks "
        "and the report.\n"
        "- **Health report (.txt)**: the text below.\n"
        "- **Activities (.csv)**: every activity with its calculated dates and float, for "
        "Excel, Power BI or Tableau.")
    st.code(res["report"], language=None)
    d1, d2, d3 = st.columns(3)
    d1.download_button("All results (.xlsx)", results_workbook(res), "schedule_health_results.xlsx")
    d2.download_button("Health report (.txt)", res["report"], "health_report.txt")
    d3.download_button("Activities (.csv)", act.to_csv(index=False), "activities.csv")
