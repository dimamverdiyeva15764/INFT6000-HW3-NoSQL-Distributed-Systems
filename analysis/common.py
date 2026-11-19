"""Shared loading and fault-phase logic for analysis.summarize and analysis.plots."""
import glob
import os
import re

import pandas as pd

RAW_ROOT = os.path.join("results", "raw")
EVENT_FILE = os.path.join("results", "logs", "chaos_events.csv")
NAME_RE = re.compile(r"^(?P<exp>[^_]+)_(?P<variant>[^_]+)_(?P<cl>[^_]+)_r(?P<rep>\d+)_(?P<stamp>[^_.]+)(?:-\d+)?\.csv$")
RUN_RE = re.compile(r"^(?P<exp>exp\d+)-(?P<scenario>[a-z0-9]+)-")
FAULT_ACTIONS = {"kill", "stop", "partition", "pause"}
RECOVER_ACTIONS = {"start", "heal", "unpause"}
CL_ORDER = ["ONE", "QUORUM", "ALL"]
PHASE_ORDER = ["before", "fault", "between", "after"]


def load_raw(root=RAW_ROOT, verbose=True):
    """Every conforming raw CSV as one DataFrame (one row per operation).

    Adds: file, dir_exp, file_variant, cl_label, rep, stamp, ok (bool), ts (UTC datetime),
    experiment / scenario (from run_id when it names a fault run, e.g. exp5-partition-...).
    """
    frames = []
    for path in sorted(glob.glob(os.path.join(root, "*", "*.csv"))):
        name = os.path.basename(path)
        m = NAME_RE.match(name)
        if not m:
            if verbose:
                print(f"skip {path}: not <exp>_<variant>_<cl>_r<rep>_<stamp>.csv")
            continue
        df = pd.read_csv(path, dtype={"key": str, "error_type": str, "coordinator": str,
                                      "run_id": str, "variant": str, "exp": str, "cl": str, "op": str,
                                      "outcome": str})
        if df.empty:
            if verbose:
                print(f"skip {path}: no rows")
            continue
        df["file"] = name
        df["dir_exp"] = os.path.basename(os.path.dirname(path))
        df["file_variant"] = m.group("variant")
        df["cl_label"] = m.group("cl")
        df["rep"] = int(m.group("rep"))
        df["stamp"] = m.group("stamp")
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["error_type"] = df["error_type"].fillna("")
    df["ok"] = df["outcome"] == "ok"
    df["ts"] = pd.to_datetime(df["ts_utc"], utc=True, format="ISO8601")
    df["latency_ms"] = pd.to_numeric(df["latency_ms"], errors="coerce")
    df["stale"] = pd.to_numeric(df["stale"], errors="coerce")
    run = df["run_id"].fillna("").str.extract(RUN_RE)
    df["experiment"] = run["exp"].fillna(df["exp"].astype(str))
    df["scenario"] = run["scenario"].fillna(df["file_variant"])
    return df


def load_events(path=EVENT_FILE):
    if not os.path.exists(path):
        return pd.DataFrame(columns=["ts", "action", "node", "note"])
    ev = pd.read_csv(path, dtype=str)
    ev["ts"] = pd.to_datetime(ev["ts_utc"], utc=True, format="ISO8601")
    return ev.sort_values("ts").reset_index(drop=True)


def fault_intervals(events, t0, t1, slack_s=2.0):
    """[(start, end, node, action)] for faults injected while a run was active.

    A fault starts with kill/stop/partition/pause and ends with the next
    start/heal/unpause of the same node (the *command*, not the moment the node is
    Up/Normal again); an unmatched fault lasts until t1.
    """
    lo, hi = t0 - pd.Timedelta(seconds=slack_s), t1 + pd.Timedelta(seconds=slack_s)
    win = events[(events["ts"] >= lo) & (events["ts"] <= hi)]
    open_, out = {}, []
    for r in win.itertuples():
        if r.action in FAULT_ACTIONS and r.node not in open_:
            open_[r.node] = (r.ts, r.action)
        elif r.action in RECOVER_ACTIONS and r.node in open_:
            start, action = open_.pop(r.node)
            out.append((start, r.ts, r.node, action))
    for node, (start, action) in open_.items():
        out.append((start, t1, node, action))
    return sorted(out)


def assign_phase(ts, intervals):
    """Series of before / fault / between / after for timestamps of one run."""
    if not intervals:
        return pd.Series("no-fault", index=ts.index)
    first = min(i[0] for i in intervals)
    last = max(i[1] for i in intervals)
    phase = pd.Series("between", index=ts.index)
    phase[ts < first] = "before"
    phase[ts >= last] = "after"
    for start, end, _node, _action in intervals:
        phase[(ts >= start) & (ts < end)] = "fault"
    return phase


def latest_runs(df, keys=("experiment", "scenario", "rep")):
    """Keep, per key, only the run_id with the newest stamp (re-runs replace dry runs)."""
    if df.empty:
        return df
    stamps = df.groupby(list(keys) + ["run_id"], as_index=False)["stamp"].max()
    keep = stamps.sort_values("stamp").groupby(list(keys)).tail(1)["run_id"]
    return df[df["run_id"].isin(set(keep))]


def fault_runs(df, events):
    """Availability-probe runs of fault experiments, with 'phase' and 't_s' columns.

    Returns (frame, intervals) where intervals[run_id] = [(start_s, end_s, node, action)]
    relative to the run's first operation. Only the newest run per (experiment, scenario,
    rep) is kept; smoke runs whose run_id does not start with expN are ignored.
    """
    probe = df[(df["file_variant"] == "availability") & df["run_id"].fillna("").str.match(r"exp\d")]
    probe = latest_runs(probe)
    parts, intervals = [], {}
    for run_id, g in probe.groupby("run_id"):
        g = g.copy()
        t0, t1 = g["ts"].min(), g["ts"].max()
        iv = fault_intervals(events, t0, t1)
        g["phase"] = assign_phase(g["ts"], iv)
        g["t_s"] = (g["ts"] - t0).dt.total_seconds()
        intervals[run_id] = [((s - t0).total_seconds(), (e - t0).total_seconds(), n, a) for s, e, n, a in iv]
        parts.append(g)
    return (pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()), intervals


def load_detection(root=os.path.join("results", "logs")):
    """Gossip detection measurements of Exp 3 and Exp 5 (Person 3's detect_down.py output)."""
    paths = sorted(set(glob.glob(os.path.join(root, "exp*", "*", "detection_times.csv"))
                       + glob.glob(os.path.join(root, "exp*", "failure_detection.csv"))))
    frames = [pd.read_csv(p, dtype=str) for p in paths if os.path.getsize(p) > 0]
    if not frames:
        return pd.DataFrame()
    d = pd.concat(frames, ignore_index=True)
    d = d.drop_duplicates(subset=["node", "action", "transition", "observer", "injected_utc"])
    d["detection_seconds"] = pd.to_numeric(d["detection_seconds"], errors="coerce")
    return d.dropna(subset=["detection_seconds"])


def pct(values, q):
    v = pd.Series(values).dropna()
    return float(v.quantile(q / 100.0)) if len(v) else float("nan")
