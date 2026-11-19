"""Figures for the report (owner: Habib Hasanov). 300 dpi PNGs in results/figures/.

    docker compose run --rm client python -m analysis.plots      (make figures runs it)

fault_availability_timeline.png  Exp 3a/3b/3c/5: per-second success of the ONE/QUORUM/ALL
                                 probe, fault window and gossip detection marked
detection_times.png              gossip detection time per fault type (Exp 3, Exp 5)
exp2_latency_distribution.png    Exp 2: latency distribution per CL and mode (box: p25-p75,
                                 whiskers p1-p99)
exp4_hints_drain.png             Exp 4a: pending hint bytes on the coordinators after the
                                 dead replica restarts (only when Exp 4 evidence exists)
exp6_lwt_latency.png             Exp 6: LWT vs plain QUORUM insert latency (only with Exp 6 data)

Colour follows the consistency level everywhere (same slots as workload/exp2_summary.py).
Every figure is drawn from committed CSVs; a figure whose data does not exist yet is
skipped with a message, and the script fails only when results/raw/ is empty.
"""
import argparse
import glob
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from analysis.common import CL_ORDER, fault_runs, load_detection, load_events, load_raw  # noqa: E402

FIG_DIR = os.path.join("results", "figures")
# Validated categorical slots (dataviz reference palette, light surface).
CL_COLOR = {"ONE": "#2a78d6", "QUORUM": "#eb6834", "ALL": "#1baf7a"}
LWT_COLOR = "#6250d6"                      # slot 7 (violet): Paxos LWT, distinct from every CL colour
INK, INK_2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
# Sequential blue ramp, light -> dark (steps 100..700): dark = available, light = failing.
SEQ = LinearSegmentedColormap.from_list("avail", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
SCENARIO_TITLE = {
    ("exp3", "3a"): "Exp 3a - one node (cass3) killed",
    ("exp3", "3b"): "Exp 3b - two nodes killed (cass2, then cass3)",
    ("exp3", "3c"): "Exp 3c - graceful stop, then kill (cass3)",
    ("exp5", "partition"): "Exp 5 - network partition (cass3 isolated, container running)",
}

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5, "axes.edgecolor": AXIS,
                     "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
                     "axes.titlesize": 9, "axes.titlecolor": INK, "legend.frameon": False})


def _style(ax, grid_axis="y"):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis=grid_axis, color=GRID, lw=0.6)
    ax.set_axisbelow(True)


def _save(fig, out_dir, name):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {path}")
    return path


# --------------------------------------------------------------------------- Exp 3 / 5
def availability_matrix(run, bin_s=1.0):
    """CL x time-bin success fraction for one probe run (NaN where no operation started)."""
    end = run["t_s"].max()
    edges = np.arange(0, end + bin_s, bin_s)
    mat = np.full((len(CL_ORDER), len(edges) - 1), np.nan)
    for i, cl in enumerate(CL_ORDER):
        g = run[run["cl"] == cl]
        idx = np.clip(np.digitize(g["t_s"], edges) - 1, 0, len(edges) - 2)
        tot = np.bincount(idx, minlength=len(edges) - 1)
        ok = np.bincount(idx, weights=g["ok"].astype(float), minlength=len(edges) - 1)
        with np.errstate(invalid="ignore", divide="ignore"):
            mat[i] = np.where(tot > 0, ok / tot, np.nan)
    return mat, edges


def detection_offsets(det, run, intervals):
    """Seconds (from run start) at which peers logged the faulted node DOWN, per interval."""
    if det.empty:
        return []
    t0 = run["ts"].min()
    marks = []
    for start_s, _end, node, action in intervals:
        inj = (t0 + pd.Timedelta(seconds=start_s)).floor("s")
        d = det[(det["transition"] == "down") & (det["action"] == action)
                & (pd.to_datetime(det["injected_utc"], utc=True) == inj)]
        d = d[(d["node"] == node) | (action == "partition")]
        if len(d):
            marks.append(start_s + float(d["detection_seconds"].min()))
    return marks


def plot_fault_timelines(probe, intervals, det, out_dir, rep=1):
    if probe.empty:
        print("skip fault_availability_timeline.png: no Exp 3/5 availability-probe data")
        return None
    chosen = []
    for key in SCENARIO_TITLE:
        g = probe[(probe["experiment"] == key[0]) & (probe["scenario"] == key[1])]
        if g.empty:
            continue
        reps = sorted(g["rep"].unique())
        r = rep if rep in reps else reps[0]
        run_id = g[g["rep"] == r]["run_id"].iloc[0]
        chosen.append((key, run_id, g[g["run_id"] == run_id]))
    fig, axes = plt.subplots(len(chosen), 1, figsize=(7.2, 1.25 * len(chosen) + 0.7), squeeze=False)
    xmax = max(g["t_s"].max() for _, _, g in chosen)
    im = None
    for ax, (key, run_id, run) in zip(axes[:, 0], chosen):
        mat, edges = availability_matrix(run)
        masked = np.ma.masked_invalid(mat)
        im = ax.pcolormesh(edges, np.arange(len(CL_ORDER) + 1), masked, cmap=SEQ, vmin=0, vmax=1,
                           shading="flat", edgecolors="white", linewidth=0.15)
        ax.set_yticks(np.arange(len(CL_ORDER)) + 0.5, CL_ORDER)
        ax.invert_yaxis()
        ax.set_xlim(0, xmax)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for start_s, end_s, node, action in intervals.get(run_id, []):
            ax.annotate("", xy=(end_s, -0.18), xytext=(start_s, -0.18), annotation_clip=False,
                        arrowprops=dict(arrowstyle="|-|", color=INK_2, lw=0.9, mutation_scale=3,
                                        shrinkA=0, shrinkB=0))
            ax.text(start_s, -0.42, f"{action} {node}", fontsize=7, color=INK_2, va="bottom",
                    clip_on=False)
            ax.axvline(start_s, color=INK, lw=0.8, ls=(0, (2, 2)))
            ax.axvline(end_s, color=INK, lw=0.8, ls=(0, (2, 2)))
        for x in detection_offsets(det, run, intervals.get(run_id, [])):
            ax.axvline(x, color=CL_COLOR["QUORUM"], lw=1.2)
        ax.set_title(f"{SCENARIO_TITLE[key]}   (rep {run['rep'].iloc[0]})", loc="left", pad=14)
    axes[-1, 0].set_xlabel("seconds since probe start (1 s bins)")
    cax = fig.add_axes([0.92, 0.25, 0.015, 0.5])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label("operations succeeding (%)", color=INK_2)
    cb.set_ticks([0, 0.5, 1], labels=["0", "50", "100"])
    cb.outline.set_visible(False)
    fig.text(0.02, 0.005, "Dashed lines: fault injected / node restarted or healed.  Orange line: first "
             "peer logs the node DOWN (gossip phi-accrual detection).\nWhite cells: no operation started - "
             "that level's probe thread was blocked waiting for a 5 s client timeout (requests coordinated by the "
             "unreachable node).",
             fontsize=6.8, color=INK_2)
    fig.subplots_adjust(left=0.1, right=0.9, hspace=0.95, top=0.93, bottom=0.13)
    return _save(fig, out_dir, "fault_availability_timeline.png")


def plot_detection(det, events, out_dir):
    if det.empty:
        print("skip detection_times.png: no detection measurements")
        return None
    det = det.copy()
    partitioned = set(events.loc[events["action"] == "partition", "node"]) if not events.empty else set()
    label = {"stop": "graceful stop", "kill": "SIGKILL (crash)", "start": "restart -> UP"}

    def name(r):
        if r["action"] == "partition":
            return "partition, majority sees node" if r["node"] in partitioned else "partition, isolated node sees peer"
        return label.get(r["action"], r["action"]) + ("" if r["transition"] == "down" or r["action"] == "start"
                                                      else f" ({r['transition']})")
    det["fault"] = det.apply(name, axis=1)
    order = (det.groupby("fault")["detection_seconds"].mean().sort_values().index.tolist())
    fig, ax = plt.subplots(figsize=(6.4, 0.45 * len(order) + 0.9))
    rng = np.random.default_rng(3)
    for i, f in enumerate(order):
        v = det[det["fault"] == f]["detection_seconds"].to_numpy()
        ax.scatter(v, i + rng.uniform(-0.12, 0.12, len(v)), s=18, color=CL_COLOR["ONE"], alpha=0.85,
                   edgecolors="white", linewidths=0.6, zorder=3)
        ax.plot([v.mean(), v.mean()], [i - 0.3, i + 0.3], color=INK, lw=2, zorder=4)
        ax.text(v.max() + 0.6, i, f"mean {v.mean():.1f} s (n={len(v)})", va="center", fontsize=7.5, color=INK_2)
    ax.set_yticks(range(len(order)), order)
    ax.set_xlabel("seconds from fault command to the peer's 'is now DOWN/UP' log line")
    ax.set_xlim(0, det["detection_seconds"].max() * 1.35)
    _style(ax, "x")
    ax.set_title("Gossip failure detection (Exp 3 and Exp 5; dots = runs, bar = mean)", loc="left")
    return _save(fig, out_dir, "detection_times.png")


# --------------------------------------------------------------------------- Exp 2
def plot_exp2_distribution(raw, out_dir):
    d = raw[(raw["dir_exp"] == "exp2") & raw["file_variant"].isin(["write", "read", "mixed"]) & raw["ok"]]
    if d.empty:
        print("skip exp2_latency_distribution.png: no Exp 2 grid data")
        return None
    modes = ["write", "read", "mixed"]
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.5), sharey=True)
    for ax, mode in zip(axes, modes):
        stats = []
        for cl in CL_ORDER:
            v = d[(d["file_variant"] == mode) & (d["cl"] == cl)]["latency_ms"].dropna()
            stats.append({"label": cl, "med": v.median(), "q1": v.quantile(0.25), "q3": v.quantile(0.75),
                          "whislo": v.quantile(0.01), "whishi": v.quantile(0.99), "fliers": []})
        bp = ax.bxp(stats, showfliers=False, patch_artist=True, widths=0.55,
                    medianprops=dict(color=INK, lw=1.6), whiskerprops=dict(color=INK_2, lw=1),
                    capprops=dict(color=INK_2, lw=1))
        for patch, cl in zip(bp["boxes"], CL_ORDER):
            patch.set(facecolor=CL_COLOR[cl], edgecolor="white", lw=1.5)
        for i, s in enumerate(stats, start=1):
            ax.annotate(f"{s['med']:.2f}", (i, s["whishi"]), xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=7, color=INK_2)
        ax.set_title(f"{mode}", loc="left")
        _style(ax)
    axes[0].set_ylabel("latency of successful ops (ms)")
    fig.suptitle("Exp 2: latency per consistency level (box p25-p75, line = median (labelled), "
                 "whiskers p1-p99; 3 reps pooled)", x=0.01, ha="left", fontsize=8.5, color=INK)
    fig.tight_layout()
    return _save(fig, out_dir, "exp2_latency_distribution.png")


# --------------------------------------------------------------------------- Exp 4 / Exp 6
def plot_hints_drain(timeline_path, out_dir):
    if not timeline_path:
        print("skip exp4_hints_drain.png: no results/logs/exp4/*/4a_hints_timeline.csv (run make exp4)")
        return None
    t = pd.read_csv(timeline_path)
    peers = [c[:-6] for c in t.columns if c.endswith("_bytes")]
    total = sum(t[f"{p}_bytes"] for p in peers) / 1024.0
    fig, ax = plt.subplots(figsize=(6.4, 2.4))
    ax.plot(t["t_s"], total, color=LWT_COLOR, lw=2)
    un = t[t["peer_view_un"] == 1]["t_s"]
    if len(un):
        ax.axvline(un.iloc[0], color=INK, lw=0.9, ls=(0, (2, 2)))
        ax.text(un.iloc[0], total.max() * 1.02 if total.max() > 0 else 1, " restarted node UN",
                fontsize=7.5, color=INK_2, va="bottom")
    ax.set_xlabel("seconds since docker start of the dead replica")
    ax.set_ylabel(f"pending hint files on {' + '.join(peers)} (KiB)")
    ax.set_ylim(bottom=0)
    _style(ax)
    ax.set_title("Exp 4a: hinted handoff drains after the replica returns", loc="left")
    return _save(fig, out_dir, "exp4_hints_drain.png")


def plot_lwt_latency(raw, out_dir):
    d = raw[(raw["dir_exp"] == "exp6") & (raw["file_variant"] == "latency") & raw["ok"]]
    if d.empty:
        print("skip exp6_lwt_latency.png: no Exp 6 latency data (run make exp6)")
        return None
    d = d[d["run_id"] == d.sort_values("stamp")["run_id"].iloc[-1]]
    series = [("write", "plain INSERT, CL QUORUM", CL_COLOR["QUORUM"]),
              ("lwt", "INSERT ... IF NOT EXISTS (Paxos, SERIAL)", LWT_COLOR)]
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    for op, label, color in series:
        v = np.sort(d[d["op"] == op]["latency_ms"].dropna().to_numpy())
        if not len(v):
            continue
        y = np.arange(1, len(v) + 1) / len(v)
        ax.plot(v, y, color=color, lw=2, label=f"{label}  (p50 {np.median(v):.2f} ms)")
    ax.set_xscale("log")
    ax.set_xlabel("latency (ms, log scale)")
    ax.set_ylabel("fraction of operations")
    ax.legend(loc="lower right", fontsize=7.5)
    _style(ax, "both")
    ax.set_title("Exp 6: cost of consensus - LWT vs plain write latency (ECDF)", loc="left")
    return _save(fig, out_dir, "exp6_lwt_latency.png")


def latest_timeline(root=os.path.join("results", "logs", "exp4")):
    paths = sorted(glob.glob(os.path.join(root, "*", "4a_hints_timeline.csv")), key=os.path.getmtime)
    return paths[-1] if paths else None


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m analysis.plots", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raw", default=os.path.join("results", "raw"))
    p.add_argument("--out", default=FIG_DIR)
    p.add_argument("--rep", type=int, default=1, help="repetition shown in the timeline figure")
    a = p.parse_args(argv)
    raw = load_raw(a.raw, verbose=False)
    if raw.empty:
        print(f"ERROR: no raw CSV in {a.raw}/<exp>/ - nothing to plot", file=sys.stderr)
        return 2
    events = load_events()
    probe, intervals = fault_runs(raw, events)
    det = load_detection()
    plot_fault_timelines(probe, intervals, det, a.out, a.rep)
    plot_detection(det, events, a.out)
    plot_exp2_distribution(raw, a.out)
    plot_hints_drain(latest_timeline(), a.out)
    plot_lwt_latency(raw, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
