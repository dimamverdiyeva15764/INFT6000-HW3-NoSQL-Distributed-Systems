"""Workload generator: drives read/write traffic at a chosen consistency level and logs
every operation to the shared results CSV.

Modes
  write   INSERT chat messages into random rooms
  read    SELECT the newest --read-limit messages of a random room
  mixed   --read-ratio reads, the rest writes (default 50/50)
  probe   freshness probe: write room_state.last_seq = n at --write-cl through one
          coordinator, immediately read it back at --read-cl through a *different*
          coordinator, and mark the read stale=1 if it returned a value lower than n

Load models
  --rate R   open loop: operations are scheduled every 1/R s regardless of latency
             (the generator falls behind only if all --threads are busy)
  --max      closed loop: every thread issues its next request as soon as the last returns

Examples (inside the client container)
  python -m workload.runner --mode mixed --cl QUORUM --rate 200 --duration 60 --exp exp1 --variant baseline
  python -m workload.runner --mode read --cl ALL --rate 200 --threads 8 --duration 60 --warmup 10 --exp exp2
  python -m workload.runner --mode probe --write-cl ONE --read-cl ONE --probes 2000 --exp exp2
  python -m workload.runner --preload 10000 --duration 0            # preload only

A one-line summary is printed every second (ops/s, ok, errors by type, latency); a
final summary is printed at the end. Ctrl-C stops the run cleanly and keeps the CSV.
"""
import argparse
import os
import random
import signal
import string
import sys
import threading
import time
import uuid
from collections import Counter

from app import config
from app.db import (cl_name, cl_value, coordinator_profile, get_session, shutdown, stmt,
                    timed_execute)
from app.results_log import ResultsLog, default_path, utc_stamp

INSERT_CQL = ("INSERT INTO messages (room, msg_id, author, body, writer_run) "
              "VALUES (?, ?, ?, ?, ?)")
SELECT_CQL = "SELECT msg_id, author, body FROM messages WHERE room = ? LIMIT ?"
PROBE_WRITE_CQL = "UPDATE room_state SET last_seq = ?, updated_by = ? WHERE room = ?"
PROBE_READ_CQL = "SELECT last_seq FROM room_state WHERE room = ?"


# --------------------------------------------------------------------------- statistics
def percentile(values, q):
    """Linear-interpolated percentile (q in 0..100) of an unsorted list; None if empty."""
    if not values:
        return None
    data = sorted(values)
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * q / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def fmt_ms(value):
    return "-" if value is None else f"{value:.2f}ms"


class Stats:
    """Thread-safe counters for the live per-second line and the final summary."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total = Counter()          # outcome -> count, measured window only
        self.latencies = []             # ok latencies, measured window
        self.stale = 0
        self.probe_reads = 0
        self.rows_read = 0
        self.reads_ok = 0
        self._iv_outcomes = Counter()
        self._iv_lat = []
        self._iv_stale = 0

    def record(self, outcome, latency_ms, measured, stale=None, rows=None):
        with self._lock:
            self._iv_outcomes[outcome] += 1
            if outcome == "ok":
                self._iv_lat.append(latency_ms)
            if stale:
                self._iv_stale += 1
            if not measured:
                return
            self.total[outcome] += 1
            if outcome == "ok":
                self.latencies.append(latency_ms)
                if rows is not None:
                    self.reads_ok += 1
                    self.rows_read += rows
            if stale is not None:
                self.probe_reads += 1
                self.stale += int(bool(stale))

    def take_interval(self):
        with self._lock:
            out = (self._iv_outcomes, self._iv_lat, self._iv_stale)
            self._iv_outcomes, self._iv_lat, self._iv_stale = Counter(), [], 0
        return out


# --------------------------------------------------------------------------- scheduling
class OpenLoopSchedule:
    """Hands out start times start, start+1/R, start+2/R ... to the worker threads."""

    def __init__(self, rate, start):
        self.interval = 1.0 / rate
        self.start = start
        self._i = 0
        self._lock = threading.Lock()

    def next_slot(self):
        with self._lock:
            i = self._i
            self._i += 1
        return self.start + i * self.interval


class Budget:
    """Optional cap on the number of measured operations (probe mode --probes)."""

    def __init__(self, limit):
        self.limit = limit
        self.used = 0
        self._lock = threading.Lock()

    def claim(self):
        if self.limit is None:
            return True
        with self._lock:
            if self.used >= self.limit:
                return False
            self.used += 1
            return True


# --------------------------------------------------------------------------- the runner
class Runner:
    def __init__(self, args, session, log):
        self.a = args
        self.session = session
        self.log = log
        self.stats = Stats()
        self.stop = threading.Event()
        self.hosts = [config.resolve_node(h) for h in args.host_list]
        self.rooms = [f"{args.room_prefix}-{i:04d}" for i in range(args.rooms)]
        self.payload = "".join(random.Random(7).choice(string.ascii_letters) for _ in range(args.payload))
        self.budget = Budget(args.probes if args.mode == "probe" else None)
        self.behind = 0
        self._behind_lock = threading.Lock()

    # -- single operations ------------------------------------------------------------
    def do_write(self, rng, measured):
        room = rng.choice(self.rooms)
        res = timed_execute(self.session, stmt(INSERT_CQL, self.a.write_cl, session=self.session),
                            [room, uuid.uuid1(), "runner", self.payload, self.a.run_id])
        self._record("write", self.a.write_cl, room, res, measured)

    def do_read(self, rng, measured):
        room = rng.choice(self.rooms)
        res = timed_execute(self.session, stmt(SELECT_CQL, self.a.read_cl, session=self.session), [room, self.a.read_limit])
        self._record("read", self.a.read_cl, room, res, measured,
                     rows=len(res.rows) if res.rows is not None else None)

    def do_probe(self, worker, state, measured):
        """One freshness probe: write seq n via coordinator A, read via coordinator B != A."""
        key = state["key"]
        state["seq"] += 1
        n = state["seq"]
        i = state["i"]
        state["i"] += 1
        w_host = self.hosts[(worker + i) % len(self.hosts)]
        r_host = self.hosts[(worker + i + 1) % len(self.hosts)] if len(self.hosts) > 1 else w_host
        w = timed_execute(self.session, stmt(PROBE_WRITE_CQL, self.a.write_cl, session=self.session), [n, self.a.run_id, key],
                          profile=coordinator_profile(w_host))
        self._record("write", self.a.write_cl, key, w, measured, expected_seq=n)
        if w.outcome != "ok":
            return  # value is unknown after a failed write; next probe uses n+1
        r = timed_execute(self.session, stmt(PROBE_READ_CQL, self.a.read_cl, session=self.session), [key],
                          profile=coordinator_profile(r_host))
        observed, stale = None, None
        if r.outcome == "ok":
            observed = r.rows[0].last_seq if r.rows else None
            stale = 1 if (observed is None or observed < n) else 0
        self._record("read", self.a.read_cl, key, r, measured, expected_seq=n,
                     observed_seq=observed, stale=stale)

    def _record(self, op, cl, key, res, measured, expected_seq=None, observed_seq=None,
                stale=None, rows=None):
        self.stats.record(res.outcome, res.latency_ms, measured, stale=stale, rows=rows)
        if measured:
            self.log.log(op=op, cl=cl_name(cl), key=key, latency_ms=res.latency_ms,
                         outcome=res.outcome, error_type=res.error_type,
                         expected_seq=expected_seq, observed_seq=observed_seq,
                         stale=stale, coordinator=res.coordinator)

    # -- worker loop ------------------------------------------------------------------
    def worker(self, wid, schedule):
        rng = random.Random(self.a.seed * 1000 + wid)
        probe_state = {"key": f"probe-{self.a.run_id}-{wid}", "seq": 0, "i": 0}
        while not self.stop.is_set():
            if schedule is not None:
                slot = schedule.next_slot()
                if slot >= self.end:
                    break
                delay = slot - time.monotonic()
                if delay > 0:
                    if self.stop.wait(delay):
                        break
                elif delay < -0.05:
                    with self._behind_lock:
                        self.behind += 1
                now = slot
            else:
                now = time.monotonic()
                if now >= self.end:
                    break
            measured = now >= self.measure_start
            if measured and not self.budget.claim():
                self.stop.set()
                break
            mode = self.a.mode
            if mode == "write":
                self.do_write(rng, measured)
            elif mode == "read":
                self.do_read(rng, measured)
            elif mode == "mixed":
                if rng.random() < self.a.read_ratio:
                    self.do_read(rng, measured)
                else:
                    self.do_write(rng, measured)
            else:
                self.do_probe(wid, probe_state, measured)

    def reporter(self):
        t0 = self.t0
        while not self.stop.wait(1.0):
            outcomes, lats, stale = self.stats.take_interval()
            elapsed = time.monotonic() - t0
            phase = "warmup " if time.monotonic() < self.measure_start else ""
            n = sum(outcomes.values())
            errs = {k: v for k, v in outcomes.items() if k != "ok"}
            line = (f"[{elapsed:6.1f}s] {phase}{n:6.0f} ops/s  ok={outcomes.get('ok', 0):<5} "
                    f"err={sum(errs.values()):<4} p50={fmt_ms(percentile(lats, 50))} "
                    f"p99={fmt_ms(percentile(lats, 99))}")
            if self.a.mode == "probe":
                line += f"  stale={stale}"
            if errs:
                line += "  " + " ".join(f"{k}={v}" for k, v in sorted(errs.items()))
            if not self.a.quiet:
                print(line, flush=True)

    def run(self):
        a = self.a
        self.t0 = time.monotonic()
        self.measure_start = self.t0 + a.warmup
        self.end = self.measure_start + a.duration if a.duration > 0 else float("inf")
        schedule = OpenLoopSchedule(a.rate, self.t0) if a.rate else None
        threads = [threading.Thread(target=self.worker, args=(i, schedule), daemon=True)
                   for i in range(a.threads)]
        rep = threading.Thread(target=self.reporter, daemon=True)
        for t in threads:
            t.start()
        rep.start()
        try:
            while any(t.is_alive() for t in threads):
                for t in threads:
                    t.join(timeout=0.2)
        except KeyboardInterrupt:
            print("\ninterrupted - stopping workers", flush=True)
            self.stop.set()
            for t in threads:
                t.join(timeout=10)
        self.stop.set()
        self.measured_s = max(min(time.monotonic(), self.end) - self.measure_start, 1e-9)
        if a.mode == "probe" and a.probes:
            self.measured_s = max(time.monotonic() - self.measure_start, 1e-9)
        rep.join(timeout=2)

    def summary(self):
        s, a = self.stats, self.a
        ok = s.total.get("ok", 0)
        total = sum(s.total.values())
        errs = {k: v for k, v in s.total.items() if k != "ok"}
        lines = [
            "",
            f"=== summary: exp={a.exp} variant={a.variant} mode={a.mode} "
            f"write_cl={cl_name(a.write_cl)} read_cl={cl_name(a.read_cl)} run_id={a.run_id}",
            f"load model:       {'open loop, target ' + str(a.rate) + ' ops/s' if a.rate else 'closed loop (--max)'}"
            f", {a.threads} threads, {self.measured_s:.1f}s measured after {a.warmup:g}s warm-up",
            f"operations:       {total} ({ok} ok, {total - ok} failed"
            f"{', ' + ', '.join(f'{k}={v}' for k, v in sorted(errs.items())) if errs else ''})",
            f"throughput (ok):  {ok / self.measured_s:.1f} ops/s",
            f"latency (ok):     p50={fmt_ms(percentile(s.latencies, 50))} "
            f"p95={fmt_ms(percentile(s.latencies, 95))} p99={fmt_ms(percentile(s.latencies, 99))} "
            f"mean={fmt_ms(sum(s.latencies) / len(s.latencies) if s.latencies else None)}",
        ]
        if s.reads_ok:
            lines.append(f"rows per read:    {s.rows_read / s.reads_ok:.1f}")
        if a.mode == "probe":
            pct = 100.0 * s.stale / s.probe_reads if s.probe_reads else 0.0
            lines.append(f"stale reads:      {s.stale} of {s.probe_reads} probes ({pct:.2f}%)")
        if a.rate and self.behind:
            lines.append(f"WARNING: {self.behind} operations started >50 ms late "
                         f"(all threads busy) - raise --threads or lower --rate")
        if a.mode in ("read", "mixed") and s.reads_ok and s.rows_read == 0:
            lines.append("WARNING: reads returned no rows - preload data first (--preload N)")
        lines.append(f"csv:              {self.log.path} ({self.log.rows} rows)")
        print("\n".join(lines), flush=True)
        return ok


# --------------------------------------------------------------------------- preload
def preload(session, rooms, count, run_id, payload_len, cl="QUORUM"):
    from cassandra.concurrent import execute_concurrent_with_args
    payload = "p" * payload_len
    prepared = stmt(INSERT_CQL, cl, session=session)
    done, failed, batch = 0, 0, 2000
    t0 = time.monotonic()
    while done + failed < count:
        n = min(batch, count - done - failed)
        params = [(rooms[(done + failed + i) % len(rooms)], uuid.uuid1(), "preload", payload, run_id)
                  for i in range(n)]
        results = execute_concurrent_with_args(session, prepared, params, concurrency=64,
                                               raise_on_first_error=False)
        ok = sum(1 for success, _ in results if success)
        done += ok
        failed += n - ok
        print(f"preload: {done}/{count} rows written ({failed} failed)", flush=True)
    print(f"preload finished in {time.monotonic() - t0:.1f}s", flush=True)
    return failed


# --------------------------------------------------------------------------- CLI
def _cl(value):
    try:
        cl_value(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None
    return value.upper()


def build_parser():
    p = argparse.ArgumentParser(prog="python -m workload.runner", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=["write", "read", "mixed", "probe"], default="mixed")
    p.add_argument("--cl", type=_cl, help="consistency level for reads and writes")
    p.add_argument("--write-cl", type=_cl, help="write consistency level (overrides --cl)")
    p.add_argument("--read-cl", type=_cl, help="read consistency level (overrides --cl)")
    load = p.add_mutually_exclusive_group()
    load.add_argument("--rate", type=float, help="open loop: target operations per second")
    load.add_argument("--max", action="store_true", help="closed loop: as fast as possible")
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--duration", type=float, default=60, help="measured seconds (0 = preload only)")
    p.add_argument("--warmup", type=float, default=0, help="seconds run but not logged before measuring")
    p.add_argument("--probes", type=int, help="probe mode: stop after this many measured probes")
    p.add_argument("--rooms", type=int, default=100, help="number of rooms (partitions)")
    p.add_argument("--room-prefix", default="room")
    p.add_argument("--read-ratio", type=float, default=0.5, help="mixed mode: fraction of reads")
    p.add_argument("--read-limit", type=int, default=10, help="messages returned per read")
    p.add_argument("--payload", type=int, default=100, help="message body size in bytes")
    p.add_argument("--preload", type=int, default=0, help="insert N messages (at QUORUM) before the run")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--exp", default="adhoc", help="experiment id, e.g. exp2")
    p.add_argument("--variant", help="variant label (default: the mode)")
    p.add_argument("--rep", type=int, default=1, help="repetition number (file name)")
    p.add_argument("--run-id", help="run identifier stored in every row")
    p.add_argument("--out", help="CSV path (default results/raw/<exp>/<exp>_<variant>_<cl>_r<rep>_<stamp>.csv)")
    p.add_argument("--hosts", help="comma-separated contact points (default: $CASSANDRA_HOSTS)")
    p.add_argument("--quiet", action="store_true", help="no per-second line")
    return p


def resolve_args(args):
    """Fill in defaults that depend on other arguments; returns the label used for 'cl'."""
    args.write_cl = args.write_cl or args.cl or "QUORUM"
    args.read_cl = args.read_cl or args.cl or "QUORUM"
    if args.mode == "probe":
        cl_label = f"{args.write_cl}-{args.read_cl}"
        if not args.rate and not args.max:
            args.max = True
        if args.probes is None and args.duration <= 0:
            raise SystemExit("probe mode needs --probes N or --duration S")
    else:
        cl_label = args.write_cl if args.write_cl == args.read_cl else f"{args.write_cl}-{args.read_cl}"
        if not args.rate and not args.max:
            args.rate = 200.0
    if args.mode == "write":
        cl_label = args.write_cl
    elif args.mode == "read":
        cl_label = args.read_cl
    args.variant = args.variant or args.mode
    args.run_id = args.run_id or f"{args.exp}-{args.variant}-{cl_label}-r{args.rep}-{utc_stamp()}"
    args.host_list = args.hosts.split(",") if args.hosts else list(config.CASSANDRA_HOSTS)
    if args.mode == "probe" and args.probes and args.duration == 60:
        args.duration = 0  # count-based probe run: no time limit unless given explicitly
    if not 0 <= args.read_ratio <= 1:
        raise SystemExit("--read-ratio must be between 0 and 1")
    if args.threads < 1:
        raise SystemExit("--threads must be >= 1")
    return cl_label


def main(argv=None):
    args = build_parser().parse_args(argv)
    cl_label = resolve_args(args)

    try:
        session = get_session(hosts=args.host_list)
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED to connect: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Run inside the client container: docker compose run --rm client python -m workload.runner ...",
              file=sys.stderr)
        return 2

    try:
        rooms = [f"{args.room_prefix}-{i:04d}" for i in range(args.rooms)]
        if args.preload:
            if preload(session, rooms, args.preload, f"preload-{args.run_id}", args.payload):
                print("WARNING: some preload writes failed", file=sys.stderr)
        if args.duration <= 0 and not (args.mode == "probe" and args.probes):
            return 0

        path = args.out or default_path(args.exp, args.variant, cl_label, args.rep)
        if os.path.exists(path):
            print(f"FAILED: {path} exists; results are never overwritten", file=sys.stderr)
            return 2
        print(f"run_id={args.run_id} mode={args.mode} write_cl={args.write_cl} read_cl={args.read_cl} "
              f"{'rate=' + format(args.rate, 'g') if args.rate else 'closed-loop'} threads={args.threads} "
              f"duration={args.duration:g}s warmup={args.warmup:g}s"
              f"{' probes=' + str(args.probes) if args.probes else ''}", flush=True)
        with ResultsLog(path, args.exp, args.variant, args.run_id) as log:
            runner = Runner(args, session, log)
            signal.signal(signal.SIGTERM, lambda *_: runner.stop.set())
            runner.run()
            ok = runner.summary()
        return 0 if ok > 0 else 3
    finally:
        shutdown(session)


if __name__ == "__main__":
    sys.exit(main())
