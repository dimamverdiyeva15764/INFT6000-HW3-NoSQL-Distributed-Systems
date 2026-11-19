"""Summary tables for every experiment (owner: Habib Hasanov).

    docker compose run --rm client python -m analysis.summarize      (make figures runs it)

Inputs   results/raw/<exp>/*.csv            per-operation rows, shared schema (CONTRACTS.md)
         results/logs/chaos_events.csv      fault injections (Person 3)
         results/logs/exp*/.../detection_times.csv, failure_detection.csv
         results/logs/exp4/convergence_checks.csv, results/logs/exp4/<run>/measurements.csv
         results/logs/exp6/races.csv, results/logs/exp6/<run>/*paxos_trace.txt
Outputs  results/summary/runs.csv                one row per raw CSV (run)
         results/summary/groups.csv              experiment x variant x op x CL, reps pooled
         results/summary/errors_by_type.csv      failed operations by outcome and driver error
         results/summary/availability_phases.csv Exp 3/5 probe success per CL before/during/after faults
         results/summary/detection_times.csv     gossip detection time per fault type
         results/summary/summary.md              the same as Markdown
         docs/report/generated/exp46_numbers.tex \\expfour{..}, \\expsix{..}, \\expfault{..} values
         docs/report/generated/fault_tables.tex  availability-phase and detection tables (Exp 3/5)

Metrics: count, ok, error %, p50/p95/p99/mean latency of successful operations, achieved
throughput = successful operations / (last - first operation start) of the run, stale %
over reads that carry a freshness verdict. The script exits with status 2 when
results/raw/ holds no data, so no placeholder number can reach the report; values of an
experiment that has not been run print as a bold marker in the PDF instead.
"""
import argparse
import glob
import os
import re
import sys

import pandas as pd

from analysis.common import (CL_ORDER, PHASE_ORDER, fault_runs, load_detection, load_events,
                             load_raw)

SUMMARY_DIR = os.path.join("results", "summary")
GEN_DIR = os.path.join("docs", "report", "generated")
EXP4_LOGS = os.path.join("results", "logs", "exp4")
EXP6_LOGS = os.path.join("results", "logs", "exp6")


def fmt(v, nd=2):
    try:
        if v is None or pd.isna(v):
            return "--"
    except (TypeError, ValueError):
        pass
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def tex_escape(s):
    return (str(s).replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("%", "\\%")
            .replace("&", "\\&").replace("#", "\\#"))


# --------------------------------------------------------------------------- metrics
def metrics(g):
    ok = g[g["ok"]]
    lat = ok["latency_ms"].dropna()
    span = (g["ts"].max() - g["ts"].min()).total_seconds() if len(g) > 1 else 0.0
    verdicts = g["stale"].dropna()
    return pd.Series({
        "ops": len(g), "ok": len(ok), "failed": len(g) - len(ok),
        "error_pct": 100.0 * (len(g) - len(ok)) / len(g) if len(g) else float("nan"),
        "p50_ms": lat.quantile(0.50) if len(lat) else float("nan"),
        "p95_ms": lat.quantile(0.95) if len(lat) else float("nan"),
        "p99_ms": lat.quantile(0.99) if len(lat) else float("nan"),
        "mean_ms": lat.mean() if len(lat) else float("nan"),
        "ok_ops_per_s": len(ok) / span if span > 0 else float("nan"),
        "stale_reads": int(verdicts.sum()) if len(verdicts) else 0,
        "stale_pct": 100.0 * verdicts.mean() if len(verdicts) else float("nan"),
    })


def per_run(df):
    keys = ["dir_exp", "file", "experiment", "scenario", "file_variant", "cl_label", "rep", "run_id"]
    return df.groupby(keys, dropna=False).apply(metrics, include_groups=False).reset_index()


def pooled(df):
    keys = ["dir_exp", "experiment", "scenario", "file_variant", "op", "cl"]
    out = df.groupby(keys, dropna=False).apply(metrics, include_groups=False).reset_index()
    runs = df.groupby(keys, dropna=False)["run_id"].nunique().rename("runs").reset_index()
    return out.merge(runs, on=keys)


def errors_by_type(df):
    bad = df[~df["ok"]]
    if bad.empty:
        return pd.DataFrame(columns=["dir_exp", "scenario", "file_variant", "op", "cl", "outcome",
                                     "error_type", "count"])
    return (bad.groupby(["dir_exp", "scenario", "file_variant", "op", "cl", "outcome", "error_type"])
            .size().rename("count").reset_index().sort_values("count", ascending=False))


def availability_phases(probe):
    if probe.empty:
        return pd.DataFrame()
    g = probe.groupby(["experiment", "scenario", "cl", "phase"])
    out = g.agg(attempted=("ok", "size"), ok=("ok", "sum"), runs=("run_id", "nunique")).reset_index()
    out["success_pct"] = 100.0 * out["ok"] / out["attempted"]
    out["cl"] = pd.Categorical(out["cl"], CL_ORDER, ordered=True)
    out["phase"] = pd.Categorical(out["phase"], PHASE_ORDER + ["no-fault"], ordered=True)
    return out.sort_values(["experiment", "scenario", "phase", "cl"]).reset_index(drop=True)


def phases_by_rep(probe):
    """Per repetition: success and client-side timeouts per CL and phase (pooling can hide a
    probe that was stuck on an unreachable coordinator in one repetition)."""
    if probe.empty:
        return pd.DataFrame()
    g = probe.assign(client_timeout=probe["outcome"] == "client_timeout").groupby(
        ["experiment", "scenario", "rep", "phase", "cl"], observed=True)
    out = g.agg(attempted=("ok", "size"), ok=("ok", "sum"), client_timeouts=("client_timeout", "sum"),
                coordinators=("coordinator", lambda c: ";".join(sorted(set(c.dropna()))))).reset_index()
    out["success_pct"] = 100.0 * out["ok"] / out["attempted"]
    return out


def detection_summary(det, events=None):
    """Mean/min/max detection per fault type; partitions split into majority/minority view."""
    if det.empty:
        return pd.DataFrame()
    det = det.copy()
    partitioned = set(events.loc[events["action"] == "partition", "node"]) if events is not None else set()
    det["fault"] = det["action"] + " (" + det["transition"] + ")"
    part = det["action"] == "partition"
    det.loc[part, "fault"] = det.loc[part, "node"].map(
        lambda n: "partition, majority view" if n in partitioned else "partition, minority view")
    out = det.groupby("fault")["detection_seconds"].agg(["count", "mean", "min", "max", "std"]).reset_index()
    return out.rename(columns={"count": "n", "mean": "mean_s", "min": "min_s", "max": "max_s", "std": "sd_s"})


# --------------------------------------------------------------------------- Exp 4 / Exp 6 numbers
NOTE_RE = re.compile(r"served_by_target (\d+); stale_on_target (\d+); repair_traces (\d+)")


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f


def _kib(b):
    b = _num(b)
    return None if b is None else f"{b / 1024:.1f}"


def exp4_numbers(raw):
    path = os.path.join(EXP4_LOGS, "convergence_checks.csv")
    if not os.path.exists(path):
        return {}
    checks = pd.read_csv(path, dtype=str).fillna("")
    complete = checks[checks["step"] == "4c-final"]["run_id"]
    run_id = complete.iloc[-1] if len(complete) else (checks["run_id"].iloc[-1] if len(checks) else "")
    c = checks[checks["run_id"] == run_id]
    n = {"run": tex_escape(run_id)}

    def check(step, kind):
        rows = c[(c["step"] == step) & (c["check"].str.startswith(kind))]
        return rows.iloc[-1] if len(rows) else None

    for step, key in (("00-baseline", "base"), ("4a-after-hints", "4a"), ("4b-after-restart", "4b"),
                      ("4b-after-readrepair", "4b2"), ("4c-after-repair", "4c")):
        r = check(step, "preview")
        if r is not None:
            n[f"{key}-preview"] = "in sync" if r["in_sync"] == "1" else f"{r['ranges']} ranges"
            n[f"{key}-preview-ranges"] = r["ranges"]
            n[f"{key}-preview-kib"] = _kib(r["bytes"]) or "--"
    for step, key in (("4a-one-after-hints", "4a-one"), ("4b-one-before", "4b-before"),
                      ("4b-all-readrepair", "4b-all"), ("4b-one-after-readrepair", "4b-after"),
                      ("4b-one-control", "4b-control"), ("4c-one-control", "4c-control")):
        r = check(step, "read-sample")
        if r is not None:
            n[f"{key}-checked"], n[f"{key}-stale"] = r["checked"], r["stale"]
            m = NOTE_RE.search(r["note"])
            if m:
                n[f"{key}-target"], n[f"{key}-target-stale"], n[f"{key}-repair-traces"] = m.groups()
    for step, key in (("4a-final", "4a"), ("4c-final", "4c")):
        r = check(step, "acked")
        if r is not None:
            n[f"{key}-acked-checked"] = r["checked"]
            n[f"{key}-acked-missing"], n[f"{key}-acked-wrong"] = r["missing"], r["wrong"]
        r = check(step, "convergence")
        if r is not None:
            n[f"{key}-verdict"] = r["verdict"]
    meas = os.path.join(EXP4_LOGS, run_id, "measurements.csv")
    if run_id and os.path.exists(meas):
        m = pd.read_csv(meas, dtype=str).fillna("")
        names = {"hint_files_before_restart": "4a-hint-files", "hint_bytes_before_restart": "4a-hint-kib",
                 "seconds_start_to_un": "4a-un-s", "seconds_un_to_hints_drained": "4a-drain-s",
                 "seconds_start_to_hints_drained": "4a-start-drain-s", "repair_seconds": "4c-repair-s"}
        for r in m.itertuples():
            if r.metric in names and r.value != "":
                n[names[r.metric]] = _kib(r.value) if r.metric.startswith("hint_bytes") else r.value
    if not raw.empty and run_id:
        w = raw[(raw["dir_exp"] == "exp4") & (raw["run_id"] == run_id) & raw["file_variant"].str.endswith("-write")]
        for v, g in w.groupby("file_variant"):
            key = v.replace("-write", "")
            n[f"{key}-written"], n[f"{key}-acked"] = f"{len(g):,}", f"{int(g['ok'].sum()):,}"
            lat = g.loc[g["ok"], "latency_ms"]
            n[f"{key}-write-p50"] = fmt(lat.quantile(0.5))
    n.update(exp4_sentences(n))
    return n


def _i(n, k):
    try:
        return int(float(n[k]))
    except (KeyError, TypeError, ValueError):
        return None


def exp4_sentences(n):
    """Conclusions that follow from the numbers; a deviation is said, never hidden."""
    s = {}
    if "4a-preview" in n and "4a-one-stale" in n:
        s["4a-conclusion"] = ("Hints alone therefore restored the replica." if n["4a-preview"] == "in sync"
                              and _i(n, "4a-one-stale") == 0 else
                              "NOTE: this deviates from the expected result (in sync, no stale read); "
                              "see the 4a evidence files.")
    if all(k in n for k in ("4b-after-stale", "4b-control-stale")):
        s["4b-conclusion"] = ("Read repair therefore fixed exactly the rows that were read, and nothing else."
                              if _i(n, "4b-after-stale") == 0 and (_i(n, "4b-control-stale") or 0) > 0 else
                              "NOTE: this deviates from the expected result (read keys repaired, control "
                              "keys still stale); see the 4b evidence files.")
    if "4c-verdict" in n:
        s["4c-conclusion"] = ("No acknowledged write was lost, and the replicas converged."
                              if n["4c-verdict"] == "PASS" else
                              "NOTE: the convergence check FAILED; see 4c\\_99\\_verdict.txt.")
    return s


def exp6_sentences(n):
    s = {}
    if "race-violations" in n:
        s["race-conclusion"] = ("Paxos therefore enforced a single owner per handle."
                                if _i(n, "race-violations") == 0 else
                                "NOTE: at least one handle had two winners - a safety violation to investigate.")
    if "race2-violations" in n:
        s["race2-conclusion"] = ("Without a majority Cassandra gave up availability for these operations "
                                 "instead of risking two owners." if _i(n, "race2-violations") == 0 and
                                 _i(n, "race2-nowinner") == _i(n, "race2-handles") else
                                 "NOTE: this deviates from the expected result (no LWT can complete "
                                 "without a majority).")
    if "lat-ratio" in n:
        s["lat-conclusion"] = ("consistent with the extra Paxos round trips" if float(n["lat-ratio"]) > 1.0
                               else "NOTE: LWTs were not slower than plain writes in this run")
    return s


def exp6_numbers(raw):
    n = {}
    races = os.path.join(EXP6_LOGS, "races.csv")
    if os.path.exists(races):
        r = pd.read_csv(races, dtype=str).fillna("")
        for variant, key in (("race", "race"), ("plain", "plain"), ("race-1down", "race1"), ("race-2down", "race2")):
            rows = r[r["variant"] == variant]
            if rows.empty:
                continue
            last = rows.iloc[-1]
            for col in ("handles", "clients", "ops_ok", "ops_failed", "exactly_one", "timeout_winner",
                        "no_winner", "violations", "acked_overwritten"):
                n[f"{key}-{col.replace('_', '')}"] = last[col]
            n[f"{key}-verdict"] = tex_escape(last["verdict"])
            if not raw.empty:
                g = raw[(raw["dir_exp"] == "exp6") & (raw["run_id"] == last["run_id"]) & ~raw["ok"]]
                if len(g):
                    top = g.groupby("error_type").size().sort_values(ascending=False)
                    n[f"{key}-errors"] = tex_escape(", ".join(f"{k or 'unknown'} {v}" for k, v in top.items()))
    if not raw.empty:
        lat = raw[(raw["dir_exp"] == "exp6") & (raw["file_variant"] == "latency")]
        if not lat.empty:
            lat = lat[lat["run_id"] == lat.sort_values("stamp")["run_id"].iloc[-1]]
            for op, key in (("lwt", "lwt"), ("write", "plain")):
                v = lat[(lat["op"] == op) & lat["ok"]]["latency_ms"]
                if len(v):
                    n[f"lat-{key}-n"] = str(len(v))
                    for q in (50, 95, 99):
                        n[f"lat-{key}-p{q}"] = fmt(v.quantile(q / 100))
                    n[f"lat-{key}-mean"] = fmt(v.mean())
            a = lat[(lat["op"] == "lwt") & lat["ok"]]["latency_ms"]
            b = lat[(lat["op"] == "write") & lat["ok"]]["latency_ms"]
            if len(a) and len(b):
                n["lat-ratio"] = f"{a.median() / b.median():.1f}"
    traces = sorted(glob.glob(os.path.join(EXP6_LOGS, "*", "*paxos_trace.txt")), key=os.path.getmtime)
    if traces:
        with open(traces[-1], encoding="utf-8") as fh:
            m = re.search(r"paxos_variant = (\S+)", fh.read())
        if m:
            n["paxos-variant"] = tex_escape(m.group(1))
    n.update(exp6_sentences(n))
    return n


# --------------------------------------------------------------------------- writers
def md_table(df, cols, headers, nd=2):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in df[cols].itertuples(index=False):
        lines.append("| " + " | ".join(fmt(v, nd) for v in r) + " |")
    return "\n".join(lines)


def fault_numbers(phases, by_rep, det):
    """\\expfault{<scenario>-<phase>-<CL>} success %, client-timeout facts, detection means."""
    n = {}
    for r in phases.itertuples():
        n[f"{r.scenario}-{r.phase}-{r.cl}"] = f"{r.success_pct:.1f}"
        n[f"{r.scenario}-{r.phase}-{r.cl}-n"] = f"{r.attempted:,}"
    if not by_rep.empty:
        stuck = by_rep[(by_rep["phase"] == "fault") & (by_rep["client_timeouts"] > 0)
                       & (by_rep["experiment"] == "exp5")]
        n["exp5-stuck-runs"] = str(stuck["rep"].nunique())
        n["exp5-stuck-timeouts"] = str(int(stuck["client_timeouts"].sum()))
        n["exp5-stuck-levels"] = "; ".join(f"rep {rep}: {', '.join(map(str, g['cl']))}"
                                          for rep, g in stuck.groupby("rep"))
    if not det.empty:
        key = {"kill (down)": "kill", "stop (down)": "stop", "start (up)": "up",
               "partition, majority view": "part-majority", "partition, minority view": "part-minority"}
        for r in det.itertuples():
            if r.fault in key:
                n[f"det-{key[r.fault]}"] = f"{r.mean_s:.1f}"
                n[f"det-{key[r.fault]}-n"] = str(r.n)
    return n


def write_numbers(path, four, six, faults=None):
    lines = ["% Generated by analysis/summarize.py - do not edit by hand.",
             "% \\expfour{<name>} and \\expsix{<name>}; names are listed below."]
    for prefix, values in (("expfour", four), ("expsix", six), ("expfault", faults or {})):
        for k, v in sorted(values.items()):
            if v is None or v == "":
                continue
            lines.append(f"\\expandafter\\def\\csname {prefix}@{k}\\endcsname{{{v}}}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def write_fault_tables(path, phases, det):
    lines = ["% Generated by analysis/summarize.py - do not edit by hand."]
    if not phases.empty:
        lines += ["\\begin{table}[t]\\centering\\footnotesize\\setlength{\\tabcolsep}{3pt}",
                  "\\caption{Availability-probe success rate per consistency level and fault phase "
                  "(Exp 3 and 5; repetitions pooled; ``fault'' = from the injection command to the "
                  "restart/heal command).}\\label{tab:fault-phases}",
                  "\\begin{tabular}{llrrr}\\hline", "Run & Phase & ONE (\\%) & QUORUM (\\%) & ALL (\\%) \\\\ \\hline"]
        wide = phases.pivot_table(index=["experiment", "scenario", "phase"], columns="cl",
                                  values="success_pct", observed=True)
        for (exp, scen, phase), r in wide.iterrows():
            vals = " & ".join(fmt(r.get(cl), 1) for cl in CL_ORDER)
            lines.append(f"{exp} {tex_escape(scen)} & {phase} & {vals} \\\\")
        lines += ["\\hline\\end{tabular}\\end{table}", ""]
    if not det.empty:
        lines += ["\\begin{table}[t]\\centering\\footnotesize\\setlength{\\tabcolsep}{3pt}",
                  "\\caption{Gossip failure-detection time (fault command to ``is now DOWN/UP'' in a "
                  "peer's log).}\\label{tab:detection}",
                  "\\begin{tabular}{lrrrr}\\hline", "Fault (transition) & $n$ & mean (s) & min (s) & max (s) \\\\ \\hline"]
        for r in det.itertuples():
            lines.append(f"{tex_escape(r.fault)} & {r.n} & {fmt(r.mean_s)} & {fmt(r.min_s)} & {fmt(r.max_s)} \\\\")
        lines += ["\\hline\\end{tabular}\\end{table}", ""]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m analysis.summarize", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raw", default=os.path.join("results", "raw"))
    p.add_argument("--out", default=SUMMARY_DIR)
    p.add_argument("--gen", default=GEN_DIR)
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)

    raw = load_raw(a.raw, verbose=not a.quiet)
    if raw.empty:
        print(f"ERROR: no raw CSV in {a.raw}/<exp>/ - run the experiments first; nothing written",
              file=sys.stderr)
        return 2
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.gen, exist_ok=True)

    runs = per_run(raw)
    groups = pooled(raw)
    errors = errors_by_type(raw)
    events = load_events()
    probe, _ = fault_runs(raw, events)
    phases = availability_phases(probe)
    by_rep = phases_by_rep(probe)
    det = detection_summary(load_detection(), events)
    four, six = exp4_numbers(raw), exp6_numbers(raw)

    runs.to_csv(os.path.join(a.out, "runs.csv"), index=False, float_format="%.3f")
    groups.to_csv(os.path.join(a.out, "groups.csv"), index=False, float_format="%.3f")
    errors.to_csv(os.path.join(a.out, "errors_by_type.csv"), index=False)
    phases.to_csv(os.path.join(a.out, "availability_phases.csv"), index=False, float_format="%.2f")
    by_rep.to_csv(os.path.join(a.out, "availability_phases_by_rep.csv"), index=False, float_format="%.2f")
    det.to_csv(os.path.join(a.out, "detection_times.csv"), index=False, float_format="%.3f")
    write_numbers(os.path.join(a.gen, "exp46_numbers.tex"), four, six, fault_numbers(phases, by_rep, det))
    write_fault_tables(os.path.join(a.gen, "fault_tables.tex"), phases, det)

    md = ["# Results summary (generated by analysis/summarize.py)", "",
          f"{len(raw):,} operations in {raw['file'].nunique()} raw CSV files "
          f"({', '.join(sorted(raw['dir_exp'].unique()))}).", "",
          "## All experiments: latency, throughput and errors (repetitions pooled)", "",
          md_table(groups, ["dir_exp", "scenario", "op", "cl", "runs", "ops", "error_pct", "p50_ms", "p95_ms",
                            "p99_ms", "mean_ms", "stale_pct"],
                   ["exp", "variant", "op", "CL", "runs", "ops", "err %", "p50 ms", "p95 ms", "p99 ms",
                    "mean ms", "stale %"]), ""]
    if not phases.empty:
        md += ["## Exp 3 / Exp 5: availability-probe success by fault phase", "",
               "Phases come from results/logs/chaos_events.csv: *fault* runs from the injection command "
               "to the restart/heal command; *between* separates two faults of one run (3c); *after* "
               "starts at the last restart/heal command, so it includes the time the node needs to "
               "rejoin. Newest run per variant and repetition.", "",
               md_table(phases, ["experiment", "scenario", "phase", "cl", "runs", "attempted", "ok",
                                 "success_pct"],
                        ["exp", "variant", "phase", "CL", "runs", "attempted", "ok", "success %"]), ""]
    if not by_rep.empty:
        stuck = by_rep[(by_rep["phase"] == "fault") & (by_rep["client_timeouts"] > 0)]
        if not stuck.empty:
            md += ["### Fault window per repetition: client-side timeouts", "",
                   "Rows where the probe saw driver timeouts (5 s, no server answer). The probe runs one "
                   "operation at a time per CL, so a level whose requests keep going to an unreachable "
                   "coordinator starts only one operation every 5 s; pooled success rates hide this.", "",
                   md_table(stuck, ["experiment", "scenario", "rep", "cl", "attempted", "ok", "client_timeouts",
                                    "success_pct"],
                            ["exp", "variant", "rep", "CL", "attempted", "ok", "client timeouts", "success %"]), ""]
    if not det.empty:
        md += ["## Gossip failure detection", "",
               md_table(det, ["fault", "n", "mean_s", "min_s", "max_s", "sd_s"],
                        ["fault (transition)", "n", "mean s", "min s", "max s", "sd s"]), ""]
    if not errors.empty:
        md += ["## Failed operations by type (top 25)", "",
               md_table(errors.head(25), ["dir_exp", "scenario", "op", "cl", "outcome", "error_type", "count"],
                        ["exp", "variant", "op", "CL", "outcome", "driver error", "count"]), ""]
    for title, vals in (("Experiment 4 (recovery)", four), ("Experiment 6 (Paxos LWT)", six)):
        md += [f"## {title}", ""]
        md += ([f"- `{k}`: {v}" for k, v in sorted(vals.items())] if vals else
               ["Not run yet - no evidence under results/logs/ (see experiments/ runbook)."]) + [""]
    with open(os.path.join(a.out, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    print(f"summarized {len(raw):,} operations from {raw['file'].nunique()} files")
    print(f"wrote {a.out}/runs.csv, groups.csv, errors_by_type.csv, availability_phases.csv, "
          f"detection_times.csv, summary.md")
    print(f"wrote {a.gen}/exp46_numbers.tex ({len(four)} Exp 4 values, {len(six)} Exp 6 values), fault_tables.tex")
    if not four:
        print("NOTE: no Exp 4 evidence yet - run make exp4; section 7.4 shows markers for those values")
    if not six:
        print("NOTE: no Exp 6 evidence yet - run make exp6; section 7.4 shows markers for those values")
    return 0


if __name__ == "__main__":
    sys.exit(main())
