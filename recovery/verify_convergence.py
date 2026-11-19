"""Convergence verification for Experiment 4 (owner: Habib Hasanov).

Proves three things about recovery after a fault, each with its own subcommand:

  write        write N independent keys (one partition each) at a chosen CL and log every
               acknowledgement to the shared results CSV. These are the "acknowledged
               writes" that must never be lost.                     [client container]
  read-sample  read a deterministic sample of those keys at a chosen CL through ONE chosen
               coordinator with query tracing; record which replica actually served the
               data, whether the value was stale, and whether the trace shows a digest
               mismatch / read repair.                               [client container]
  acked        read EVERY acknowledged key at ALL; PASS only if each returns exactly the
               acknowledged value (no lost or wrong acknowledged write). [client container]
  preview      run `nodetool repair --full --preview <keyspace>` through docker exec and
               parse the Merkle-tree comparison: "in sync", or how many ranges/bytes would
               be streamed.                                          [host, needs docker]
  full         preview + acked in one call; prints CONVERGENCE PASS or FAIL.  [host]

Examples
  docker compose run --rm client python -m recovery.verify_convergence write --n 5000 --variant 4a
  docker compose run --rm client python -m recovery.verify_convergence read-sample \\
        --writes results/raw/exp4/exp4_4b-write_QUORUM_r1_<stamp>.csv \\
        --cl ONE --coordinator cass3 --sample 50 --set A --step 4b-one-before
  python -m recovery.verify_convergence preview --node cass1 --label healthy --expect in-sync
  python -m recovery.verify_convergence full --label 4c-final --writes results/raw/exp4/exp4_4*-write_*.csv

Every check appends one row to results/logs/exp4/convergence_checks.csv (append-only,
like chaos_events.csv). The host-side subcommands use the standard library only; the
CQL subcommands import app.db (cassandra-driver) lazily.
"""
import argparse
import csv
import glob
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

KEYSPACE = os.environ.get("KEYSPACE", "chat")
CHECK_LOG = os.path.join("results", "logs", "exp4", "convergence_checks.csv")
CHECK_FIELDS = ["ts_utc", "run_id", "step", "check", "verdict", "expected", "in_sync", "ranges",
                "bytes", "checked", "stale", "missing", "wrong", "failed", "note"]

WRITE_CQL = "UPDATE room_state SET last_seq = ?, updated_by = ? WHERE room = ?"
READ_CQL = "SELECT last_seq FROM room_state WHERE room = ?"

# Trace descriptions (Cassandra 4.0-5.0). A replica that executes the read logs
# "Executing single-partition query on <table>" and "Read N live rows ..."; digest
# mismatches and read repair are traced on the coordinator.
SERVED_RE = re.compile(r"Executing single-partition query|Read \d+ live rows", re.IGNORECASE)
REPAIR_RE = re.compile(r"mismatch|repair", re.IGNORECASE)


# --------------------------------------------------------------------------- utilities
def utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")


def append_check(row, path=CHECK_LOG):
    """Append one verdict row to the convergence log (creates it with a header)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CHECK_FIELDS, extrasaction="ignore")
        if new:
            writer.writeheader()
        full = {k: "" for k in CHECK_FIELDS}
        full.update({k: ("" if v is None else v) for k, v in row.items()})
        full["ts_utc"] = full["ts_utc"] or utc_now_iso()
        writer.writerow(full)


_SIZE_UNITS = {"": 1, "B": 1, "BYTES": 1, "KB": 1000, "KIB": 1024, "MB": 1000 ** 2,
               "MIB": 1024 ** 2, "GB": 1000 ** 3, "GIB": 1024 ** 3, "TB": 1000 ** 4, "TIB": 1024 ** 4}


def parse_size(text):
    """'430B' -> 430, '1.240KiB' -> 1270, '12 MiB' -> 12582912, '977' -> 977; None if unparsable.

    nodetool prints sizes with FBUtilities.prettyPrintMemory (e.g. 1.240KiB); plain integers
    are accepted too, so the parser survives format differences between versions.
    """
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]*)\s*", text or "")
    if not m:
        return None
    unit = m.group(2).upper()
    if unit not in _SIZE_UNITS:
        return None
    return int(round(float(m.group(1)) * _SIZE_UNITS[unit]))


_TOTAL_RE = re.compile(r"Total estimated streaming:\s*(\d+)\s*ranges?,\s*(\d+)\s*sstables?,\s*"
                       r"([0-9.]+\s*[A-Za-z]*?)\s*(?:bytes)?\s*$", re.IGNORECASE | re.MULTILINE)
_PAIR_RE = re.compile(r"/?([0-9a-fA-F.:]+?)(?::\d+)?\s*->\s*/?([0-9a-fA-F.:]+?)(?::\d+)?:\s*(\d+)\s*ranges?,"
                      r"\s*(\d+)\s*sstables?,\s*([0-9.]+\s*[A-Za-z]*?)\s*(?:bytes)?\s*$", re.MULTILINE)


def parse_preview(text):
    """Parse `nodetool repair --preview` output.

    Returns dict(in_sync, ranges, sstables, bytes, pairs, error). in_sync is True for
    "Previewed data was in sync" / "Repaired data is in sync", False when a streaming
    estimate is printed, None when neither appears (then read the saved raw output).
    """
    out = {"in_sync": None, "ranges": None, "sstables": None, "bytes": None, "pairs": [], "error": None}
    if re.search(r"(Previewed|Repaired) data (was|is) in sync", text or ""):
        out.update(in_sync=True, ranges=0, sstables=0, bytes=0)
    m = _TOTAL_RE.search(text or "")
    if m:
        out.update(in_sync=False, ranges=int(m.group(1)), sstables=int(m.group(2)),
                   bytes=parse_size(m.group(3)))
        for p in _PAIR_RE.finditer(text):
            out["pairs"].append({"src": p.group(1), "dst": p.group(2), "ranges": int(p.group(3)),
                                 "sstables": int(p.group(4)), "bytes": parse_size(p.group(5))})
    if re.search(r"error|exception|failed", text or "", re.IGNORECASE) and out["in_sync"] is None:
        out["error"] = "nodetool reported an error"
    return out


def load_acked(paths):
    """Acknowledged writes from one or more `write` CSVs: list of (key, expected_seq)."""
    acked = []
    for path in paths:
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("op") == "write" and row.get("outcome") == "ok":
                    acked.append((row["key"], int(row["expected_seq"])))
    return acked


def choose_sample(acked, n, which="A", seed=4):
    """Deterministic disjoint samples: set A = first n of a seeded shuffle, set B = next n."""
    keys = sorted(acked)
    random.Random(seed).shuffle(keys)
    start = {"A": 0, "B": n}.get(which.upper())
    if start is None:
        raise ValueError("--set must be A or B")
    return keys[start:start + n]


def expand(patterns):
    paths = []
    for p in patterns or []:
        matches = sorted(glob.glob(p))
        if not matches and os.path.exists(p):
            matches = [p]
        if not matches:
            raise SystemExit(f"no file matches {p}")
        paths.extend(matches)
    return paths


# --------------------------------------------------------------------------- CQL side
def _db():
    from app import db  # noqa: PLC0415 - cassandra-driver only needed in the client container
    return db


def _pool_map(fn, items, concurrency):
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        return list(ex.map(fn, items))


def do_write(session, log, keys_values, cl, run_id, concurrency=32):
    """Write (key, seq) pairs; return number acknowledged. Every attempt is logged."""
    db = _db()
    ps = db.stmt(WRITE_CQL, cl, session=session)

    def one(kv):
        key, seq = kv
        res = db.timed_execute(session, ps, [seq, run_id, key])
        log.log(op="write", cl=cl, key=key, latency_ms=res.latency_ms, outcome=res.outcome,
                error_type=res.error_type, expected_seq=seq, coordinator=res.coordinator)
        return res.outcome == "ok"

    return sum(_pool_map(one, keys_values, concurrency))


def trace_summary(future, wait_s=5.0):
    """(replicas that executed the read, list of mismatch/repair event texts) from a trace."""
    served, repair = set(), []
    if future is None:
        return served, repair
    try:
        trace = future.get_query_trace(wait_s)  # positional: ResponseFuture uses max_wait
    except Exception:  # noqa: BLE001 - tracing is evidence, never fatal
        return served, repair
    for ev in getattr(trace, "events", None) or []:
        desc = str(getattr(ev, "description", ""))
        src = str(getattr(ev, "source", "")).split(":")[0].lstrip("/")
        if SERVED_RE.search(desc):
            served.add(src)
        if REPAIR_RE.search(desc):
            repair.append(f"{src}: {desc}")
    return served, repair


def do_read_sample(session, log, sample, cl, coordinator, trace=True):
    """Read each (key, expected) through one coordinator; returns per-key detail dicts."""
    db = _db()
    from app import config  # noqa: PLC0415
    ps = db.stmt(READ_CQL, cl, session=session)
    profile = db.coordinator_profile(coordinator) if coordinator else None
    target = config.resolve_node(coordinator) if coordinator else ""
    details = []
    for key, expected in sample:            # sequential: traces stay small and readable
        res = db.timed_execute(session, ps, [key], profile=profile, trace=trace)
        observed = stale = None
        if res.outcome == "ok":
            observed = res.rows[0].last_seq if res.rows else None
            stale = int(observed is None or observed < expected)
        served, repair = trace_summary(res.future) if trace and res.outcome == "ok" else (set(), [])
        log.log(op="read", cl=cl, key=key, latency_ms=res.latency_ms, outcome=res.outcome,
                error_type=res.error_type, expected_seq=expected, observed_seq=observed,
                stale=stale, coordinator=res.coordinator)
        details.append({
            "key": key, "expected_seq": expected, "observed_seq": "" if observed is None else observed,
            "stale": "" if stale is None else stale, "outcome": res.outcome,
            "coordinator": res.coordinator, "served_by": ";".join(sorted(served)),
            "served_by_target": int(bool(target) and target in served),
            "repair_events": len(repair), "repair_excerpt": " | ".join(repair[:3]),
        })
    return details


def summarize_sample(details):
    ok = [d for d in details if d["outcome"] == "ok"]
    on_target = [d for d in ok if d["served_by_target"]]
    errors = {}
    for d in details:
        if d["outcome"] != "ok":
            errors[d["outcome"]] = errors.get(d["outcome"], 0) + 1
    return {
        "errors": errors,
        "reads": len(details), "ok": len(ok), "failed": len(details) - len(ok),
        "stale": sum(int(d["stale"] or 0) for d in ok),
        "served_by_target": len(on_target),
        "stale_on_target": sum(int(d["stale"] or 0) for d in on_target),
        "with_repair_events": sum(1 for d in ok if d["repair_events"]),
    }


def do_acked(session, log, acked, concurrency=32):
    """Read every acknowledged key at ALL. Returns counts dict."""
    db = _db()
    ps = db.stmt(READ_CQL, "ALL", session=session)

    def one(kv):
        key, expected = kv
        res = db.timed_execute(session, ps, [key])
        observed = res.rows[0].last_seq if res.outcome == "ok" and res.rows else None
        if res.outcome != "ok":
            status = "failed"
        elif observed is None:
            status = "missing"
        elif observed != expected:
            status = "wrong"
        else:
            status = "ok"
        log.log(op="read", cl="ALL", key=key, latency_ms=res.latency_ms, outcome=res.outcome,
                error_type=res.error_type, expected_seq=expected, observed_seq=observed,
                stale="" if res.outcome != "ok" else int(status != "ok"), coordinator=res.coordinator)
        return status

    statuses = _pool_map(one, acked, concurrency)
    return {s: statuses.count(s) for s in ("ok", "missing", "wrong", "failed")}


def acked_verdict(counts, total):
    return "PASS" if total > 0 and counts.get("ok", 0) == total else "FAIL"


# --------------------------------------------------------------------------- host side
def run_preview(node, keyspace=KEYSPACE, timeout=600):
    """Run preview repair in a node container; returns raw combined output."""
    cmd = ["docker", "exec", node, "nodetool", "repair", "--full", "--preview", keyspace]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    return (proc.stdout or "") + (proc.stderr or ""), proc.returncode


def preview_line(label, res):
    if res["in_sync"] is True:
        return f"PREVIEW {label}: IN SYNC (Merkle trees match; nothing to stream)"
    if res["in_sync"] is False:
        return (f"PREVIEW {label}: DIVERGENT - {res['ranges']} range(s), {res['sstables']} sstable(s), "
                f"{res['bytes']} bytes would be streamed")
    return f"PREVIEW {label}: UNKNOWN (inspect the raw output)"


# --------------------------------------------------------------------------- commands
def cmd_write(a):
    db = _db()
    from app.results_log import ResultsLog, default_path  # noqa: PLC0415
    run_id = a.run_id or f"exp4-{a.variant}-r{a.rep}-{utc_stamp()}"
    out = a.out or default_path("exp4", f"{a.variant}-write", a.cl, a.rep)
    prefix = a.key_prefix or run_id
    pairs = [(f"{prefix}-k{i:05d}", i + 1) for i in range(a.n)]
    session = db.get_session()
    try:
        t0 = time.monotonic()
        with ResultsLog(out, "exp4", f"{a.variant}-write", run_id) as log:
            ok = do_write(session, log, pairs, a.cl, run_id, a.concurrency)
        dt = time.monotonic() - t0
    finally:
        db.shutdown(session)
    print(f"WRITE {a.variant}: {ok}/{a.n} acknowledged at {a.cl} in {dt:.1f}s")
    print(f"csv: {out}")
    return 0 if ok > 0 else 3


def cmd_read_sample(a):
    db = _db()
    from app.results_log import ResultsLog, default_path  # noqa: PLC0415
    acked = load_acked(expand(a.writes))
    if not acked:
        raise SystemExit("no acknowledged writes in --writes")
    sample = choose_sample(acked, a.sample, a.set, a.seed)
    if not sample:
        raise SystemExit(f"sample set {a.set} is empty: only {len(acked)} acknowledged keys")
    run_id = a.run_id or f"exp4-{a.step}-{utc_stamp()}"
    out = a.out or default_path("exp4", a.step, a.cl, a.rep)
    detail = a.detail or os.path.join("results", "logs", "exp4", run_id, f"{a.step}_reads.csv")
    session = db.get_session()
    try:
        with ResultsLog(out, "exp4", a.step, run_id) as log:
            details = do_read_sample(session, log, sample, a.cl, a.coordinator, trace=not a.no_trace)
    finally:
        db.shutdown(session)
    os.makedirs(os.path.dirname(detail), exist_ok=True)
    with open(detail, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(details[0].keys()))
        w.writeheader()
        w.writerows(details)
    s = summarize_sample(details)
    print(f"READ-SAMPLE {a.step}: set {a.set}, {s['reads']} keys at {a.cl} via {a.coordinator or 'any'}; "
          f"ok={s['ok']} failed={s['failed']} stale={s['stale']}; served by {a.coordinator}: "
          f"{s['served_by_target']} (stale {s['stale_on_target']}); traces with mismatch/repair: "
          f"{s['with_repair_events']}")
    expectation = ""
    if s["errors"]:
        print("read errors: " + ", ".join(f"{k}={v}" for k, v in sorted(s["errors"].items()))
              + " (see the outcome/error_type columns of the CSV)")
    if a.expect:
        if a.expect == "fresh":
            met = s["ok"] > 0 and s["failed"] == 0 and s["stale"] == 0
        else:
            met = s["stale"] > 0
        expectation = "met" if met else "NOT met"
        print(f"expectation '{a.expect}': {expectation}")
    for d in details:
        if d["repair_excerpt"]:
            print(f"trace excerpt ({d['key']}): {d['repair_excerpt']}")
            break
    append_check({"run_id": run_id, "step": a.step, "check": f"read-sample-{a.cl}",
                  "verdict": expectation or "measured", "expected": a.expect or "",
                  "checked": s["ok"], "stale": s["stale"], "failed": s["failed"],
                  "note": f"set {a.set}; coordinator {a.coordinator}; served_by_target "
                          f"{s['served_by_target']}; stale_on_target {s['stale_on_target']}; "
                          f"repair_traces {s['with_repair_events']}"
                          + ("; errors " + " ".join(f"{k}={v}" for k, v in sorted(s["errors"].items()))
                             if s["errors"] else "")})
    print(f"csv: {out}\ndetail: {detail}")
    return 0


def cmd_acked(a):
    db = _db()
    from app.results_log import ResultsLog, default_path  # noqa: PLC0415
    acked = load_acked(expand(a.writes))
    run_id = a.run_id or f"exp4-{a.step}-{utc_stamp()}"
    out = a.out or default_path("exp4", f"{a.step}-acked", "ALL", a.rep)
    session = db.get_session()
    try:
        with ResultsLog(out, "exp4", f"{a.step}-acked", run_id) as log:
            counts = do_acked(session, log, acked, a.concurrency)
    finally:
        db.shutdown(session)
    verdict = acked_verdict(counts, len(acked))
    print(f"ACKED-CHECK {a.step}: {verdict} - {counts['ok']}/{len(acked)} acknowledged writes read back "
          f"at ALL with the acknowledged value (missing={counts['missing']}, wrong={counts['wrong']}, "
          f"read failed={counts['failed']})")
    append_check({"run_id": run_id, "step": a.step, "check": "acked-ALL", "verdict": verdict,
                  "expected": "PASS", "checked": len(acked), "missing": counts["missing"],
                  "wrong": counts["wrong"], "failed": counts["failed"]})
    print(f"csv: {out}")
    return 0 if verdict == "PASS" else 1


def cmd_preview(a):
    if a.from_file:
        with open(a.from_file, encoding="utf-8") as fh:
            raw, rc = fh.read(), 0
    else:
        raw, rc = run_preview(a.node, a.keyspace)
    if a.save:
        os.makedirs(os.path.dirname(a.save) or ".", exist_ok=True)
        with open(a.save, "w", encoding="utf-8") as fh:
            fh.write(raw)
    res = parse_preview(raw)
    print(preview_line(a.label, res))
    seen = set()
    for p in res["pairs"]:
        key = (p["src"], p["dst"], p["ranges"], p["bytes"])
        if key not in seen:
            seen.add(key)
            print(f"    {p['src']} -> {p['dst']}: {p['ranges']} range(s), {p['bytes']} bytes")
    verdict = "measured"
    if a.expect:
        want = a.expect == "in-sync"
        verdict = "met" if res["in_sync"] is want else "NOT met"
        print(f"expectation '{a.expect}': {verdict}")
    if not a.no_log:
        append_check({"run_id": a.run_id or "", "step": a.label, "check": "preview-repair",
                      "verdict": verdict, "expected": a.expect or "",
                      "in_sync": "" if res["in_sync"] is None else int(res["in_sync"]),
                      "ranges": res["ranges"], "bytes": res["bytes"],
                      "note": f"node {a.node}; exit {rc}" + (f"; {res['error']}" if res["error"] else "")})
    if res["in_sync"] is None:
        return 2
    return 1 if verdict == "NOT met" else 0


def cmd_full(a):
    raw, rc = run_preview(a.node, a.keyspace)
    if a.save_dir:
        os.makedirs(a.save_dir, exist_ok=True)
        with open(os.path.join(a.save_dir, f"{a.label}_preview.txt"), "w", encoding="utf-8") as fh:
            fh.write(raw)
    res = parse_preview(raw)
    print(preview_line(a.label, res))
    append_check({"run_id": a.run_id or "", "step": a.label, "check": "preview-repair",
                  "verdict": "met" if res["in_sync"] else "NOT met", "expected": "in-sync",
                  "in_sync": "" if res["in_sync"] is None else int(res["in_sync"]),
                  "ranges": res["ranges"], "bytes": res["bytes"], "note": f"node {a.node}; exit {rc}"})
    acked_ok = True
    if a.writes:
        cmd = ["docker", "compose", "run", "--rm", "-T", "client", "python", "-m",
               "recovery.verify_convergence", "acked", "--step", a.label, "--rep", str(a.rep),
               "--writes", *expand(a.writes)]
        if a.run_id:
            cmd += ["--run-id", a.run_id]
        acked_ok = subprocess.run(cmd, check=False).returncode == 0
    passed = res["in_sync"] is True and acked_ok
    verdict = "PASS" if passed else "FAIL"
    print(f"CONVERGENCE {a.label}: {verdict} (preview in sync: {res['in_sync']}, "
          f"acknowledged writes intact: {acked_ok if a.writes else 'not checked'})")
    append_check({"run_id": a.run_id or "", "step": a.label, "check": "convergence",
                  "verdict": verdict, "expected": "PASS"})
    return 0 if passed else 1


# --------------------------------------------------------------------------- CLI
def _cl(value):
    v = value.upper()
    if v not in {"ONE", "TWO", "THREE", "QUORUM", "ALL", "LOCAL_ONE", "LOCAL_QUORUM", "ANY"}:
        raise argparse.ArgumentTypeError(f"unsupported consistency level {value}")
    return v


def _label(value):
    if "_" in value:
        raise argparse.ArgumentTypeError("labels must not contain '_' (it separates file-name fields)")
    return value


def build_parser():
    p = argparse.ArgumentParser(prog="python -m recovery.verify_convergence", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("write", help="write N keys and log acknowledgements (client container)")
    w.add_argument("--n", type=int, default=5000)
    w.add_argument("--cl", type=_cl, default="QUORUM")
    w.add_argument("--variant", type=_label, default="4a")
    w.add_argument("--rep", type=int, default=1)
    w.add_argument("--concurrency", type=int, default=32)
    w.add_argument("--key-prefix", help="key prefix (default: the run id)")
    w.add_argument("--run-id")
    w.add_argument("--out")
    w.set_defaults(func=cmd_write)

    r = sub.add_parser("read-sample", help="traced sample reads through one coordinator (client container)")
    r.add_argument("--writes", nargs="+", required=True, help="CSV(s) written by 'write' (globs allowed)")
    r.add_argument("--cl", type=_cl, default="ONE")
    r.add_argument("--coordinator", default="cass3", help="node name or address used as coordinator")
    r.add_argument("--sample", type=int, default=50)
    r.add_argument("--set", default="A", choices=["A", "B", "a", "b"], help="A or the disjoint control set B")
    r.add_argument("--seed", type=int, default=4)
    r.add_argument("--step", type=_label, required=True, help="label, e.g. 4b-one-before")
    r.add_argument("--expect", choices=["fresh", "stale"])
    r.add_argument("--no-trace", action="store_true")
    r.add_argument("--rep", type=int, default=1)
    r.add_argument("--run-id")
    r.add_argument("--out")
    r.add_argument("--detail", help="per-key detail CSV (default results/logs/exp4/<run_id>/<step>_reads.csv)")
    r.set_defaults(func=cmd_read_sample)

    k = sub.add_parser("acked", help="read every acknowledged key at ALL (client container)")
    k.add_argument("--writes", nargs="+", required=True)
    k.add_argument("--step", type=_label, default="final")
    k.add_argument("--concurrency", type=int, default=32)
    k.add_argument("--rep", type=int, default=1)
    k.add_argument("--run-id")
    k.add_argument("--out")
    k.set_defaults(func=cmd_acked)

    v = sub.add_parser("preview", help="Merkle-tree preview repair via docker exec (host)")
    v.add_argument("--node", default="cass1")
    v.add_argument("--keyspace", default=KEYSPACE)
    v.add_argument("--label", type=_label, default="check")
    v.add_argument("--expect", choices=["in-sync", "divergent"])
    v.add_argument("--save", help="write the raw nodetool output to this file")
    v.add_argument("--from-file", help="parse a saved output instead of running nodetool")
    v.add_argument("--no-log", action="store_true", help="do not append to the convergence log")
    v.add_argument("--run-id")
    v.set_defaults(func=cmd_preview)

    f = sub.add_parser("full", help="preview + acked check, prints CONVERGENCE PASS/FAIL (host)")
    f.add_argument("--node", default="cass1")
    f.add_argument("--keyspace", default=KEYSPACE)
    f.add_argument("--label", type=_label, default="final")
    f.add_argument("--writes", nargs="*", help="write CSVs to verify at ALL (omit on a fresh cluster)")
    f.add_argument("--save-dir")
    f.add_argument("--rep", type=int, default=1)
    f.add_argument("--run-id")
    f.set_defaults(func=cmd_full)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
