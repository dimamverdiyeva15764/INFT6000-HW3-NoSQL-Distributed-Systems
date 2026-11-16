"""Unit tests for the data-access layer, the results CSV, the workload runner and the
Exp 2 summary. They need the Python dependencies (client/requirements.txt) but NOT a
running Cassandra cluster:

    docker compose run --rm client python -m pytest -q          (make test)
    python -m pytest -q                                         (local venv)
"""
import csv
import os
import re
import threading
from types import SimpleNamespace

import pytest
from cassandra import (ConsistencyLevel, OperationTimedOut, ReadFailure, ReadTimeout, Unavailable,
                       WriteFailure, WriteTimeout)
from cassandra.cluster import NoHostAvailable

from app import db
from app.db import OUTCOMES, classify_error, cl_name, cl_value, stmt, timed_execute
from app.results_log import FIELDS, ResultsLog, default_path, result_filename, utc_now_iso
from workload import runner

CONTRACT_FIELDS = ["ts_utc", "exp", "variant", "run_id", "op", "cl", "key", "latency_ms", "outcome",
                   "error_type", "expected_seq", "observed_seq", "stale", "coordinator"]
ISO_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")


# --------------------------------------------------------------------------- fakes
class FakeFuture:
    def __init__(self, rows=None, exc=None, host="172.28.0.12"):
        self._rows, self._exc = rows, exc
        self.coordinator_host = SimpleNamespace(address=host)

    def result(self):
        if self._exc is not None:
            raise self._exc
        return self._rows


class FakePrepared:
    def __init__(self, cql):
        self.query_string = cql
        self.consistency_level = None
        self.serial_consistency_level = None


class FakeSession:
    """Answers the runner's probe statements from a scripted list of read values."""

    def __init__(self, read_values=None, fail_with=None):
        self.prepared = 0
        self.read_values = list(read_values or [])
        self.fail_with = fail_with
        self.calls = []

    def prepare(self, cql):
        self.prepared += 1
        return FakePrepared(cql)

    def execute_async(self, statement, params=None, trace=False, execution_profile=None):
        self.calls.append((statement.query_string, params, execution_profile))
        if self.fail_with is not None:
            return FakeFuture(exc=self.fail_with)
        if statement.query_string.startswith("SELECT last_seq"):
            value = self.read_values.pop(0)
            return FakeFuture(rows=[] if value is None else [SimpleNamespace(last_seq=value)])
        return FakeFuture(rows=[])


# --------------------------------------------------------------------------- classify_error
@pytest.mark.parametrize("exc, expected", [
    (None, "ok"),
    (Unavailable("not enough replicas alive"), "unavailable"),
    (WriteTimeout("write timed out"), "write_timeout"),
    (ReadTimeout("read timed out"), "read_timeout"),
    (WriteFailure("write failed"), "write_failure"),
    (ReadFailure("read failed"), "read_failure"),
    (NoHostAvailable("no host", {}), "no_host"),
    (OperationTimedOut(), "client_timeout"),
    (ValueError("anything else"), "other"),
])
def test_classify_error(exc, expected):
    assert classify_error(exc) == expected
    assert classify_error(exc) in OUTCOMES


def test_consistency_level_names():
    for name in ("ONE", "QUORUM", "ALL", "SERIAL", "LOCAL_QUORUM"):
        assert cl_name(cl_value(name)) == name
    assert cl_value("quorum") == ConsistencyLevel.QUORUM
    with pytest.raises(ValueError):
        cl_value("MAJORITY")


# --------------------------------------------------------------------------- stmt()
def test_stmt_caches_one_statement_per_consistency_level():
    session = FakeSession()
    cql = "SELECT * FROM messages WHERE room = ?"
    a = stmt(cql, "ONE", session=session)
    b = stmt(cql, "ONE", session=session)
    c = stmt(cql, "ALL", session=session)
    assert a is b and a is not c
    assert session.prepared == 2
    assert a.consistency_level == ConsistencyLevel.ONE
    assert c.consistency_level == ConsistencyLevel.ALL
    lwt = stmt("INSERT INTO usernames (handle, owner) VALUES (?, ?) IF NOT EXISTS", "QUORUM", "SERIAL",
               session=session)
    assert lwt.serial_consistency_level == ConsistencyLevel.SERIAL


def test_stmt_needs_a_session(monkeypatch):
    monkeypatch.setattr(db, "_default_session", None)
    with pytest.raises(RuntimeError):
        stmt("SELECT 1", "ONE")


def test_timed_execute_never_raises_and_classifies():
    ok = timed_execute(FakeSession(), FakePrepared("INSERT"), [])
    assert ok.outcome == "ok" and ok.error_type == "" and ok.coordinator == "172.28.0.12"
    bad = timed_execute(FakeSession(fail_with=Unavailable("x")), FakePrepared("INSERT"), [])
    assert bad.outcome == "unavailable" and bad.error_type == "Unavailable" and bad.latency_ms >= 0


# --------------------------------------------------------------------------- results CSV
def test_csv_header_matches_contract():
    assert FIELDS == CONTRACT_FIELDS


def test_results_log_is_schema_valid_and_thread_safe(tmp_path):
    path = tmp_path / "exp2_write_ONE_r1_20261116T1000Z.csv"
    log = ResultsLog(str(path), "exp2", "write", "run-1")

    def work(t):
        for i in range(250):
            log.log(op="write", cl="ONE", key=f"room-{t}", latency_ms=1.0 + i / 1000, outcome="ok",
                    coordinator="172.28.0.11")

    threads = [threading.Thread(target=work, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # rows are flushed immediately: readable before close()
    with open(path, newline="") as fh:
        assert sum(1 for _ in fh) == 1 + 8 * 250
    log.close()
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == CONTRACT_FIELDS
        rows = list(reader)
    assert len(rows) == 2000
    for r in rows:
        assert ISO_RE.match(r["ts_utc"])
        assert r["outcome"] in OUTCOMES
        float(r["latency_ms"])
        assert r["exp"] == "exp2" and r["variant"] == "write" and r["run_id"] == "run-1"


def test_results_log_never_overwrites(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("previous run")
    with pytest.raises(FileExistsError):
        ResultsLog(str(path), "exp2", "write", "r")
    assert path.read_text() == "previous run"


def test_file_naming_convention(tmp_path):
    name = result_filename("exp2", "probe", "ONE-QUORUM", 3)
    assert re.match(r"^exp2_probe_ONE-QUORUM_r3_\d{8}T\d{4}Z\.csv$", name)
    with pytest.raises(ValueError):
        result_filename("exp2", "bad_variant", "ONE", 1)
    first = default_path("exp2", "write", "ONE", 1, root=str(tmp_path))
    os.makedirs(os.path.dirname(first))
    open(first, "w").close()
    second = default_path("exp2", "write", "ONE", 1, root=str(tmp_path))
    assert second != first and second.endswith("-2.csv")
    assert ISO_RE.match(utc_now_iso())


# --------------------------------------------------------------------------- runner
def test_percentile():
    assert runner.percentile([], 50) is None
    assert runner.percentile([5], 99) == 5
    assert runner.percentile([1, 2, 3, 4], 50) == 2.5
    assert runner.percentile(list(range(101)), 99) == 99


def test_open_loop_schedule_and_budget():
    s = runner.OpenLoopSchedule(rate=200, start=100.0)
    slots = [s.next_slot() for _ in range(3)]
    assert slots == pytest.approx([100.0, 100.005, 100.010])
    b = runner.Budget(2)
    assert [b.claim(), b.claim(), b.claim()] == [True, True, False]
    assert runner.Budget(None).claim()


def _args(argv):
    args = runner.build_parser().parse_args(argv)
    return args, runner.resolve_args(args)


def test_runner_arguments_used_by_experiment_scripts():
    # exactly what scripts/run_exp1.sh passes (Person 1's baseline step)
    args, label = _args(["--mode", "mixed", "--cl", "QUORUM", "--rate", "200", "--duration", "60",
                         "--exp", "exp1", "--variant", "baseline", "--run-id", "exp1-x", "--out", "x.csv"])
    assert (args.write_cl, args.read_cl, label, args.rate) == ("QUORUM", "QUORUM", "QUORUM", 200)
    args, label = _args(["--mode", "probe", "--write-cl", "ONE", "--read-cl", "ALL", "--probes", "2000"])
    assert label == "ONE-ALL" and args.max and args.duration == 0
    args, label = _args(["--mode", "read", "--cl", "ALL"])
    assert label == "ALL" and args.rate == 200.0 and args.variant == "read"


def test_chat_cli_arguments_used_by_experiment_scripts():
    from app import chat
    p = chat.build_parser()
    a = p.parse_args(["--trace", "read", "--room", "general", "--limit", "5", "--cl", "ONE"])
    assert a.trace and a.command == "read" and a.cl == "ONE"
    a = p.parse_args(["post", "--room", "smoke", "--author", "smoke", "--text", "t", "--cl", "quorum"])
    assert a.cl == "QUORUM"
    with pytest.raises(SystemExit):
        p.parse_args(["read", "--room", "r", "--cl", "MAJORITY"])


@pytest.mark.parametrize("read_values, expected_stale", [
    ([1, 2, 3], [0, 0, 0]),        # every read sees the value just written
    ([1, 1, None], [0, 1, 1]),     # older value, then missing row -> stale
])
def test_probe_marks_stale_reads(tmp_path, read_values, expected_stale):
    args, _ = _args(["--mode", "probe", "--write-cl", "ONE", "--read-cl", "ONE", "--probes", "3",
                     "--hosts", "172.28.0.11,172.28.0.12,172.28.0.13", "--exp", "exp2"])
    session = FakeSession(read_values=read_values)
    db._stmt_cache.clear()
    with ResultsLog(str(tmp_path / "p.csv"), "exp2", "probe", "r") as log:
        r = runner.Runner(args, session, log)
        state = {"key": "probe-k", "seq": 0, "i": 0}
        for _ in range(3):
            r.do_probe(0, state, measured=True)
    with open(tmp_path / "p.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    reads = [row for row in rows if row["op"] == "read"]
    assert [int(row["stale"]) for row in reads] == expected_stale
    assert [int(row["expected_seq"]) for row in reads] == [1, 2, 3]
    # the read is always sent through a different coordinator than the write
    profiles = [c[2] for c in session.calls]
    for w, rd in zip(profiles[0::2], profiles[1::2]):
        assert w != rd


# --------------------------------------------------------------------------- exp2 summary
def test_summary_refuses_to_run_without_data(tmp_path):
    pytest.importorskip("pandas")
    from workload import exp2_summary
    rc = exp2_summary.main(["--raw", str(tmp_path / "none" / "*.csv"),
                            "--summary-dir", str(tmp_path / "s"), "--figure-dir", str(tmp_path / "f"),
                            "--tex-dir", str(tmp_path / "t")])
    assert rc == 1
    assert not (tmp_path / "s").exists() and not (tmp_path / "t").exists()


def test_summary_pipeline_on_tiny_input(tmp_path):
    """Tiny hand-made input, only to check the pipeline end to end (never committed)."""
    pytest.importorskip("pandas")
    pytest.importorskip("matplotlib")
    from workload import exp2_summary
    raw = tmp_path / "raw"
    raw.mkdir()

    def write(variant, cl, rows):
        with ResultsLog(str(raw / f"exp2_{variant}_{cl}_r1_20261116T1000Z.csv"), "exp2", variant, "t") as log:
            for i, row in enumerate(rows):
                log.log(ts_utc=f"2026-11-16T10:00:{i:02d}.000000Z", **row)

    for cl, base in (("ONE", 1.0), ("QUORUM", 1.5), ("ALL", 2.0)):
        for mode in ("write", "read", "mixed"):
            op = "read" if mode == "read" else "write"
            write(mode, cl, [dict(op=op, cl=cl, key="room-0001", latency_ms=base + i / 10, outcome="ok")
                             for i in range(20)])
        write("max", cl, [dict(op="write", cl=cl, key="k", latency_ms=base, outcome="ok") for _ in range(20)])
    write("probe", "ONE-ONE", [dict(op="read", cl="ONE", key="p", latency_ms=1, outcome="ok",
                                    expected_seq=i, observed_seq=i - (i % 5 == 0), stale=int(i % 5 == 0))
                               for i in range(1, 21)])
    rc = exp2_summary.main(["--raw", str(raw / "*.csv"), "--exp1", str(tmp_path / "no-exp1*.csv"),
                            "--summary-dir", str(tmp_path / "s"), "--figure-dir", str(tmp_path / "f"),
                            "--tex-dir", str(tmp_path / "t"), "--target-rate", "1"])
    assert rc == 0
    for name in ("exp2_grid.csv", "exp2_probe.csv", "exp2_summary.md"):
        assert (tmp_path / "s" / name).exists()
    for name in ("exp2_latency_percentiles.png", "exp2_staleness.png", "exp2_saturation.png"):
        assert (tmp_path / "f" / name).stat().st_size > 10_000
    numbers = (tmp_path / "t" / "exp2_numbers.tex").read_text()
    assert "exptwo@write-ONE-p50" in numbers and "exptwo@probe-ONE-ONE-stale" in numbers
    assert "rose monotonically" in numbers
