"""
streamlit_app.py
Interactive web version of schedule-health.

    streamlit run streamlit_app.py

Load the sample schedule or upload your own CSV exports, edit durations or logic in the
table to test a what-if, and every result (critical path, float, need-date margins,
baseline slip, quality checks, charts) recalculates at once, compared with the schedule
as loaded. The same engine (schedule_health.analyze) feeds the command line tool, the
Power BI pipeline and this app.
"""
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import visualize as vz
from schedule_health import WATCH_DAYS, analyze

HERE = Path(__file__).resolve().parent

st.set_page_config(page_title="Schedule health", layout="wide")


def read_csv(src):
    return pd.read_csv(src, dtype=str).fillna("")


def run(schedule, needs, start):
    try:
        return analyze(schedule, needs, start), None
    except Exception as e:  # logic loop, unknown predecessor, bad duration, missing milestone
        return None, str(e)


def show(fig):
    st.pyplot(fig, width="stretch")
    plt.close(fig)


# ---- Sidebar: data source and project start ----
with st.sidebar:
    st.header("Schedule data")
    source = st.radio("Source", ["Sample utility schedule", "Upload my CSV files"])
    if source == "Upload my CSV files":
        up_s = st.file_uploader("Schedule export", type="csv",
                                help="Columns: id, name, area, duration, predecessors, baseline_finish")
        up_n = st.file_uploader("Need dates", type="csv",
                                help="Columns: utility_milestone, need_date, needed_by")
        if not (up_s and up_n):
            st.info("Upload both files to start.")
            st.stop()
        schedule0, needs0 = read_csv(up_s), read_csv(up_n)
    else:
        schedule0 = read_csv(HERE / "sample_infra_schedule.csv")
        needs0 = read_csv(HERE / "need_dates.csv")
    start = st.date_input("Project start", date(2026, 1, 5))
    st.caption("Link syntax: A130 (finish-to-start), A110SS+15 (start-to-start, 15 d lag), "
               "A500FF-3 (finish-to-finish, 3 d lead). Separate links with ;")
    st.caption(f"Margin under {WATCH_DAYS} days = WATCH, below 0 = CONFLICT. Durations are calendar days.")

st.title("Schedule health")
st.caption("Critical path, float, utility readiness against need dates, baseline slip and "
           "DCMA-style checks. Sample data is invented for illustration.")

# ---- Editable inputs: the what-if ----
with st.expander("Schedule and need dates (edit any cell to test a what-if)", expanded=False):
    schedule = st.data_editor(schedule0, num_rows="dynamic", width="stretch", key="sched")
    needs = st.data_editor(needs0, num_rows="dynamic", width="stretch", key="needs")
    st.caption("Example: set A210 (UPW polish loop) to 23 days and watch the UPW conflict clear.")

base, base_err = run(schedule0, needs0, start)
res, err = run(schedule, needs, start)
if err:
    st.error(f"The schedule could not be calculated: {err}")
    st.stop()
edited = base is not None and not (schedule.equals(schedule0) and needs.equals(needs0))

act, nd = res["activities"], res["need_dates"]
pact, pnd = vz.prepare(act, nd)

# ---- Headline numbers ----
worst = nd.sort_values("margin_days").iloc[0]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Forecast finish", f"{res['finish']:%m/%d/%Y}",
          delta=f"{(res['finish'] - base['finish']).days:+d} d vs as loaded" if edited else None,
          delta_color="inverse")
c2.metric("Worst need-date margin", f"{int(worst.margin_days):+d} d",
          delta=(f"{int(worst.margin_days) - int(base['need_dates'].margin_days.min()):+d} d vs as loaded"
                 if edited else None))
c3.metric("Utility conflicts", int((nd.status == "CONFLICT").sum()),
          help=f"{int((nd.status == 'WATCH').sum())} more on WATCH")
c4.metric("Critical activities", int(act.critical.sum()), help=f"of {len(act)} activities")
st.markdown(f"**Worst:** {worst.milestone} {worst.name}, ready {worst.forecast_ready:%m/%d}, "
            f"needed {worst.need_date:%m/%d} ({worst.status}).  "
            f"**Critical path:** {' > '.join(act[act.critical].sort_values('early_start').id)}")

# ---- Detail tabs ----
t_gantt, t_ready, t_slip, t_qc, t_report = st.tabs(
    ["Gantt chart", "Utility readiness", "Baseline slip", "Quality checks", "Report and downloads"])

with t_gantt:
    show(vz.gantt(pact, pnd))
    st.dataframe(act, width="stretch", hide_index=True)

with t_ready:
    show(vz.readiness(pnd))
    st.dataframe(nd, width="stretch", hide_index=True)

with t_slip:
    show(vz.slip(pact))

with t_qc:
    st.dataframe(res["quality_checks"], width="stretch", hide_index=True)
    st.caption("Simplified subset of the DCMA 14-point schedule assessment.")

with t_report:
    st.code(res["report"], language=None)
    d1, d2, d3, d4 = st.columns(4)
    d1.download_button("Health report (.txt)", res["report"], "health_report.txt")
    d2.download_button("Activities (.csv)", act.to_csv(index=False), "activities.csv")
    d3.download_button("Need dates (.csv)", nd.to_csv(index=False), "need_date_alignment.csv")
    d4.download_button("Quality checks (.csv)", res["quality_checks"].to_csv(index=False), "quality_checks.csv")
