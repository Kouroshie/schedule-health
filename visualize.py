"""Charts for the schedule-health outputs.

Run schedule_health.py first, then:

    python visualize.py

Reads out_activities.csv and out_need_date_alignment.csv from this folder and writes:
    chart_gantt.png              Gantt chart: critical path in red, total float, baseline finish, need dates
    chart_utility_readiness.png  Margin of each need-date milestone against its need date
    chart_baseline_slip.png      Forecast finish minus baseline finish per activity
    chart_network.png            Network (precedence) diagram: activity boxes and logic links
    chart_wbs.png                Work breakdown structure: project > area > activities
"""
import textwrap
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch

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


def short(text, n=48):
    return text if len(text) <= n else text[: n - 1] + "…"


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


def load_links():
    path = HERE / "out_links.csv"
    if not path.exists():
        return pd.DataFrame(columns=["predecessor", "successor", "type", "lag", "driving", "critical"])
    links = pd.read_csv(path, dtype={"predecessor": str, "successor": str})
    for c in ("driving", "critical"):
        links[c] = links[c].astype(str).str.upper().eq("TRUE")
    return links


def gantt(act, need, title="Schedule: critical path, float and need dates"):
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

    ax.set_yticks(list(y), [short(f"{r.id}  {r.name}") for r in act.itertuples()])
    ax.invert_yaxis()
    span = (act["late_finish"].max() - act["early_start"].min()).days
    if span <= 200:  # short project: a tick every other Monday
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO, interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    else:            # long project: let matplotlib pick months or quarters
        loc = mdates.AutoDateLocator(maxticks=12)
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.tick_params(axis="y", length=0)
    finish = act["early_finish"].max()
    ax.axvline(finish, color=MUTED, lw=1, ls="--", zorder=1)
    ax.text(finish + day, -0.9, f"Forecast finish {finish:%m/%d/%Y}", color=MUTED, fontsize=8)
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=14)
    legend = [Patch(color=RED, label="Critical path (0 float)"), Patch(color=BLUE, label="Non-critical activity"),
              Patch(color=FLOAT, label="Total float"),
              Line2D([], [], color=INK, lw=1.4, label="Baseline finish"),
              Line2D([], [], marker="v", ls="", mfc="white", mec=INK, label="Need date"),
              Line2D([], [], marker="D", ls="", color=MUTED, label="Milestone")]
    ax.legend(handles=legend, loc="upper center", ncol=6, frameon=False, fontsize=8,
              bbox_to_anchor=(0.4, -0.05))
    fig.tight_layout()
    return fig


def readiness(need, watch_days=10):
    need = need.sort_values("margin_days")
    colors = {"CONFLICT": RED, "WATCH": AMBER, "OK": GREEN}
    fig, ax = plt.subplots(figsize=(9, 0.55 * len(need) + 1.6))
    labels = [short(n.replace(" (milestone)", "")) for n in need["name"]]
    ax.barh(labels, need["margin_days"], color=[colors[s] for s in need["status"]], height=0.56, zorder=3)
    for i, r in enumerate(need.itertuples()):
        txt = f"{r.margin_days:+d} d  {r.status}  (ready {r.forecast_ready:%m/%d}, needed {r.need_date:%m/%d})"
        ax.annotate(txt, (max(r.margin_days, 0), i), xytext=(6, -3), textcoords="offset points", color=INK, fontsize=8)
    ax.axvline(0, color=INK, lw=1)
    ax.axvspan(0, watch_days, color=AMBER, alpha=0.08, zorder=0)
    lo, hi = need["margin_days"].min(), need["margin_days"].max()
    ax.set_xlim(min(lo, 0) - 3, hi + 22)
    ax.set_xlabel(f"Margin in days (need date minus forecast ready).  Below 0 = conflict, "
                  f"0 to {watch_days - 1} = watch")
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.tick_params(axis="y", length=0)
    ax.set_title("Milestone readiness vs need dates", loc="left", fontsize=12, color=INK, pad=10)
    fig.tight_layout()
    return fig


def slip(act, top=30):
    s = act[act["slip_days"].fillna(0) != 0]
    s = s.loc[s["slip_days"].abs().sort_values(ascending=False).index[:top]].sort_values("slip_days", ascending=False)
    fig, ax = plt.subplots(figsize=(9, 0.42 * max(len(s), 1) + 1.6))
    if s.empty:
        ax.text(0.5, 0.5, "No activity is forecast off its baseline", ha="center", transform=ax.transAxes)
        ax.axis("off")
    else:
        colors = [RED if c else BLUE for c in s["critical"]]
        ax.barh([short(f"{r.id}  {r.name}") for r in s.itertuples()], s["slip_days"], color=colors, height=0.56, zorder=3)
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


def _box(ax, x, y, w, h, edge, lw=1.5, fill="white", round_=0.06):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle=f"round,pad=0,rounding_size={round_}",
                                facecolor=fill, edgecolor=edge, lw=lw, zorder=3))


def _link_label(kind, lag):
    if kind == "FS" and not lag:
        return ""
    return f"{kind}{lag:+d}" if lag else kind


def network(act, links, title="Network diagram: activities and logic links"):
    """Precedence (activity-on-node) diagram. Columns follow the logic from left to right:
    each activity sits one column after its latest predecessor. Critical activities and the
    driving links between them are red; link types other than plain finish-to-start are labeled."""
    ids = list(act.sort_values(["early_start", "id"])["id"])
    keep = set(ids)
    lk = links[links["predecessor"].isin(keep) & links["successor"].isin(keep)]
    preds, succs = defaultdict(list), defaultdict(list)
    for r in lk.itertuples():
        preds[r.successor].append(r.predecessor)
        succs[r.predecessor].append(r.successor)

    # Column = longest chain of links from a start activity (Kahn order).
    indeg = {i: len(preds[i]) for i in ids}
    col = {i: 0 for i in ids}
    queue = [i for i in ids if indeg[i] == 0]
    while queue:
        a = queue.pop(0)
        for b in succs[a]:
            col[b] = max(col[b], col[a] + 1)
            indeg[b] -= 1
            if indeg[b] == 0:
                queue.append(b)
    cols = defaultdict(list)
    for i in ids:  # already in start-date order
        cols[col[i]].append(i)
    # The critical path runs along the center row, so no other box can sit on a red line.
    # Other activities fill the rows above and below, ordered by the average row of their
    # predecessors to reduce crossing lines.
    crit = dict(zip(act["id"], act["critical"].astype(bool)))
    row = {}
    for c in sorted(cols):
        bary = lambda i: (sum(row[p] for p in preds[i]) / len(preds[i])) if preds[i] else 0
        on, off = [i for i in cols[c] if crit[i]], [i for i in cols[c] if not crit[i]]
        for k, i in enumerate(on):  # parallel critical activities: 0, -1, +1, -2, ...
            row[i] = (k + 1) // 2 * (1 if k % 2 else -1) if k else 0
        used = set(row[i] for i in on)
        free = sorted((r for r in range(-len(cols[c]) - 1, len(cols[c]) + 2) if r not in used and r != 0),
                      key=lambda r: (abs(r), r))
        off.sort(key=bary)
        slots = sorted(free[:len(off)])
        for i, r in zip(off, slots):
            row[i] = r
    info = act.set_index("id")
    W, H, DX, DY = 1.55, 0.78, 2.15, 1.0
    ncol = max(cols) + 1
    nrow = max(row.values()) - min(row.values()) + 1
    fig, ax = plt.subplots(figsize=(max(7, ncol * 1.75 + 1), max(3.2, nrow * 0.85 + 1.6)))
    pos = {i: (col[i] * DX, -row[i] * DY) for i in ids}

    for r in lk.itertuples():
        (x1, y1), (x2, y2) = pos[r.predecessor], pos[r.successor]
        crit = bool(r.critical)
        span = round((x2 - x1) / DX)
        rad = 0 if abs(y2 - y1) < 1e-6 and (span == 1 or crit) else (0.08 if span == 1 else 0.18) * (1 if y2 >= y1 else -1)
        ax.add_patch(FancyArrowPatch((x1 + W / 2, y1), (x2 - W / 2, y2), arrowstyle="-|>", mutation_scale=9,
                                     connectionstyle=f"arc3,rad={rad}", color=RED if crit else "#9aa1ab",
                                     lw=1.6 if crit else 0.9, zorder=2, shrinkA=0, shrinkB=1))
        label = _link_label(r.type, int(r.lag))
        if label:
            ax.text((x1 + W / 2 + x2 - W / 2) / 2, (y1 + y2) / 2 + 0.09, label, ha="center", va="bottom",
                    fontsize=6.5, color=INK, zorder=4,
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none"))

    for i in ids:
        x, y = pos[i]
        a = info.loc[i]
        crit = bool(a["critical"])
        ms = int(a["duration"]) == 0
        _box(ax, x, y, W, H, RED if crit else BLUE, lw=1.8 if crit else 1.1,
             fill="#fdf0f0" if crit else "white", round_=0.3 if ms else 0.06)
        ax.text(x, y + H / 2 - 0.1, ("\u25c6 " if ms else "") + i, ha="center", va="top", fontsize=7.5,
                fontweight="bold", color=RED if crit else INK, zorder=5)
        name = "" if str(a["name"]) == i else textwrap.shorten(str(a["name"]), 40, placeholder="…")
        ax.text(x, y + 0.02, "\n".join(textwrap.wrap(name, 21)[:2]), ha="center", va="center",
                fontsize=6.3, color=INK, zorder=5, linespacing=1.05)
        ax.text(x, y - H / 2 + 0.07, f"{int(a['duration'])} d  |  TF {int(a['total_float'])}",
                ha="center", va="bottom", fontsize=6.3, color=MUTED, zorder=5)

    ax.set_xlim(-W / 2 - 0.3, (ncol - 1) * DX + W / 2 + 0.3)
    ys = [p[1] for p in pos.values()]
    ax.set_ylim(min(ys) - H / 2 - 0.3, max(ys) + H / 2 + 0.3)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=12)
    legend = [Patch(facecolor="#fdf0f0", edgecolor=RED, label="Critical activity"),
              Patch(facecolor="white", edgecolor=BLUE, label="Activity with float"),
              Line2D([], [], color=RED, lw=1.6, label="Driving link on the critical path"),
              Line2D([], [], color="#9aa1ab", lw=0.9, label="Other logic link")]
    ax.legend(handles=legend, frameon=False, fontsize=7.5, loc="upper left", bbox_to_anchor=(0, -0.01), ncol=4)
    fig.tight_layout()
    return fig


def wbs(act, project="Project", max_rows=14):
    """Work breakdown structure: the project on top, one branch per area, and the activities
    of each area listed under it (critical ones outlined in red)."""
    act = act.copy()
    act["area"] = act["area"].fillna("").astype(str).replace("", "Unassigned")
    groups = sorted(act.groupby("area"), key=lambda g: (g[1]["early_start"].min(), g[0]))
    n = len(groups)
    BW, DX = 2.2, 2.45
    shown = min(max(len(g) for _, g in groups), max_rows + 1)
    fig, ax = plt.subplots(figsize=(max(7, n * 2.35 + 0.4), 3.0 + shown * 0.48))
    xs = [k * DX for k in range(n)]
    mid = (xs[0] + xs[-1]) / 2
    start, finish = act["early_start"].min(), act["early_finish"].max()

    # Level 1: the project.
    _box(ax, mid, 0, max(BW * 1.4, 3.2), 0.85, INK, lw=1.6, fill="#f3f4f6")
    ax.text(mid, 0.17, f"1  {textwrap.shorten(project, 44, placeholder='…')}", ha="center", va="center",
            fontsize=9, fontweight="bold", color=INK, zorder=5)
    ax.text(mid, -0.17, f"{len(act)} activities  |  {start:%m/%d/%y} to {finish:%m/%d/%y}  |  "
            f"{(finish - start).days} d", ha="center", va="center", fontsize=7, color=MUTED, zorder=5)
    # Connector bar to the areas.
    ax.plot([mid, mid], [-0.43, -0.8], color=MUTED, lw=1, zorder=1)
    if n > 1:
        ax.plot([xs[0], xs[-1]], [-0.8, -0.8], color=MUTED, lw=1, zorder=1)

    y_area, LH = -1.55, 0.5
    for k, (area, g) in enumerate(groups):
        x = xs[k]
        g = g.sort_values(["early_start", "id"])
        ncrit = int(g["critical"].sum())
        ax.plot([x, x], [-0.8, y_area + 0.4], color=MUTED, lw=1, zorder=1)
        _box(ax, x, y_area, BW, 0.8, RED if ncrit else BLUE, lw=1.5, fill="#fdf0f0" if ncrit else "#eef4fc")
        ax.text(x, y_area + 0.2, f"1.{k + 1}  {textwrap.shorten(area, 20, placeholder='…')}", ha="center",
                va="center", fontsize=8, fontweight="bold", color=INK, zorder=5)
        ax.text(x, y_area - 0.04, f"{len(g)} activities, {ncrit} critical",
                ha="center", va="center", fontsize=6.3, color=RED if ncrit else MUTED, zorder=5)
        ax.text(x, y_area - 0.24, f"{g['early_start'].min():%m/%d/%y} to {g['early_finish'].max():%m/%d/%y}",
                ha="center", va="center", fontsize=6.3, color=MUTED, zorder=5)
        rows = list(g.itertuples())
        extra = len(rows) - max_rows if len(rows) > max_rows + 1 else 0
        rows = rows[:max_rows] if extra else rows
        lx = x - BW / 2 + 0.12
        y = y_area - 0.4
        for j, r in enumerate(rows):
            y = y_area - 0.95 - j * LH
            crit = bool(r.critical)
            _box(ax, x + 0.12, y, BW - 0.24, 0.4, RED if crit else "#b8bec7", lw=1.3 if crit else 0.8)
            ax.plot([lx, lx + 0.06], [y, y], color=MUTED, lw=0.8, zorder=1)
            ax.text(x - BW / 2 + 0.3, y + 0.065, r.id + ("" if str(r.name) == r.id else "  " + textwrap.shorten(str(r.name), 22, placeholder="…")),
                    ha="left", va="center", fontsize=6.3, color=INK, zorder=5,
                    fontweight="bold" if crit else "normal")
            ax.text(x - BW / 2 + 0.3, y - 0.1, f"{int(r.duration)} d  |  TF {int(r.total_float)}",
                    ha="left", va="center", fontsize=5.8, color=MUTED, zorder=5)
        if rows:
            ax.plot([lx, lx], [y_area - 0.4, y], color=MUTED, lw=0.8, zorder=1)
        if extra:
            ax.text(x, y - LH * 0.8, f"+ {extra} more", ha="center", va="center", fontsize=7, color=MUTED)

    ax.set_xlim(xs[0] - BW / 2 - 0.2, xs[-1] + BW / 2 + 0.2)
    ax.set_ylim(y_area - 1.2 - shown * LH, 0.6)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(f"Work breakdown structure: {project}", loc="left", fontsize=12, color=INK, pad=10)
    legend = [Patch(facecolor="white", edgecolor=RED, label="Critical activity (0 float)"),
              Patch(facecolor="white", edgecolor="#b8bec7", label="Activity with float")]
    ax.legend(handles=legend, frameon=False, fontsize=7.5, loc="upper right", ncol=2, bbox_to_anchor=(1, 1.06))
    fig.tight_layout()
    return fig


def main():
    act, need = load()
    charts = [(gantt(act, need), "chart_gantt.png"), (readiness(need), "chart_utility_readiness.png"),
              (slip(act), "chart_baseline_slip.png"), (wbs(act), "chart_wbs.png")]
    links = load_links()
    if len(links):
        charts.append((network(act, links), "chart_network.png"))
    for fig, name in charts:
        fig.savefig(HERE / name, dpi=160, bbox_inches="tight")
        plt.close(fig)
    print("wrote " + ", ".join(name for _, name in charts))


if __name__ == "__main__":
    main()
