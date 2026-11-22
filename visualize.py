"""Charts for the schedule-health outputs.

Run schedule_health.py first, then:

    python visualize.py

Reads out_activities.csv and out_need_date_alignment.csv from this folder and writes:
    chart_gantt.png              Gantt chart: critical path in red, total float, baseline finish, need dates
    chart_utility_readiness.png  Margin of each need-date milestone against its need date
    chart_baseline_slip.png      Forecast finish minus baseline finish per activity
    chart_network.png            Network (precedence) diagram: activity boxes and logic links
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


def _tracks(segs, lo_room):
    """Give overlapping segments in one channel separate tracks. segs: list of (lo, hi, key).
    Returns {key: offset from the channel center}."""
    ends, track = [], {}
    for lo, hi, key in sorted(segs):
        t = next((k for k, e in enumerate(ends) if e < lo - 0.02), None)
        if t is None:
            t, ends = len(ends), ends + [hi]
        ends[t] = hi
        track[key] = t
    n = len(ends)
    step = min(0.11, 2 * lo_room / max(n, 1))
    return {k: (t - (n - 1) / 2) * step for k, t in track.items()}


def _route_links(lk, col, row, pos, W, DX, DY):
    """Right-angle routes that never pass behind a box. A link leaves the right side of its
    predecessor, runs in the empty channels between columns and the empty lanes between rows,
    and enters the left side of its successor. Links sharing a channel get their own track."""
    occupied = {(col[i], row[i]) for i in pos}
    # Row corridors: a box's own links use the channel next to it on its row. A link that runs
    # along a row claims the cells and channels it crosses, so two links never share a stretch.
    claim = defaultdict(set)
    for r in lk.itertuples():
        claim[("ch", col[r.predecessor], row[r.predecessor])].add(("out", r.predecessor))
        claim[("ch", col[r.successor] - 1, row[r.successor])].add(("in", r.successor))

    def run(rr, a, b, own, turn=None):
        """Units on row rr from channel a to channel b (cells in between); None if blocked.
        The channel where the link turns is left out: track order keeps its stubs apart."""
        units = [("ch", c, rr) for c in range(a, b + 1) if c != turn] +                 [("cell", c, rr) for c in range(a + 1, b + 1)]
        if any((u[0] == "cell" and (u[1], u[2]) in occupied) or not claim[u] <= own for u in units):
            return None
        return units

    order = sorted(range(len(lk)), key=lambda k: (not lk.iloc[k]["critical"],
                                                  col[lk.iloc[k]["successor"]] - col[lk.iloc[k]["predecessor"]]))
    plans = []
    for k in order:
        r = next(lk.iloc[[k]].itertuples())
        p, s = r.predecessor, r.successor
        c1, c2, r1, r2 = col[p], col[s], row[p], row[s]
        own = {("out", p), ("in", s)}
        if r1 == r2 and (u := run(r1, c1, c2 - 1, own)) is not None:
            plan = ("straight",)
        elif c2 == c1 + 1:
            u, plan = [], ("bend", c1)   # next column: one turn in the gap between them
        elif (u := run(r2, c1, c2 - 1, own, turn=c1)) is not None:
            plan = ("bend", c1)          # turn right after the predecessor, run along the successor's row
        elif (u := run(r1, c1, c2 - 1, own, turn=c2 - 1)) is not None:
            plan = ("bend", c2 - 1)      # run along the predecessor's row, turn just before the successor
        else:
            u = []
            lane = r2 - 0.5 if r1 <= r2 else r2 + 0.5   # gap between rows, next to the successor
            plan = ("lane", c1, lane, c2 - 1)
        for unit in u:
            claim[unit].add(("link", k))
        plans.append((k, r, plan))

    # Vertical pieces in each channel between columns. Each has a row where a horizontal piece
    # leaves it to the left (from a predecessor) and a row where one leaves it to the right
    # (toward a successor). Ordering the tracks so that every left piece on a row sits left of
    # every right piece on that row keeps exit and entry stubs from overlapping.
    vseg, hseg = defaultdict(dict), defaultdict(list)
    for k, r, plan in plans:
        r1, r2 = row[r.predecessor], row[r.successor]
        if plan[0] == "bend":
            vseg[plan[1]][(k, 0)] = (r1, r2, min(r1, r2))
        elif plan[0] == "lane":
            _, ca, lane, cb = plan
            vseg[ca][(k, 0)] = (r1, None, min(r1, lane))
            vseg[cb][(k, 1)] = (None, r2, min(lane, r2))
            hseg[lane].append((ca, cb, k))
    voff = {}
    for c, segs in vseg.items():
        keys = sorted(segs, key=lambda key: (segs[key][2], key))
        before = {key: set() for key in keys}   # keys that must sit left of this one
        for a_ in keys:
            for b_ in keys:
                if a_ != b_ and segs[a_][0] is not None and segs[a_][0] == segs[b_][1]:
                    before[b_].add(a_)
        ordered = []
        while keys:
            nxt = next((key for key in keys if not (before[key] - set(ordered))), keys[0])
            ordered.append(nxt)
            keys.remove(nxt)
        n = len(ordered)
        step = min(0.11, 2 * ((DX - W) / 2 - 0.08) / max(n, 1))
        voff.update({key: (t - (n - 1) / 2) * step for t, key in enumerate(ordered)})
    hoff = {}
    for lane, segs in hseg.items():
        hoff.update(_tracks([(a * DX, b * DX + 0.01, k) for a, b, k in segs], 0.16))

    xc = lambda c: c * DX + DX / 2
    out = []
    for k, r, plan in plans:
        (x1, y1), (x2, y2) = pos[r.predecessor], pos[r.successor]
        start, end = (x1 + W / 2, y1), (x2 - W / 2, y2)
        if plan[0] == "straight":
            pts = [start, end]
        elif plan[0] == "bend":
            x = xc(plan[1]) + voff[(k, 0)]
            pts = [start, (x, y1), (x, y2), end]
        else:
            _, ca, lane, cb = plan
            xa, xb = xc(ca) + voff[(k, 0)], xc(cb) + voff[(k, 1)]
            yl = -lane * DY + hoff[k]
            pts = [start, (xa, y1), (xa, yl), (xb, yl), (xb, y2), end]
        out.append({"points": pts, "critical": bool(r.critical), "type": r.type, "lag": int(r.lag)})
    return out


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
    W, H, DX, DY = 1.55, 0.78, 2.35, 1.3
    ncol = max(cols) + 1
    nrow = max(row.values()) - min(row.values()) + 1
    fig, ax = plt.subplots(figsize=(max(7, ncol * DX * 0.8 + 1), max(3.2, nrow * DY * 0.8 + 1.6)))
    pos = {i: (col[i] * DX, -row[i] * DY) for i in ids}
    for r in _route_links(lk, col, row, pos, W, DX, DY):
        crit, pts = r["critical"], r["points"]
        color, lw = (RED, 1.6) if crit else ("#9aa1ab", 0.9)
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=color, lw=lw, zorder=2.5 if crit else 2,
                solid_joinstyle="miter", solid_capstyle="butt")
        (xe, ye) = pts[-1]
        ax.add_patch(FancyArrowPatch((xe - 0.05, ye), (xe, ye), arrowstyle="-|>", mutation_scale=9,
                                     color=color, lw=lw, zorder=2.6 if crit else 2.1, shrinkA=0, shrinkB=0))
        label = _link_label(r["type"], r["lag"])
        if label:  # just right of the predecessor, where the link starts
            ax.text(pts[0][0] + 0.04, pts[0][1] + 0.04, label, ha="left", va="bottom", fontsize=6.3,
                    color=INK, zorder=4, bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none"))

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
    ax.set_ylim(min(ys) - DY / 2 - 0.25, max(ys) + DY / 2 + 0.25)
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


def main():
    act, need = load()
    charts = [(gantt(act, need), "chart_gantt.png"), (readiness(need), "chart_utility_readiness.png"),
              (slip(act), "chart_baseline_slip.png")]
    links = load_links()
    if len(links):
        charts.append((network(act, links), "chart_network.png"))
    for fig, name in charts:
        fig.savefig(HERE / name, dpi=160, bbox_inches="tight")
        plt.close(fig)
    print("wrote " + ", ".join(name for _, name in charts))


if __name__ == "__main__":
    main()
