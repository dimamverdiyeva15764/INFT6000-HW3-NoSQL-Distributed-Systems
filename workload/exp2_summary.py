"""Experiment 2 summary: turns the raw CSVs into tables, LaTeX numbers and figures.

    docker compose run --rm client python -m workload.exp2_summary      (or: make exp2-report)

Inputs   results/raw/exp2/*.csv  (written by workload/consistency_matrix.sh)
         results/raw/exp1/exp1_baseline_*.csv  (optional, Exp 1 baseline run)
Outputs  results/summary/exp2_runs.csv         one row per run (file)
         results/summary/exp2_grid.csv         fixed-rate grid: mode x CL, reps pooled
         results/summary/exp2_saturation.csv   closed-loop runs per CL
         results/summary/exp2_probe.csv        freshness probes per write/read pair
         results/summary/exp2_summary.md       the same as Markdown tables
         results/figures/exp2_latency_percentiles.png
         results/figures/exp2_latency_ecdf.png
         results/figures/exp2_saturation.png
         results/figures/exp2_staleness.png
         docs/report/generated/exp2_tables.tex   LaTeX tables for report section 7.2
         docs/report/generated/exp2_numbers.tex  \\exptwo{...} values + data-driven sentences

Every number comes from the CSVs; the script refuses to run without them, so no
placeholder value can reach the report.
"""
import argparse
import glob
import os
import re
import sys

import pandas as pd

N_REPLICAS = 3
CL_ORDER = ["ONE", "QUORUM", "ALL"]
CL_WEIGHT = {"ONE": 1, "TWO": 2, "QUORUM": N_REPLICAS // 2 + 1, "THREE": 3, "ALL": N_REPLICAS}
MODE_ORDER = ["write", "read", "mixed"]
PROBE_ORDER = ["ONE-ONE", "ONE-QUORUM", "QUORUM-QUORUM", "ALL-ONE", "ONE-ALL"]
NAME_RE = re.compile(r"^(?P<exp>[^_]+)_(?P<variant>[^_]+)_(?P<cl>[^_]+)_r(?P<rep>\d+)_(?P<stamp>[^_.]+)")

# Validated categorical slots 1-3 (light surface) - colour follows the CL everywhere.
CL_COLOR = {"ONE": "#2a78d6", "QUORUM": "#eb6834", "ALL": "#1baf7a"}
INK, INK_2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"


# --------------------------------------------------------------------------- loading
def load_runs(pattern):
    frames = []
    for path in sorted(glob.glob(pattern)):
        m = NAME_RE.match(os.path.basename(path))
        if not m:
            print(f"skip {path}: name does not follow <exp>_<variant>_<cl>_r<rep>_<stamp>.csv")
            continue
        df = pd.read_csv(path, dtype={"key": str, "error_type": str, "coordinator": str})
        if df.empty:
            print(f"skip {path}: no rows")
            continue
        df["file"] = os.path.basename(path)
        df["cl_label"] = m.group("cl")
        df["rep"] = int(m.group("rep"))
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts_utc"], format="ISO8601", utc=True)
    df["ok"] = df["outcome"].eq("ok")
    return df


def per_run(df):
    rows = []
    for f, g in df.groupby("file", sort=True):
        span = (g["ts"].max() - g["ts"].min()).total_seconds()
        ok = g[g["ok"]]
        lat = ok["latency_ms"]
        reads = g[(g["op"] == "read") & g["stale"].notna()]
        rows.append({
            "file": f, "variant": g["variant"].iloc[0], "cl": g["cl_label"].iloc[0],
            "rep": g["rep"].iloc[0], "ops": len(g), "ok": len(ok),
            "error_pct": 100.0 * (len(g) - len(ok)) / len(g),
            "seconds": span, "ok_ops_per_s": len(ok) / span if span > 0 else float("nan"),
            "p50_ms": lat.quantile(0.50), "p95_ms": lat.quantile(0.95), "p99_ms": lat.quantile(0.99),
            "mean_ms": lat.mean(),
            "probes": len(reads), "stale": int(reads["stale"].sum()) if len(reads) else 0,
        })
    return pd.DataFrame(rows)


def pooled(df, runs, keys):
    """Latency percentiles pooled over repetitions; throughput as mean/sd of per-run values."""
    out = []
    for key, g in df.groupby(keys, sort=False):
        key = key if isinstance(key, tuple) else (key,)
        lat = g.loc[g["ok"], "latency_ms"]
        r = runs.set_index("file").loc[g["file"].unique()]
        errs = g.loc[~g["ok"], "outcome"].value_counts()
        out.append(dict(zip(keys, key)) | {
            "runs": len(r), "ops": len(g), "ok": int(g["ok"].sum()),
            "error_pct": 100.0 * (~g["ok"]).sum() / len(g),
            "errors": ", ".join(f"{k}={v}" for k, v in errs.items()),
            "p50_ms": lat.quantile(0.50), "p95_ms": lat.quantile(0.95), "p99_ms": lat.quantile(0.99),
            "mean_ms": lat.mean(),
            "p50_sd_ms": r["p50_ms"].std(ddof=1) if len(r) > 1 else float("nan"),
            "ok_ops_per_s": r["ok_ops_per_s"].mean(),
            "ok_ops_per_s_sd": r["ok_ops_per_s"].std(ddof=1) if len(r) > 1 else float("nan"),
        })
    return pd.DataFrame(out)


def ordered(frame, col, order):
    frame = frame.copy()
    frame["_o"] = frame[col].map({v: i for i, v in enumerate(order)}).fillna(len(order))
    return frame.sort_values("_o", kind="stable").drop(columns="_o")


# --------------------------------------------------------------------------- tables
def fmt(v, nd=2):
    if v is None or (isinstance(v, float) and v != v):
        return "--"
    return f"{v:.{nd}f}"


def md_table(frame, cols, headers):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for _, r in frame.iterrows():
        lines.append("| " + " | ".join(str(r[c]) if not isinstance(r[c], float) else fmt(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def tex_escape(s):
    return str(s).replace("_", r"\_").replace("%", r"\%")


# --------------------------------------------------------------------------- figures
def _ms_axis(ax):
    """Log x-axis with plain millisecond tick labels (0.5, 1, 2, 5 ...)."""
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator
    ticks = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000]
    ax.set_xscale("log")
    ax.xaxis.set_major_locator(FixedLocator(ticks))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))


def _style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=INK_2, labelsize=8, length=0)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def figures(grid_df, grid, sat, probe, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "text.color": INK,
                         "axes.labelcolor": INK_2, "figure.facecolor": "white", "axes.facecolor": "white"})
    os.makedirs(outdir, exist_ok=True)
    made = []

    # 1. latency percentiles (dumbbell: p50 -> p95 -> p99) per mode, one row per CL
    if not grid.empty:
        modes = [m for m in MODE_ORDER if m in set(grid["mode"])]
        fig, axes = plt.subplots(1, len(modes), figsize=(7.2, 2.4), sharex=True, squeeze=False)
        for ax, mode in zip(axes[0], modes):
            g = grid[grid["mode"] == mode]
            cls = [c for c in CL_ORDER if c in set(g["cl"])]
            for y, cl in enumerate(reversed(cls)):
                r = g[g["cl"] == cl].iloc[0]
                c = CL_COLOR.get(cl, INK_2)
                ax.plot([r.p50_ms, r.p99_ms], [y, y], color=c, linewidth=2, solid_capstyle="round")
                ax.scatter([r.p50_ms], [y], s=46, color=c, edgecolor="white", linewidth=1.5, zorder=3)
                ax.scatter([r.p95_ms], [y], s=30, marker="D", color="white", edgecolor=c, linewidth=1.5, zorder=3)
                ax.scatter([r.p99_ms], [y], s=46, marker="s", color=c, edgecolor="white", linewidth=1.5, zorder=3)
                ax.annotate(f"{r.p50_ms:.2f}", (r.p50_ms, y), xytext=(0, 7), textcoords="offset points",
                            ha="center", fontsize=7, color=INK_2)
            ax.set_yticks(range(len(cls)))
            ax.set_yticklabels(list(reversed(cls)))
            ax.set_ylim(-0.6, len(cls) - 0.4)
            ax.set_title(f"{mode}", fontsize=9, color=INK, loc="left")
            _ms_axis(ax)
            _style(ax)
            ax.grid(False, axis="y")
        axes[0][len(modes) // 2].set_xlabel("latency (ms, log scale) - circle p50, diamond p95, square p99")
        fig.suptitle("Exp 2 - operation latency by consistency level (fixed-rate runs, reps pooled)",
                     fontsize=9.5, x=0.01, ha="left", color=INK)
        fig.tight_layout()
        path = os.path.join(outdir, "exp2_latency_percentiles.png")
        fig.savefig(path, dpi=300)
        plt.close(fig)
        made.append(path)

        # 2. ECDF of latency per mode
        fig, axes = plt.subplots(1, len(modes), figsize=(7.2, 2.5), sharey=True, squeeze=False)
        for ax, mode in zip(axes[0], modes):
            g = grid_df[(grid_df["variant"] == mode) & grid_df["ok"]]
            for cl in CL_ORDER:
                lat = g.loc[g["cl_label"] == cl, "latency_ms"].sort_values().to_numpy()
                if len(lat) == 0:
                    continue
                y = (pd.Series(range(1, len(lat) + 1)) / len(lat)).to_numpy()
                ax.plot(lat, y, color=CL_COLOR[cl], linewidth=2, label=cl)
            _ms_axis(ax)
            ax.set_title(mode, fontsize=9, loc="left")
            ax.set_ylim(0, 1.02)
            _style(ax)
        axes[0][0].set_ylabel("fraction of operations")
        axes[0][len(modes) // 2].set_xlabel("latency (ms, log scale)")
        axes[0][-1].legend(frameon=False, fontsize=8, loc="lower right", title="CL", title_fontsize=8)
        fig.suptitle("Exp 2 - latency distribution (ECDF) by consistency level", fontsize=9.5,
                     x=0.01, ha="left")
        fig.tight_layout()
        path = os.path.join(outdir, "exp2_latency_ecdf.png")
        fig.savefig(path, dpi=300)
        plt.close(fig)
        made.append(path)

    # 3. saturation throughput
    if not sat.empty:
        s = ordered(sat, "cl", CL_ORDER)
        fig, ax = plt.subplots(figsize=(3.5, 2.4))
        xs = range(len(s))
        ax.bar(xs, s["ok_ops_per_s"], width=0.6, color=[CL_COLOR.get(c, INK_2) for c in s["cl"]],
               edgecolor="white", linewidth=2)
        for x, v in zip(xs, s["ok_ops_per_s"]):
            ax.annotate(f"{v:,.0f}", (x, v), xytext=(0, 3), textcoords="offset points", ha="center",
                        fontsize=8, color=INK)
        ax.set_xticks(list(xs))
        ax.set_xticklabels(s["cl"])
        ax.set_ylabel("successful ops/s")
        ax.set_title("Exp 2 - closed-loop saturation throughput\n(mixed 50/50)", fontsize=9, loc="left")
        _style(ax)
        ax.grid(False, axis="x")
        fig.tight_layout()
        path = os.path.join(outdir, "exp2_saturation.png")
        fig.savefig(path, dpi=300)
        plt.close(fig)
        made.append(path)

    # 4. staleness per probe pair
    if not probe.empty:
        p = ordered(probe, "pair", PROBE_ORDER)
        fig, ax = plt.subplots(figsize=(4.2, 2.7))
        xs = range(len(p))
        ax.bar(xs, p["stale_pct"], width=0.6, color=INK_2, edgecolor="white", linewidth=2)
        for x, (v, n, s) in enumerate(zip(p["stale_pct"], p["probes"], p["stale"])):
            ax.annotate(f"{s}/{n}", (x, v), xytext=(0, 3), textcoords="offset points", ha="center",
                        fontsize=7, color=INK)
        ax.set_xticks(list(xs))
        short = {"ONE": "ONE", "QUORUM": "QUO", "ALL": "ALL"}
        ax.set_xticklabels([f"{short.get(a, a)}/{short.get(b, b)}\nR+W={n}" for a, b, n in
                            zip(p["write_cl"], p["read_cl"], p["r_plus_w"])], fontsize=7)
        ax.set_xlabel("write CL / read CL  (N = 3; overlap needs R+W > 3)", fontsize=7.5)
        ax.set_ylabel("stale reads (%)")
        top = max(float(p["stale_pct"].max()), 1.0)
        ax.set_ylim(0, top * 1.25)
        ax.set_title("Exp 2 - freshness probe: read-after-write\nthrough a different coordinator",
                     fontsize=9, loc="left")
        _style(ax)
        ax.grid(False, axis="x")
        fig.tight_layout()
        path = os.path.join(outdir, "exp2_staleness.png")
        fig.savefig(path, dpi=300)
        plt.close(fig)
        made.append(path)
    return made


# --------------------------------------------------------------------------- report text
def sentences(grid, sat, probe, nums):
    s = {}
    # latency ordering per mode
    parts, violations = [], []
    for mode in MODE_ORDER:
        g = grid[grid["mode"] == mode].set_index("cl")
        if not set(CL_ORDER) <= set(g.index):
            continue
        p50 = [g.loc[c, "p50_ms"] for c in CL_ORDER]
        holds = p50[0] <= p50[1] <= p50[2]
        parts.append(f"{mode} {p50[0]:.2f}/{p50[1]:.2f}/{p50[2]:.2f}~ms")
        if not holds:
            violations.append(mode)
    if parts:
        txt = "Median latency at ONE/QUORUM/ALL was " + "; ".join(parts) + ". "
        if not violations:
            txt += ("In every mode the median rose monotonically from ONE to ALL, as expected because the "
                    "coordinator waits for 1, 2 and 3 replica responses respectively.")
        else:
            txt += ("The expected ordering ONE $\\le$ QUORUM $\\le$ ALL did not hold for the "
                    + ", ".join(violations) + " mode(s); on a single host the replica round trip is "
                    "sub-millisecond, so the gap between levels is within run-to-run noise.")
        s["sentence-ordering"] = txt
    # p99 tail
    g = grid.set_index(["mode", "cl"])
    if ("write", "ONE") in g.index and ("write", "ALL") in g.index:
        a, b = g.loc[("write", "ONE"), "p99_ms"], g.loc[("write", "ALL"), "p99_ms"]
        s["sentence-tail"] = (f"The tail widens more than the median: write p99 was {a:.2f}~ms at ONE and "
                              f"{b:.2f}~ms at ALL ({b / a:.1f}$\\times$), because ALL waits for the slowest "
                              f"of the three replicas while ONE only needs the fastest.")
    # error count
    errs = int(grid["ops"].sum() - grid["ok"].sum())
    total = int(grid["ops"].sum())
    s["sentence-errors"] = (f"All {total:,} operations of the fixed-rate grid succeeded." if errs == 0 else
                            f"{errs:,} of {total:,} grid operations failed ({100 * errs / total:.3f}\\%); "
                            "see Table~\\ref{tab:exp2-grid} for the error types.")
    # target rate reached?
    low = grid[grid["ok_ops_per_s"] < 0.97 * nums.get("target_rate", 0)]
    s["sentence-rate"] = ("Every fixed-rate cell sustained its target rate, so latency differences are not caused "
                          "by back-pressure." if low.empty else
                          "The target rate was not sustained in: " + ", ".join(
                              f"{r.mode}/{r.cl} ({r.ok_ops_per_s:.0f} ops/s)" for r in low.itertuples()) + ".")
    # saturation
    if not sat.empty and set(CL_ORDER) <= set(sat["cl"]):
        t = sat.set_index("cl")["ok_ops_per_s"]
        diff = 100 * (t["ALL"] / t["ONE"] - 1)
        rel = (f"{abs(diff):.0f}\\% {'lower' if diff < 0 else 'higher'} at ALL than at ONE"
               if abs(diff) >= 0.5 else "practically equal at ALL and ONE")
        s["sentence-saturation"] = (
            f"Closed-loop saturation throughput was {t['ONE']:,.0f}, {t['QUORUM']:,.0f} and {t['ALL']:,.0f} ops/s "
            f"at ONE, QUORUM and ALL ({rel}). With RF = N = 3 every replica applies every write whatever the "
            "CL, so for writes only the client's waiting time differs; a read at QUORUM or ALL additionally "
            "sends one or two digest requests, which adds server work. Because the Python client itself "
            "is CPU-bound near saturation, these values are a lower bound on cluster capacity.")
    # staleness
    if not probe.empty:
        weak = probe[~probe["overlap"]]
        strong = probe[probe["overlap"]]
        ws, wn = int(weak["stale"].sum()), int(weak["probes"].sum())
        ss, sn = int(strong["stale"].sum()), int(strong["probes"].sum())
        txt = (f"Pairs with $R+W\\le N$ returned {ws} stale value(s) in {wn:,} probes "
               f"({100 * ws / wn if wn else 0:.2f}\\%); ")
        txt += (f"pairs with $R+W>N$ returned {ss} in {sn:,} probes"
                + (", consistent with the quorum-overlap guarantee." if ss == 0 else
                   " - this contradicts quorum overlap and must be investigated (clock skew, a failed write "
                   "counted as acknowledged, or a topology change during the run)."))
        if ws == 0:
            txt += (" No staleness was observed even without overlap: on a healthy single-host cluster the "
                    "replica mutations arrive long before the client's next request, so the inconsistency "
                    "window is shorter than one client round trip. Staleness becomes visible once a replica "
                    "misses writes (Exp 4b, Exp 5).")
        s["sentence-staleness"] = txt
    return s


def write_tex(path_tables, path_numbers, grid, sat, probe, exp1, nums, sents):
    os.makedirs(os.path.dirname(path_tables), exist_ok=True)
    g = ordered(ordered(grid, "cl", CL_ORDER), "mode", MODE_ORDER)
    lines = [
        "% Generated by workload/exp2_summary.py - do not edit by hand.",
        "\\begin{table*}[t]\\centering\\footnotesize",
        "\\caption{Experiment 2: latency and throughput per consistency level (fixed-rate open loop, "
        f"{nums.get('target_rate', 0):.0f}~ops/s, {nums.get('reps', 0)} repetitions pooled; latency of "
        "successful operations).}\\label{tab:exp2-grid}",
        "\\begin{tabular}{llrrrrrrl}\\hline",
        "Mode & CL & p50 (ms) & p95 (ms) & p99 (ms) & mean (ms) & ops/s (mean$\\pm$sd) & err.\\ (\\%) & errors \\\\ \\hline",
    ]
    for r in g.itertuples():
        lines.append(f"{r.mode} & {r.cl} & {fmt(r.p50_ms)} & {fmt(r.p95_ms)} & {fmt(r.p99_ms)} & "
                     f"{fmt(r.mean_ms)} & {fmt(r.ok_ops_per_s, 1)}$\\pm${fmt(r.ok_ops_per_s_sd, 1)} & "
                     f"{fmt(r.error_pct, 3)} & {tex_escape(r.errors) or '--'} \\\\")
    lines += ["\\hline\\end{tabular}\\end{table*}", ""]
    if not probe.empty:
        p = ordered(probe, "pair", PROBE_ORDER)
        lines += [
            "\\begin{table}[t]\\centering\\footnotesize",
            "\\caption{Experiment 2: freshness probes (write then immediate read through a different "
            "coordinator; $N=3$).}\\label{tab:exp2-probe}",
            "\\begin{tabular}{llcrrr}\\hline",
            "$W$ & $R$ & $R+W>N$ & probes & stale & stale (\\%) \\\\ \\hline",
        ]
        for r in p.itertuples():
            lines.append(f"{r.write_cl} & {r.read_cl} & {'yes' if r.overlap else 'no'} & {r.probes} & "
                         f"{r.stale} & {fmt(r.stale_pct, 2)} \\\\")
        lines += ["\\hline\\end{tabular}\\end{table}", ""]
    with open(path_tables, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    macros = ["% Generated by workload/exp2_summary.py - do not edit by hand.",
              "% Use \\exptwo{<name>} in the report; names are listed below."]

    def put(name, value):
        macros.append(f"\\expandafter\\def\\csname exptwo@{name}\\endcsname{{{value}}}")

    for r in grid.itertuples():
        for k in ("p50_ms", "p95_ms", "p99_ms", "mean_ms"):
            put(f"{r.mode}-{r.cl}-{k.split('_')[0]}", fmt(getattr(r, k)))
        put(f"{r.mode}-{r.cl}-tput", fmt(r.ok_ops_per_s, 1))
        put(f"{r.mode}-{r.cl}-err", fmt(r.error_pct, 3))
    for r in sat.itertuples():
        put(f"max-{r.cl}-tput", f"{r.ok_ops_per_s:,.0f}")
        put(f"max-{r.cl}-p99", fmt(r.p99_ms))
    for r in probe.itertuples():
        put(f"probe-{r.pair}-stale", str(r.stale))
        put(f"probe-{r.pair}-probes", str(r.probes))
        put(f"probe-{r.pair}-pct", fmt(r.stale_pct, 2))
    for k, v in nums.items():
        put(k, v if isinstance(v, str) else fmt(v, 0) if float(v).is_integer() else fmt(v))
    if exp1 is not None:
        for k, v in exp1.items():
            put(f"exp1-{k}", v)
    for k, v in sents.items():
        put(k, v)
    with open(path_numbers, "w", encoding="utf-8") as fh:
        fh.write("\n".join(macros) + "\n")


# --------------------------------------------------------------------------- main
def exp1_baseline(pattern):
    df = load_runs(pattern)
    if df.empty:
        return None, None
    runs = per_run(df)
    lat = df.loc[df["ok"], "latency_ms"]
    info = {
        "ops": f"{len(df):,}", "ok": f"{int(df['ok'].sum()):,}",
        "err": fmt(100.0 * (~df["ok"]).sum() / len(df), 3),
        "tput": fmt(runs["ok_ops_per_s"].mean(), 1),
        "p50": fmt(lat.quantile(0.5)), "p95": fmt(lat.quantile(0.95)), "p99": fmt(lat.quantile(0.99)),
        "files": str(len(runs)),
    }
    return info, runs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default="results/raw/exp2/*.csv")
    ap.add_argument("--exp1", default="results/raw/exp1/exp1_baseline_*.csv")
    ap.add_argument("--summary-dir", default="results/summary")
    ap.add_argument("--figure-dir", default="results/figures")
    ap.add_argument("--tex-dir", default="docs/report/generated")
    ap.add_argument("--target-rate", type=float, default=200.0, help="rate of the fixed-rate grid")
    args = ap.parse_args(argv)

    df = load_runs(args.raw)
    if df.empty:
        print(f"ERROR: no Experiment 2 data matches {args.raw} - run 'make exp2' first. "
              "Nothing was written (no placeholder numbers).", file=sys.stderr)
        return 1
    runs = per_run(df)

    grid_df = df[df["variant"].isin(MODE_ORDER)].copy()
    grid = pooled(grid_df.assign(mode=grid_df["variant"], cl=grid_df["cl_label"]), runs, ["mode", "cl"])
    sat_df = df[df["variant"] == "max"]
    sat = pooled(sat_df.assign(cl=sat_df["cl_label"]), runs, ["cl"]) if not sat_df.empty else pd.DataFrame()
    pdf = df[(df["variant"] == "probe") & (df["op"] == "read")]
    probe_rows = []
    for pair, g in pdf.groupby("cl_label", sort=False):
        w, r = pair.split("-", 1)
        measured = g[g["stale"].notna()]
        probe_rows.append({
            "pair": pair, "write_cl": w, "read_cl": r,
            "r_plus_w": CL_WEIGHT.get(w, 0) + CL_WEIGHT.get(r, 0),
            "overlap": CL_WEIGHT.get(w, 0) + CL_WEIGHT.get(r, 0) > N_REPLICAS,
            "runs": g["file"].nunique(), "probes": len(measured), "stale": int(measured["stale"].sum()),
            "stale_pct": 100.0 * measured["stale"].sum() / len(measured) if len(measured) else float("nan"),
            "failed_reads": int((~g["ok"]).sum()),
            "read_p50_ms": g.loc[g["ok"], "latency_ms"].quantile(0.5),
        })
    probe = pd.DataFrame(probe_rows)

    os.makedirs(args.summary_dir, exist_ok=True)
    runs.to_csv(os.path.join(args.summary_dir, "exp2_runs.csv"), index=False)
    grid.to_csv(os.path.join(args.summary_dir, "exp2_grid.csv"), index=False)
    if not sat.empty:
        sat.to_csv(os.path.join(args.summary_dir, "exp2_saturation.csv"), index=False)
    if not probe.empty:
        probe.to_csv(os.path.join(args.summary_dir, "exp2_probe.csv"), index=False)

    exp1, exp1_runs = exp1_baseline(args.exp1)
    nums = {"target_rate": args.target_rate,
            "reps": int(runs[runs["variant"].isin(MODE_ORDER)]["rep"].max()) if not grid.empty else 0,
            "runs": len(runs), "ops": f"{len(df):,}"}
    sents = sentences(grid, sat, probe, nums)

    md = ["# Experiment 2 - consistency tuning: summary", "",
          f"Generated from {len(runs)} runs ({len(df):,} logged operations) in `results/raw/exp2/`.", "",
          "## Fixed-rate grid (latency of successful operations, repetitions pooled)", "",
          md_table(ordered(ordered(grid, "cl", CL_ORDER), "mode", MODE_ORDER),
                   ["mode", "cl", "runs", "ops", "p50_ms", "p95_ms", "p99_ms", "mean_ms", "ok_ops_per_s",
                    "ok_ops_per_s_sd", "error_pct", "errors"],
                   ["mode", "CL", "runs", "ops", "p50 ms", "p95 ms", "p99 ms", "mean ms", "ok ops/s",
                    "sd", "error %", "errors"]), ""]
    if not sat.empty:
        md += ["## Closed-loop saturation (mixed)", "",
               md_table(ordered(sat, "cl", CL_ORDER), ["cl", "ops", "ok_ops_per_s", "p50_ms", "p99_ms", "error_pct"],
                        ["CL", "ops", "ok ops/s", "p50 ms", "p99 ms", "error %"]), ""]
    if not probe.empty:
        md += ["## Freshness probes", "",
               md_table(ordered(probe, "pair", PROBE_ORDER),
                        ["write_cl", "read_cl", "r_plus_w", "overlap", "probes", "stale", "stale_pct", "read_p50_ms"],
                        ["W", "R", "R+W", "R+W>N", "probes", "stale", "stale %", "read p50 ms"]), ""]
    if exp1 is not None:
        md += ["## Experiment 1 baseline (mixed, QUORUM, 200 ops/s)", "",
               f"ops {exp1['ops']}, ok {exp1['ok']}, errors {exp1['err']} %, throughput {exp1['tput']} ops/s, "
               f"p50 {exp1['p50']} ms, p95 {exp1['p95']} ms, p99 {exp1['p99']} ms", ""]
    md += ["## Observations (generated from the data)", ""] + [f"- {v}".replace("~", " ").replace("\\%", "%")
                                                               .replace("$\\le$", "<=").replace("$\\times$", "x")
                                                               .replace("$R+W\\le N$", "R+W<=N")
                                                               .replace("$R+W>N$", "R+W>N")
                                                               .replace("Table \\ref{tab:exp2-grid}", "the grid table")
                                                               for v in sents.values()]
    with open(os.path.join(args.summary_dir, "exp2_summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")

    write_tex(os.path.join(args.tex_dir, "exp2_tables.tex"), os.path.join(args.tex_dir, "exp2_numbers.tex"),
              grid, sat, probe, exp1, nums, sents)
    made = figures(grid_df, grid, sat, probe, args.figure_dir)

    print("\n".join(md))
    print("\nwritten:")
    for p in ["exp2_runs.csv", "exp2_grid.csv", "exp2_saturation.csv", "exp2_probe.csv", "exp2_summary.md"]:
        full = os.path.join(args.summary_dir, p)
        if os.path.exists(full):
            print("  " + full)
    for p in made + [os.path.join(args.tex_dir, "exp2_tables.tex"), os.path.join(args.tex_dir, "exp2_numbers.tex")]:
        print("  " + p)
    if "did not hold" in sents.get("sentence-ordering", "") or "contradicts" in sents.get("sentence-staleness", ""):
        print("\nNOTE: a result deviates from the expected behaviour - review the wording of report section 7.2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
