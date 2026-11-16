"""Continuously measure reads and writes at ONE, QUORUM, and ALL during a fault."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

from app.db import get_session, shutdown, stmt, timed_execute
from app.results_log import ResultsLog, default_path

CONSISTENCY_LEVELS = ("ONE", "QUORUM", "ALL")
WRITE_CQL = "UPDATE room_state SET last_seq = ?, updated_by = ? WHERE room = ?"
READ_CQL = "SELECT last_seq FROM room_state WHERE room = ?"


def run_probe(session, log, run_id, duration, interval, room_prefix):
    sequence = {cl: 0 for cl in CONSISTENCY_LEVELS}
    counts = {cl: {"ok": 0, "failed": 0} for cl in CONSISTENCY_LEVELS}
    deadline = time.monotonic() + duration

    def probe_level(cl):
        next_cycle = time.monotonic()
        while time.monotonic() < deadline:
            key = f"{room_prefix}-{cl.lower()}"
            sequence[cl] += 1
            expected = sequence[cl]
            write = timed_execute(session, stmt(WRITE_CQL, cl, session=session),
                                  [expected, run_id, key])
            log.log(op="write", cl=cl, key=key, latency_ms=write.latency_ms,
                    outcome=write.outcome, error_type=write.error_type,
                    expected_seq=expected, coordinator=write.coordinator)
            counts[cl]["ok" if write.outcome == "ok" else "failed"] += 1
            if write.outcome == "ok":
                read = timed_execute(session, stmt(READ_CQL, cl, session=session), [key])
                observed = read.rows[0].last_seq if read.outcome == "ok" and read.rows else None
                stale = None if read.outcome != "ok" else int(observed is None or observed < expected)
                log.log(op="read", cl=cl, key=key, latency_ms=read.latency_ms,
                        outcome=read.outcome, error_type=read.error_type,
                        expected_seq=expected, observed_seq=observed, stale=stale,
                        coordinator=read.coordinator)
                counts[cl]["ok" if read.outcome == "ok" else "failed"] += 1

            next_cycle += interval
            delay = next_cycle - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_cycle = time.monotonic()

    with ThreadPoolExecutor(max_workers=len(CONSISTENCY_LEVELS)) as executor:
        futures = [executor.submit(probe_level, cl) for cl in CONSISTENCY_LEVELS]
        for future in futures:
            future.result()

    for cl in CONSISTENCY_LEVELS:
        print(f"{cl}: {counts[cl]['ok']} successful operations, "
              f"{counts[cl]['failed']} failed operations")
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=120, help="probe duration in seconds")
    parser.add_argument("--interval", type=float, default=0.25, help="seconds between full CL sweeps")
    parser.add_argument("--rep", type=int, default=1)
    parser.add_argument("--run-id", help="run identifier stored in the results CSV")
    parser.add_argument("--room-prefix", default="p3-availability")
    parser.add_argument("--out", help="CSV output path; defaults under results/raw/exp3/")
    args = parser.parse_args(argv)
    if args.duration <= 0 or args.interval <= 0:
        parser.error("--duration and --interval must be positive")

    run_id = args.run_id or f"exp3-availability-r{args.rep}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    output = args.out or default_path("exp3", "availability", "ONE-QUORUM-ALL", args.rep)
    if not Path(output).resolve().is_relative_to(Path("results/raw/exp3").resolve()):
        parser.error("--out must be inside results/raw/exp3/")
    session = None
    try:
        session = get_session()
        with ResultsLog(output, "exp3", "availability", run_id) as log:
            run_probe(session, log, run_id, args.duration, args.interval,
                      f"{args.room_prefix}-{run_id}")
        print(f"CSV: {output}")
        return 0
    finally:
        shutdown(session)


if __name__ == "__main__":
    raise SystemExit(main())
