"""Experiment 6 - consensus through Paxos lightweight transactions (owner: Habib Hasanov).

Cassandra has no leader for ordinary reads and writes; the only consensus protocol on
the data path is the per-partition Paxos round behind INSERT ... IF NOT EXISTS and
UPDATE ... IF. This module makes that visible:

  race     --clients C threads claim the SAME handle at the same instant (a barrier
           releases them together), for --handles H different handles.
           LWT mode:   INSERT INTO usernames ... IF NOT EXISTS  (serial CL SERIAL, commit
                       CL QUORUM). Safety property: at most one [applied]=True per handle,
                       and every loser is told the winner's owner.
           --plain:    the same race with a plain INSERT. Every client is told "success";
                       last-write-wins keeps one owner and silently discards the others.
  latency  --n N interleaved LWT and plain QUORUM inserts of fresh handles (sequential,
           one in flight), to compare the cost of the extra Paxos round trips.
  trace    one traced LWT that wins and one that loses, printing the coordinator's Paxos
           phases, and the node's paxos_variant setting.

Examples (inside the client container; make exp6 runs the full sequence)
  python -m recovery.lwt_demo race --clients 10 --handles 20
  python -m recovery.lwt_demo race --clients 10 --handles 20 --plain
  python -m recovery.lwt_demo latency --n 200
  python -m recovery.lwt_demo trace

Outputs follow docs/CONTRACTS.md: per-operation CSV in results/raw/exp6/, per-handle detail
and race summaries in results/logs/exp6/. Exit status: 0 = completed and no safety
violation (failures because nodes are down are observations, not errors), 1 = a handle
had more than one LWT winner, 2 = could not connect / bad arguments.
"""
import argparse
import csv
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

LWT_INSERT = "INSERT INTO usernames (handle, owner) VALUES (?, ?) IF NOT EXISTS"
PLAIN_INSERT = "INSERT INTO usernames (handle, owner) VALUES (?, ?)"
SELECT_OWNER = "SELECT owner FROM usernames WHERE handle = ?"
PAXOS_RE = re.compile(r"paxos|ballot|propos|promis|prepar|commit|accept|CAS|precondition", re.IGNORECASE)
LOG_DIR = os.path.join("results", "logs", "exp6")
RACE_LOG = os.path.join(LOG_DIR, "races.csv")
RACE_FIELDS = ["ts_utc", "run_id", "variant", "mode", "handles", "clients", "ops_ok", "ops_failed",
               "exactly_one", "timeout_winner", "no_winner", "violations", "acked_overwritten",
               "final_read_failed", "verdict"]


def utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")


def percentile(values, q):
    if not values:
        return None
    data = sorted(values)
    pos = (len(data) - 1) * q / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def row_applied(row):
    """[applied] column of an LWT result row (the driver exposes it as 'applied')."""
    if row is None:
        return None
    if hasattr(row, "applied"):
        return bool(row.applied)
    if isinstance(row, dict):
        for k, v in row.items():
            if "applied" in k:
                return bool(v)
    try:
        return bool(row[0])
    except (TypeError, IndexError):
        return None


# --------------------------------------------------------------------------- classification
def classify_handle(attempts, final_owner, lwt=True):
    """Classify one raced handle.

    attempts     list of dicts: owner, outcome, applied (True/False/None), returned_owner
    final_owner  owner read back afterwards (None if absent or the read failed)

    LWT categories
      exactly-one     one applied=True, every other successful attempt saw the winner
      timeout-winner  no visible winner, but the row exists and its owner is a client whose
                      LWT timed out: the "failed" CAS was in fact committed (WriteTimeout
                      means unknown, not failed)
      no-winner       nothing applied and nothing stored (e.g. Paxos quorum unavailable)
      violation       more than one winner, or losers/final read disagree on the owner
    Plain mode: 'last-write-wins' with the number of acknowledged-but-overwritten writes.
    """
    ok = [a for a in attempts if a["outcome"] == "ok"]
    if not lwt:
        overwritten = max(0, len(ok) - 1) if final_owner is not None else len(ok)
        return {"category": "last-write-wins" if ok else "no-winner", "winner": final_owner,
                "acked_overwritten": overwritten}
    winners = [a for a in ok if a["applied"]]
    losers = [a for a in ok if a["applied"] is False]
    seen = {a["returned_owner"] for a in losers if a["returned_owner"] is not None}
    if len(winners) > 1:
        return {"category": "violation", "winner": None, "acked_overwritten": 0}
    if len(winners) == 1:
        w = winners[0]["owner"]
        consistent = seen <= {w} and (final_owner is None or final_owner == w)
        return {"category": "exactly-one" if consistent else "violation", "winner": w,
                "acked_overwritten": 0}
    owner = final_owner if final_owner is not None else (next(iter(seen)) if len(seen) == 1 else None)
    if len(seen) > 1:
        return {"category": "violation", "winner": None, "acked_overwritten": 0}
    if owner is None:
        return {"category": "no-winner", "winner": None, "acked_overwritten": 0}
    timed_out = {a["owner"] for a in attempts if a["outcome"] in ("write_timeout", "client_timeout")}
    if owner in timed_out:
        return {"category": "timeout-winner", "winner": owner, "acked_overwritten": 0}
    return {"category": "violation", "winner": owner, "acked_overwritten": 0}


def summarize_race(per_handle, attempts_all, lwt, final_read_failed):
    cats = [h["category"] for h in per_handle]
    s = {
        "handles": len(per_handle),
        "ops_ok": sum(1 for a in attempts_all if a["outcome"] == "ok"),
        "ops_failed": sum(1 for a in attempts_all if a["outcome"] != "ok"),
        "exactly_one": cats.count("exactly-one"),
        "timeout_winner": cats.count("timeout-winner"),
        "no_winner": cats.count("no-winner"),
        "violations": cats.count("violation"),
        "acked_overwritten": sum(h["acked_overwritten"] for h in per_handle),
        "final_read_failed": final_read_failed,
    }
    if s["violations"]:
        s["verdict"] = "VIOLATION"
    elif lwt and s["exactly_one"] + s["timeout_winner"] == s["handles"]:
        s["verdict"] = "SAFE: one winner per handle"
    elif lwt and s["no_winner"] == s["handles"]:
        s["verdict"] = "SAFE: unavailable (no Paxos quorum), nothing applied"
    elif lwt:
        s["verdict"] = "SAFE: partial availability"
    else:
        s["verdict"] = f"LWW: {s['acked_overwritten']} acknowledged writes silently overwritten"
    return s


def append_csv(path, fields, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


# --------------------------------------------------------------------------- CQL helpers
def _db():
    from app import db  # noqa: PLC0415
    return db


def run_race(session, log, handles, clients, lwt=True, barrier_timeout=10.0):
    """Race `clients` concurrent claims on each handle. Returns (per_handle, attempts)."""
    db = _db()
    cql, cl, serial = (LWT_INSERT, "QUORUM", "SERIAL") if lwt else (PLAIN_INSERT, "QUORUM", None)
    ps = db.stmt(cql, cl, serial_cl=serial, session=session)
    read_ps = db.stmt(SELECT_OWNER, "SERIAL" if lwt else "QUORUM", session=session)
    op, cl_label = ("lwt", "SERIAL") if lwt else ("write", "QUORUM")
    per_handle, attempts_all, read_failed = [], [], 0
    with ThreadPoolExecutor(max_workers=clients) as pool:
        for handle in handles:
            barrier = threading.Barrier(clients, timeout=barrier_timeout)

            def claim(k, handle=handle, barrier=barrier):
                owner = f"client-{k:02d}"
                barrier.wait()
                res = db.timed_execute(session, ps, [handle, owner])
                row = res.rows[0] if res.outcome == "ok" and res.rows else None
                applied = row_applied(row) if lwt else (True if res.outcome == "ok" else None)
                returned = getattr(row, "owner", None) if (row is not None and lwt) else None
                log.log(op=op, cl=cl_label, key=handle, latency_ms=res.latency_ms, outcome=res.outcome,
                        error_type=res.error_type, coordinator=res.coordinator)
                return {"handle": handle, "owner": owner, "outcome": res.outcome,
                        "error_type": res.error_type, "applied": applied, "returned_owner": returned,
                        "latency_ms": round(res.latency_ms, 3), "coordinator": res.coordinator}

            attempts = list(pool.map(claim, range(clients)))
            final = db.timed_execute(session, read_ps, [handle])
            if final.outcome == "ok":
                final_owner = final.rows[0].owner if final.rows else None
            else:
                final_owner, read_failed = None, read_failed + 1
            verdict = classify_handle(attempts, final_owner, lwt)
            for a in attempts:
                a["final_owner"] = final_owner or ""
                a["category"] = verdict["category"]
            per_handle.append({"handle": handle, "final_owner": final_owner, **verdict})
            attempts_all.extend(attempts)
    return per_handle, attempts_all, read_failed


# --------------------------------------------------------------------------- commands
def cmd_race(a, session):
    from app.results_log import ResultsLog, default_path  # noqa: PLC0415
    lwt = not a.plain
    variant = a.variant or ("race" if lwt else "plain")
    run_id = a.run_id or f"exp6-{variant}-r{a.rep}-{utc_stamp()}"
    out = a.out or default_path("exp6", variant, "SERIAL" if lwt else "QUORUM", a.rep)
    handles = [f"{run_id}-h{j:02d}" for j in range(a.handles)]
    with ResultsLog(out, "exp6", variant, run_id) as log:
        per_handle, attempts, read_failed = run_race(session, log, handles, a.clients, lwt)
    s = summarize_race(per_handle, attempts, lwt, read_failed)

    detail_dir = os.path.join(LOG_DIR, run_id)
    os.makedirs(detail_dir, exist_ok=True)
    detail = os.path.join(detail_dir, f"{variant}_detail.csv")
    fields = ["handle", "owner", "outcome", "error_type", "applied", "returned_owner", "final_owner",
              "category", "latency_ms", "coordinator"]
    with open(detail, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(attempts)
    append_csv(RACE_LOG, RACE_FIELDS, {"ts_utc": utc_now_iso(), "run_id": run_id, "variant": variant,
                                       "mode": "lwt" if lwt else "plain", "clients": a.clients, **s})

    mode = "LWT (INSERT ... IF NOT EXISTS, serial SERIAL)" if lwt else "plain INSERT at QUORUM"
    print(f"=== race: {mode}, {a.clients} clients x {a.handles} handles, run {run_id}")
    print(f"{'handle':<14} {'applied/ok/failed':>18}  {'final owner':<12} category")
    for h in per_handle:
        rows = [x for x in attempts if x["handle"] == h["handle"]]
        applied = sum(1 for x in rows if x["applied"] and x["outcome"] == "ok")
        ok = sum(1 for x in rows if x["outcome"] == "ok")
        print(f"{h['handle'][-14:]:<14} {applied:>6}/{ok:>3}/{len(rows) - ok:<6}  "
              f"{(h['final_owner'] or '-'):<12} {h['category']}")
    errors = {}
    for x in attempts:
        if x["outcome"] != "ok":
            errors[x["outcome"]] = errors.get(x["outcome"], 0) + 1
    print(f"operations: {s['ops_ok']} ok, {s['ops_failed']} failed"
          + (" (" + ", ".join(f"{k}={v}" for k, v in sorted(errors.items())) + ")" if errors else ""))
    if lwt:
        print(f"handles with exactly one winner: {s['exactly_one']}/{s['handles']}; "
              f"timed-out-but-committed winners: {s['timeout_winner']}; no winner: {s['no_winner']}; "
              f"SAFETY VIOLATIONS: {s['violations']}")
    else:
        print(f"every successful client was told 'success'; acknowledged writes silently overwritten "
              f"by last-write-wins: {s['acked_overwritten']}")
    print(f"verdict: {s['verdict']}\ncsv: {out}\ndetail: {detail}")
    return 1 if s["violations"] else 0


def cmd_latency(a, session):
    db = _db()
    from app.results_log import ResultsLog, default_path  # noqa: PLC0415
    run_id = a.run_id or f"exp6-latency-r{a.rep}-{utc_stamp()}"
    out = a.out or default_path("exp6", "latency", "SERIAL-QUORUM", a.rep)
    lwt_ps = db.stmt(LWT_INSERT, "QUORUM", serial_cl="SERIAL", session=session)
    plain_ps = db.stmt(PLAIN_INSERT, "QUORUM", session=session)
    for i in range(a.warmup):                      # not logged: connection and JIT warm-up
        db.timed_execute(session, lwt_ps, [f"{run_id}-w{i}", "warmup"])
        db.timed_execute(session, plain_ps, [f"{run_id}-v{i}", "warmup"])
    lat = {"lwt": [], "write": []}
    fails = {"lwt": 0, "write": 0}
    with ResultsLog(out, "exp6", "latency", run_id) as log:
        for i in range(a.n):
            # alternate which goes first so drift affects both equally
            order = (("lwt", lwt_ps, "SERIAL"), ("write", plain_ps, "QUORUM"))
            for op, ps, cl in (order if i % 2 == 0 else order[::-1]):
                handle = f"{run_id}-{'l' if op == 'lwt' else 'p'}{i:04d}"
                res = db.timed_execute(session, ps, [handle, "latency"])
                log.log(op=op, cl=cl, key=handle, latency_ms=res.latency_ms, outcome=res.outcome,
                        error_type=res.error_type, coordinator=res.coordinator)
                if res.outcome == "ok":
                    lat[op].append(res.latency_ms)
                else:
                    fails[op] += 1
    print(f"=== latency: {a.n} LWT vs {a.n} plain QUORUM inserts (fresh handles, sequential)")
    for op, name in (("write", "plain INSERT, CL QUORUM"), ("lwt", "LWT IF NOT EXISTS (Paxos)")):
        v = lat[op]
        if v:
            print(f"{name:<28} n={len(v):<4} failed={fails[op]:<3} p50={percentile(v, 50):.2f}ms "
                  f"p95={percentile(v, 95):.2f}ms p99={percentile(v, 99):.2f}ms mean={sum(v) / len(v):.2f}ms")
        else:
            print(f"{name:<28} no successful operations ({fails[op]} failed)")
    if lat["lwt"] and lat["write"]:
        print(f"median ratio LWT / plain: {percentile(lat['lwt'], 50) / percentile(lat['write'], 50):.2f}x")
    print(f"csv: {out}")
    return 0 if lat["lwt"] and lat["write"] else 3


def paxos_variant(session):
    try:
        rows = list(session.execute("SELECT value FROM system_views.settings WHERE name = 'paxos_variant'"))
        return rows[0].value if rows else "unknown"
    except Exception as exc:  # noqa: BLE001
        return f"unknown ({type(exc).__name__})"


def format_trace(future, title):
    lines = [f"--- {title}"]
    try:
        trace = future.get_query_trace(5.0)  # positional: ResponseFuture uses max_wait
    except Exception as exc:  # noqa: BLE001
        return lines + [f"(no trace: {type(exc).__name__}: {exc})"], 0
    lines.append(f"coordinator {trace.coordinator}, duration {trace.duration}")
    hits = 0
    for ev in trace.events:
        mark = "*" if PAXOS_RE.search(str(ev.description)) else " "
        hits += mark == "*"
        elapsed = getattr(ev, "source_elapsed", None)
        us = int(elapsed.total_seconds() * 1e6) if elapsed is not None else 0
        lines.append(f"{mark} {str(ev.source):<15} {us:>8} us  {ev.description}")
    return lines, hits


def cmd_trace(a, session):
    db = _db()
    run_id = a.run_id or f"exp6-trace-{utc_stamp()}"
    handle = f"{run_id}-traced"
    ps = db.stmt(LWT_INSERT, "QUORUM", serial_cl="SERIAL", session=session)
    variant = paxos_variant(session)
    out = [f"paxos_variant = {variant}", f"handle = {handle}",
           "lines marked * mention a Paxos phase (prepare/promise, propose/accept, commit) or the CAS check", ""]
    total = 0
    for owner, title in (("first", "LWT that wins (row absent -> applied)"),
                         ("second", "LWT that loses (row present -> not applied)")):
        res = db.timed_execute(session, ps, [handle, owner], trace=True)
        row = res.rows[0] if res.outcome == "ok" and res.rows else None
        out.append(f"{title}: outcome={res.outcome} applied={row_applied(row)} "
                   f"owner={getattr(row, 'owner', None)} latency={res.latency_ms:.2f}ms")
        lines, hits = format_trace(res.future, title) if res.future is not None else (["(no trace)"], 0)
        total += hits
        out += lines + [""]
    text = "\n".join(out)
    print(text)
    path = a.save or os.path.join(LOG_DIR, run_id, "paxos_trace.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(f"saved: {path}")
    return 0 if total else 3


# --------------------------------------------------------------------------- CLI
def _label(value):
    if "_" in value:
        raise argparse.ArgumentTypeError("labels must not contain '_'")
    return value


def build_parser():
    p = argparse.ArgumentParser(prog="python -m recovery.lwt_demo", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("race", help="concurrent claims of the same handles")
    r.add_argument("--clients", type=int, default=10)
    r.add_argument("--handles", type=int, default=20)
    r.add_argument("--plain", action="store_true", help="plain INSERT instead of IF NOT EXISTS")
    r.add_argument("--variant", type=_label, help="label, e.g. race-1down (default race/plain)")
    r.add_argument("--rep", type=int, default=1)
    r.add_argument("--run-id")
    r.add_argument("--out")
    lt = sub.add_parser("latency", help="LWT vs plain QUORUM insert latency")
    lt.add_argument("--n", type=int, default=200)
    lt.add_argument("--warmup", type=int, default=20)
    lt.add_argument("--rep", type=int, default=1)
    lt.add_argument("--run-id")
    lt.add_argument("--out")
    t = sub.add_parser("trace", help="one traced winning and one traced losing LWT")
    t.add_argument("--run-id")
    t.add_argument("--save")
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.cmd == "race" and (a.clients < 2 or a.handles < 1):
        print("race needs --clients >= 2 and --handles >= 1", file=sys.stderr)
        return 2
    db = _db()
    try:
        session = db.get_session()
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED to connect: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Run inside the client container: docker compose run --rm client python -m recovery.lwt_demo ...",
              file=sys.stderr)
        return 2
    try:
        t0 = time.monotonic()
        rc = {"race": cmd_race, "latency": cmd_latency, "trace": cmd_trace}[a.cmd](a, session)
        print(f"elapsed {time.monotonic() - t0:.1f}s")
        return rc
    finally:
        db.shutdown(session)


if __name__ == "__main__":
    sys.exit(main())
