"""Charts for the schedule-health outputs.

Run schedule_health.py first, then:

    python visualize.py

Reads out_activities.csv and out_need_date_alignment.csv from this folder and writes:
    chart_gantt.png              Gantt chart: critical path in red, total float, baseline finish, need dates
    chart_utility_readiness.png  Margin of each utility milestone against its need date
    chart_baseline_slip.png      Forecast finish minus baseline finish per activity
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

HERE = Path(__file__).resolve().parent

# Colors: one series blue for normal work, reserved status colors for meaning.
BLUE = "#2a78d6"       # non-critical activity
RED = "#d03b3b"        # critical path / conflict
AMBER = "#fab219"      # watch
GREEN = "#0ca30c"      # ok
FLOAT = "#c9cdd3"      # total float
INK = "#1f2328"        # text, baseline and need-date marks
MUTED = "#6b7280"      # axis text
GRID = "#e5e7eb"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID,
    "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": INK,
    "axes.spines.top": False, "axes.spines.right": False,
})


def dates(s):
    return pd.to_datetime(s, format="mixed")


def prepare(act, need):
    """Give the activity and need-date tables real date and boolean types for plotting."""
    act, need = act.copy(), need.copy()
    for c in ("early_start", "early_finish", "late_finish", "baseline_finish"):
        act[c] = dates(act[c])
    act["critical"] = act["critical"].astype(str).str.upper().eq("TRUE")
    act["slip_days"] = pd.to_numeric(act["slip_days"], errors="coerce")
    for c in ("forecast_ready", "need_date"):
        need[c] = dates(need[c])
    return act, need


def load():
    return prepare(pd.read_csv(HERE / "out_activities.csv"), pd.read_csv(HERE / "out_need_date_alignment.csv"))


def gantt(act, need):
    n = len(act)
    fig, ax = plt.subplots(figsize=(12, 0.34 * n + 1.8))
    y = range(n)
    day = pd.Timedelta(days=1)
    need_by_id = need.set_index("milestone")["need_date"]
    status_by_id = need.set_index("milestone")["status"]

    for i, r in zip(y, act.itertuples()):
        color = RED if r.critical else BLUE
        if r.duration > 0:
            ax.barh(i, r.duration, left=r.early_start, height=0.56, color=color, zorder=3)
        else:
            ax.scatter(r.early_finish, i, marker="D", s=46, color=color, zorder=4)
        if r.total_float > 0:  # float bar from early finish to late finish
            ax.barh(i, r.total_float, left=r.early_finish, height=0.2, color=FLOAT, zorder=2)
        if pd.notna(r.baseline_finish):
            ax.plot([r.baseline_finish] * 2, [i - 0.36, i + 0.36], color=INK, lw=1.4, zorder=5)
        if r.id in need_by_id:
            nd = need_by_id[r.id]
            ax.scatter(nd, i, marker="v", s=60, facecolor="white", edgecolor=INK, lw=1.4, zorder=6)
            late = (r.early_finish - nd).days
            if late > 0:
                ax.annotate(f"{late} d late vs need date", (r.early_finish, i), xytext=(8, -3),
                            textcoords="offset points", color=INK, fontsize=8, fontweight="bold")

    ax.set_yticks(list(y), [f"{r.id}  {r.name}" for r in act.itertuples()])
    ax.invert_yaxis()
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO, interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.tick_params(axis="y", length=0)
    finish = act["early_finish"].max()
    ax.axvline(finish, color=MUTED, lw=1, ls="--", zorder=1)
    ax.text(finish + day, -0.9, f"Forecast finish {finish:%m/%d/%Y}", color=MUTED, fontsize=8)
    ax.set_title("Infra utility schedule: critical path, float and need dates (prototype data)",
                 loc="left", fontsize=12, color=INK, pad=14)
    legend = [Patch(color=RED, label="Critical path (0 float)"), Patch(color=BLUE, label="Non-critical activity"),
              Patch(color=FLOAT, label="Total float"),
              Line2D([], [], color=INK, lw=1.4, label="Baseline finish"),
              Line2D([], [], marker="v", ls="", mfc="white", mec=INK, label="Fab need date"),
              Line2D([], [], marker="D", ls="", color=MUTED, label="Milestone")]
    ax.legend(handles=legend, loc="upper center", ncol=6, frameon=False, fontsize=8,
              bbox_to_anchor=(0.4, -0.05))
    fig.tight_layout()
    return fig


def readiness(need):
    need = need.sort_values("margin_days")
    colors = {"CONFLICT": RED, "WATCH": AMBER, "OK": GREEN}
    fig, ax = plt.subplots(figsize=(9, 0.55 * len(need) + 1.6))
    labels = [n.replace(" (milestone)", "") for n in need["name"]]
    ax.barh(labels, need["margin_days"], color=[colors[s] for s in need["status"]], height=0.56, zorder=3)
    for i, r in enumerate(need.itertuples()):
        txt = f"{r.margin_days:+d} d  {r.status}  (ready {r.forecast_ready:%m/%d}, needed {r.need_date:%m/%d})"
        ax.annotate(txt, (max(r.margin_days, 0), i), xytext=(6, -3), textcoords="offset points", color=INK, fontsize=8)
    ax.axvline(0, color=INK, lw=1)
    ax.axvspan(0, 10, color=AMBER, alpha=0.08, zorder=0)
    lo, hi = need["margin_days"].min(), need["margin_days"].max()
    ax.set_xlim(min(lo, 0) - 3, hi + 22)
    ax.set_xlabel("Margin in days (need date minus forecast ready).  Below 0 = conflict, 0 to 9 = watch")
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.tick_params(axis="y", length=0)
    ax.set_title("Utility readiness vs Fab Engineering need dates", loc="left", fontsize=12, color=INK, pad=10)
    fig.tight_layout()
    return fig


def slip(act):
    s = act[act["slip_days"].fillna(0) != 0].sort_values("slip_days", ascending=False)
    fig, ax = plt.subplots(figsize=(9, 0.42 * max(len(s), 1) + 1.6))
    if s.empty:
        ax.text(0.5, 0.5, "No activity is forecast off its baseline", ha="center", transform=ax.transAxes)
        ax.axis("off")
    else:
        colors = [RED if c else BLUE for c in s["critical"]]
        ax.barh([f"{r.id}  {r.name}" for r in s.itertuples()], s["slip_days"], color=colors, height=0.56, zorder=3)
        for i, v in enumerate(s["slip_days"]):
            ax.annotate(f"{v:+.0f} d", (v, i), xytext=(5 if v > 0 else -5, -3), textcoords="offset points",
                        ha="left" if v > 0 else "right", color=INK, fontsize=8)
        ax.axvline(0, color=INK, lw=1)
        ax.invert_yaxis()
        ax.set_xlabel("Forecast finish minus baseline finish (days, + = late)")
        ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
        ax.tick_params(axis="y", length=0)
        ax.set_xlim(min(0, s["slip_days"].min()) * 1.15 - 0.5, max(0, s["slip_days"].max()) * 1.15 + 0.5)
        kinds = [h for h, on in ((Patch(color=RED, label="On critical path"), s["critical"].any()),
                                 (Patch(color=BLUE, label="Has float"), (~s["critical"]).any())) if on]
        ax.legend(handles=kinds, frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    ax.set_title("Slip vs baseline", loc="left", fontsize=12, color=INK, pad=10)
    fig.tight_layout()
    return fig


def main():
    act, need = load()
    for fig, name in ((gantt(act, need), "chart_gantt.png"), (readiness(need), "chart_utility_readiness.png"),
                      (slip(act), "chart_baseline_slip.png")):
        fig.savefig(HERE / name, dpi=160, bbox_inches="tight")
        plt.close(fig)
    print("wrote chart_gantt.png, chart_utility_readiness.png, chart_baseline_slip.png")


if __name__ == "__main__":
    main()
