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
    source = st.radio("Source", [SAMPLE_FAB, SAMPLE_BUILD, UPLOAD], label_visibility="collapsed")
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
    project = st.text_input("Project name", default_name, key=f"name-{data_key}")
    start = st.date_input("Project start (day 0)", default_start, key=f"start-{data_key}")
    watch = st.number_input("WATCH when need-date margin is under (days)", 1, 120, WATCH_DAYS)
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
    schedule = st.data_editor(schedule0, num_rows="dynamic", width="stretch", key=f"sched-{data_key}")
    needs = st.data_editor(needs0, num_rows="dynamic", width="stretch", key=f"needs-{data_key}")
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
          delta_color="inverse", help=f"{res['duration_days']} days from project start")
if len(nd):
    worst = nd.iloc[0]
    base_worst = base["need_dates"].margin_days.min() if edited and len(base["need_dates"]) else None
    c2.metric("Worst need-date margin", f"{int(worst.margin_days):+d} d",
              delta=f"{int(worst.margin_days) - int(base_worst):+d} d vs as loaded" if base_worst is not None else None)
    c3.metric("Need-date conflicts", int((nd.status == "CONFLICT").sum()),
              help=f"{int((nd.status == 'WATCH').sum())} more on WATCH")
else:
    c2.metric("Worst need-date margin", "n/a", help="No need dates given")
    c3.metric("Need-date conflicts", "n/a", help="No need dates given")
c4.metric("Critical activities", int(act.critical.sum()), help=f"of {len(act)} activities")
summary = f"**Critical path:** {' > '.join(act[act.critical].sort_values('early_start').id)}"
if len(nd):
    summary = (f"**Worst:** {worst.milestone} {worst.name}, ready {worst.forecast_ready:%m/%d/%Y}, "
               f"needed {worst.need_date:%m/%d/%Y} ({worst.status}).  " + summary)
st.markdown(summary)

# ---- Detail tabs ----
t_gantt, t_ready, t_slip, t_qc, t_report = st.tabs(
    ["Gantt chart", "Need-date readiness", "Baseline slip", "Quality checks", "Report and downloads"])

with t_gantt:
    f1, f2 = st.columns([2, 1])
    areas = sorted(a for a in pact["area"].unique() if a)
    pick = f1.multiselect("Areas", areas, placeholder="All areas") if areas else []
    near = f2.number_input("Show only activities with float up to (days, blank = all)", min_value=0,
                           value=10 if len(pact) > 60 else None, placeholder="all")
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
    st.dataframe(act, width="stretch", hide_index=True)

with t_ready:
    if len(nd):
        show(vz.readiness(pnd, watch_days=int(watch)))
        st.dataframe(nd, width="stretch", hide_index=True)
    else:
        st.info("No need dates given. Add a need_dates sheet or file (milestone, need_date, needed_by) "
                "to check key milestones against the dates other teams need them.")

with t_slip:
    if act["slip_days"].notna().any():
        show(vz.slip(pact))
    else:
        st.info("No baseline_finish dates given, so slip cannot be measured.")

with t_qc:
    st.dataframe(res["quality_checks"], width="stretch", hide_index=True)
    st.caption("Simplified subset of the DCMA 14-point schedule assessment.")

with t_report:
    st.code(res["report"], language=None)
    d1, d2, d3 = st.columns(3)
    d1.download_button("All results (.xlsx)", results_workbook(res), "schedule_health_results.xlsx")
    d2.download_button("Health report (.txt)", res["report"], "health_report.txt")
    d3.download_button("Activities (.csv)", act.to_csv(index=False), "activities.csv")
