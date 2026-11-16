"""Thread-safe CSV writer for the shared results schema (docs/CONTRACTS.md).

Every experiment writes the same columns so that one analysis pipeline reads all of
them. Each row is flushed immediately, so data written before a client crash during a
chaos experiment is never lost.
"""
import csv
import os
import threading
from datetime import datetime, timezone

FIELDS = [
    "ts_utc", "exp", "variant", "run_id", "op", "cl", "key", "latency_ms",
    "outcome", "error_type", "expected_seq", "observed_seq", "stale", "coordinator",
]


def utc_now_iso(dt=None):
    """ISO-8601 UTC with microseconds, e.g. 2026-11-16T10:15:03.123456Z."""
    dt = dt or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def utc_stamp(dt=None):
    """Minute-resolution stamp used in file names: 20261116T1015Z."""
    dt = dt or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%MZ")


def result_filename(exp, variant, cl, rep, dt=None):
    """<exp>_<variant>_<cl>_r<rep>_<YYYYmmddTHHMMZ>.csv (fields must not contain '_')."""
    for name, value in (("exp", exp), ("variant", variant), ("cl", cl)):
        if "_" in str(value):
            raise ValueError(f"{name} {value!r} must not contain '_' (it separates file-name fields)")
    return f"{exp}_{variant}_{cl}_r{int(rep)}_{utc_stamp(dt)}.csv"


def default_path(exp, variant, cl, rep, root="results/raw", dt=None):
    """results/raw/<exp>/<file>; adds -2, -3 ... instead of overwriting an existing run."""
    name = result_filename(exp, variant, cl, rep, dt)
    path = os.path.join(root, exp, name)
    n = 2
    while os.path.exists(path):
        path = os.path.join(root, exp, name[:-4] + f"-{n}.csv")
        n += 1
    return path


class ResultsLog:
    """Append-only CSV writer; ``log()`` may be called from many threads at once."""

    def __init__(self, path, exp, variant, run_id, overwrite=False):
        if os.path.exists(path) and not overwrite:
            raise FileExistsError(f"{path} exists; results are never overwritten")
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.path = path
        self.exp, self.variant, self.run_id = exp, variant, run_id
        self._lock = threading.Lock()
        self._fh = open(path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=FIELDS)
        self._writer.writeheader()
        self._fh.flush()
        self.rows = 0

    def log(self, op, cl, key, latency_ms, outcome, error_type="", expected_seq="",
            observed_seq="", stale="", coordinator="", ts_utc=None):
        row = {
            "ts_utc": ts_utc or utc_now_iso(),
            "exp": self.exp,
            "variant": self.variant,
            "run_id": self.run_id,
            "op": op,
            "cl": cl,
            "key": key,
            "latency_ms": "" if latency_ms is None else f"{latency_ms:.3f}",
            "outcome": outcome,
            "error_type": error_type or "",
            "expected_seq": "" if expected_seq is None else expected_seq,
            "observed_seq": "" if observed_seq is None else observed_seq,
            "stale": "" if stale is None else stale,
            "coordinator": coordinator or "",
        }
        with self._lock:
            if self._fh.closed:
                return
            self._writer.writerow(row)
            self._fh.flush()
            self.rows += 1

    def close(self):
        with self._lock:
            if not self._fh.closed:
                self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
