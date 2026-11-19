"""Unit tests for the recovery tooling (Exp 4 and Exp 6). Owner: Habib Hasanov.

No running cluster is needed: CQL calls go to fake sessions that implement just enough
of Cassandra's semantics (LWT compare-and-set, last-write-wins, per-replica copies).
"""
import csv
import threading
from collections import namedtuple
from types import SimpleNamespace

import pytest

from app import db
from app.results_log import ResultsLog
from recovery import lwt_demo
from recovery import verify_convergence as vc

LwtRow = namedtuple("Row", ["applied", "handle", "owner"])
OwnerRow = namedtuple("Row", ["owner"])
SeqRow = namedtuple("Row", ["last_seq"])


# --------------------------------------------------------------------------- fakes
class FakeFuture:
    def __init__(self, rows=None, exc=None, host="172.28.0.11", events=None):
        self._rows, self._exc = rows, exc
        self.coordinator_host = SimpleNamespace(address=host)
        self._events = events or []

    def result(self):
        if self._exc is not None:
            raise self._exc
        return self._rows

    def get_query_trace(self, max_wait=None, query_cl=None):   # same signature as the driver
        return SimpleNamespace(events=self._events, coordinator="172.28.0.13", duration=None)


class FakePrepared:
    def __init__(self, cql):
        self.query_string = cql
        self.consistency_level = None
        self.serial_consistency_level = None


class FakeCluster:
    """usernames table with real compare-and-set semantics, guarded by a lock."""

    def __init__(self, fail=None):
        self.usernames = {}
        self.lock = threading.Lock()
        self.fail = fail

    def prepare(self, cql):
        return FakePrepared(cql)

    def execute_async(self, statement, params=None, trace=False, execution_profile=None):
        cql = statement.query_string
        if self.fail is not None and not cql.startswith("SELECT"):
            return FakeFuture(exc=self.fail)
        with self.lock:
            if cql.startswith("INSERT") and "IF NOT EXISTS" in cql:
                handle, owner = params
                if handle in self.usernames:
                    return FakeFuture(rows=[LwtRow(False, handle, self.usernames[handle])])
                self.usernames[handle] = owner
                return FakeFuture(rows=[LwtRow(True, None, None)])
            if cql.startswith("INSERT"):
                self.usernames[params[0]] = params[1]       # last write wins
                return FakeFuture(rows=[])
            owner = self.usernames.get(params[0])
            return FakeFuture(rows=[] if owner is None else [OwnerRow(owner)])


class ReplicaSession:
    """room_state with a stale replica: reads pinned to cass3 see cass3's copy at ONE."""

    def __init__(self, stale_keys=()):
        self.fresh = {}
        self.stale_keys = set(stale_keys)

    def prepare(self, cql):
        return FakePrepared(cql)

    def execute_async(self, statement, params=None, trace=False, execution_profile=None):
        cql = statement.query_string
        if cql.startswith("UPDATE"):
            seq, _run, key = params
            self.fresh[key] = seq
            return FakeFuture(rows=[])
        key = params[0]
        on_cass3 = execution_profile == db.coordinator_profile("cass3")
        one = statement.consistency_level == db.cl_value("ONE")
        events = [SimpleNamespace(source="172.28.0.13", description="Executing single-partition query on room_state")]
        if on_cass3 and one and key in self.stale_keys:
            return FakeFuture(rows=[], host="172.28.0.13", events=events)
        if not one and key in self.stale_keys:
            events.append(SimpleNamespace(source="172.28.0.13", description="Digest mismatch: key " + key))
            self.stale_keys.discard(key)                     # blocking read repair
        value = self.fresh.get(key)
        return FakeFuture(rows=[] if value is None else [SeqRow(value)], host="172.28.0.13", events=events)


@pytest.fixture(autouse=True)
def _clear_stmt_cache():
    db._stmt_cache.clear()
    yield
    db._stmt_cache.clear()


# --------------------------------------------------------------------------- preview parsing
IN_SYNC = """[2026-11-19 10:00:01,000] Starting repair command #1 (...), repairing keyspace chat
[2026-11-19 10:00:02,100] Repair preview completed successfully; Previewed data was in sync
"""
DIVERGENT = """[2026-11-19 10:00:01,000] Starting repair command #2, repairing keyspace chat with repair options (...)
Total estimated streaming: 48 ranges, 6 sstables, 1.240MiB bytes
    chat.room_state - 48 ranges, 6 sstables, 1.240MiB bytes
        /172.28.0.11:7000 -> /172.28.0.13:7000: 48 ranges, 3 sstables, 634.881KiB bytes
        /172.28.0.12:7000 -> /172.28.0.13:7000: 48 ranges, 3 sstables, 634.881KiB bytes
"""


def test_preview_in_sync():
    res = vc.parse_preview(IN_SYNC)
    assert res["in_sync"] is True and res["ranges"] == 0 and res["bytes"] == 0


def test_preview_divergent_totals_and_pairs():
    res = vc.parse_preview(DIVERGENT)
    assert res["in_sync"] is False
    assert res["ranges"] == 48 and res["sstables"] == 6
    assert res["bytes"] == round(1.240 * 1024 ** 2)
    assert {(p["src"], p["dst"]) for p in res["pairs"]} == {("172.28.0.11", "172.28.0.13"),
                                                           ("172.28.0.12", "172.28.0.13")}


def test_preview_unknown_output_is_not_reported_as_in_sync():
    assert vc.parse_preview("error: nodetool failed: Connection refused")["in_sync"] is None


@pytest.mark.parametrize("text,expected", [("430B", 430), ("1.000KiB", 1024), ("2 MiB", 2 * 1024 ** 2),
                                           ("977", 977), ("abc", None)])
def test_parse_size(text, expected):
    assert vc.parse_size(text) == expected


def test_preview_command_from_saved_file_logs_verdict(tmp_path, monkeypatch, capsys):
    saved = tmp_path / "out.txt"
    saved.write_text(DIVERGENT)
    log = tmp_path / "checks.csv"
    monkeypatch.setattr(vc, "CHECK_LOG", str(log))
    monkeypatch.setattr(vc.append_check, "__defaults__", (str(log),))
    rc = vc.main(["preview", "--from-file", str(saved), "--label", "4b-after-restart", "--expect", "divergent"])
    assert rc == 0
    assert "DIVERGENT - 48 range(s)" in capsys.readouterr().out
    rows = list(csv.DictReader(log.open()))
    assert rows[0]["verdict"] == "met" and rows[0]["in_sync"] == "0" and rows[0]["ranges"] == "48"


def test_preview_expectation_not_met_exits_1(tmp_path, monkeypatch):
    saved = tmp_path / "out.txt"
    saved.write_text(DIVERGENT)
    monkeypatch.setattr(vc.append_check, "__defaults__", (str(tmp_path / "c.csv"),))
    assert vc.main(["preview", "--from-file", str(saved), "--expect", "in-sync"]) == 1


# --------------------------------------------------------------------------- acknowledged writes
def _write_csv(tmp_path, rows):
    path = tmp_path / "exp4_4b-write_QUORUM_r1_20261119T1000Z.csv"
    with ResultsLog(str(path), "exp4", "4b-write", "t") as log:
        for key, seq, outcome in rows:
            log.log(op="write", cl="QUORUM", key=key, latency_ms=1.0, outcome=outcome, expected_seq=seq)
    return path


def test_load_acked_keeps_only_acknowledged(tmp_path):
    path = _write_csv(tmp_path, [("k1", 1, "ok"), ("k2", 2, "write_timeout"), ("k3", 3, "ok")])
    assert vc.load_acked([str(path)]) == [("k1", 1), ("k3", 3)]


def test_samples_are_deterministic_and_disjoint():
    acked = [(f"k{i}", i) for i in range(200)]
    a1, a2 = vc.choose_sample(acked, 50, "A"), vc.choose_sample(acked, 50, "A")
    b = vc.choose_sample(acked, 50, "B")
    assert a1 == a2 and len(a1) == 50 and not set(a1) & set(b)


def test_write_then_acked_check_passes(tmp_path):
    session = ReplicaSession()
    out = tmp_path / "w.csv"
    with ResultsLog(str(out), "exp4", "4a-write", "run") as log:
        ok = vc.do_write(session, log, [(f"k{i}", i + 1) for i in range(30)], "QUORUM", "run", concurrency=4)
    assert ok == 30
    acked = vc.load_acked([str(out)])
    with ResultsLog(str(tmp_path / "a.csv"), "exp4", "final-acked", "run") as log:
        counts = vc.do_acked(session, log, acked, concurrency=4)
    assert vc.acked_verdict(counts, len(acked)) == "PASS"


def test_acked_check_fails_on_lost_write(tmp_path):
    session = ReplicaSession()
    session.fresh = {"k1": 1}
    with ResultsLog(str(tmp_path / "a.csv"), "exp4", "final-acked", "run") as log:
        counts = vc.do_acked(session, log, [("k1", 1), ("k2", 2)], concurrency=2)
    assert counts["missing"] == 1
    assert vc.acked_verdict(counts, 2) == "FAIL"


def test_read_repair_story(tmp_path):
    """4b in miniature: stale at ONE on cass3, ALL repairs only the keys it reads."""
    keys = [(f"k{i}", i + 1) for i in range(10)]
    session = ReplicaSession(stale_keys=[k for k, _ in keys])
    session.fresh = dict(keys)

    def sample(step, cl, subset):
        with ResultsLog(str(tmp_path / f"{step}.csv"), "exp4", step, "run") as log:
            return vc.summarize_sample(vc.do_read_sample(session, log, subset, cl, "cass3"))

    set_a, set_b = keys[:5], keys[5:]
    before = sample("one-before", "ONE", set_a)
    assert before["stale_on_target"] == 5 and before["served_by_target"] == 5
    repaired = sample("all", "ALL", set_a)
    assert repaired["stale"] == 0 and repaired["with_repair_events"] == 5
    assert sample("one-after", "ONE", set_a)["stale"] == 0
    assert sample("control", "ONE", set_b)["stale"] == 5     # never read at ALL -> still stale


# --------------------------------------------------------------------------- LWT classification
def _att(owner, outcome="ok", applied=None, returned=None):
    return {"owner": owner, "outcome": outcome, "applied": applied, "returned_owner": returned}


def test_classify_exactly_one_winner():
    atts = [_att("c0", applied=True)] + [_att(f"c{i}", applied=False, returned="c0") for i in range(1, 5)]
    assert lwt_demo.classify_handle(atts, "c0")["category"] == "exactly-one"


def test_classify_two_winners_is_violation():
    atts = [_att("c0", applied=True), _att("c1", applied=True)]
    assert lwt_demo.classify_handle(atts, "c1")["category"] == "violation"


def test_classify_timed_out_cas_that_committed():
    atts = [_att("c0", outcome="write_timeout"), _att("c1", applied=False, returned="c0")]
    assert lwt_demo.classify_handle(atts, "c0")["category"] == "timeout-winner"


def test_classify_unavailable_no_winner():
    atts = [_att(f"c{i}", outcome="unavailable") for i in range(3)]
    assert lwt_demo.classify_handle(atts, None)["category"] == "no-winner"


def test_classify_plain_counts_overwritten_acks():
    atts = [_att(f"c{i}", applied=True) for i in range(10)]
    v = lwt_demo.classify_handle(atts, "c7", lwt=False)
    assert v["category"] == "last-write-wins" and v["acked_overwritten"] == 9


def test_row_applied_variants():
    assert lwt_demo.row_applied(LwtRow(True, None, None)) is True
    assert lwt_demo.row_applied({"[applied]": False}) is False
    assert lwt_demo.row_applied(None) is None


# --------------------------------------------------------------------------- LWT races (fake CAS)
def test_lwt_race_has_exactly_one_winner_per_handle(tmp_path):
    cluster = FakeCluster()
    with ResultsLog(str(tmp_path / "r.csv"), "exp6", "race", "run") as log:
        per_handle, attempts, read_failed = lwt_demo.run_race(cluster, log, ["h0", "h1", "h2"], 8, lwt=True)
    s = lwt_demo.summarize_race(per_handle, attempts, True, read_failed)
    assert s["exactly_one"] == 3 and s["violations"] == 0
    assert s["verdict"].startswith("SAFE: one winner")
    for h in per_handle:
        rows = [a for a in attempts if a["handle"] == h["handle"]]
        assert sum(1 for a in rows if a["applied"]) == 1
        assert {a["returned_owner"] for a in rows if not a["applied"]} == {h["winner"]}


def test_plain_race_acknowledges_everyone_and_keeps_one(tmp_path):
    cluster = FakeCluster()
    with ResultsLog(str(tmp_path / "p.csv"), "exp6", "plain", "run") as log:
        per_handle, attempts, rf = lwt_demo.run_race(cluster, log, ["h0", "h1"], 6, lwt=False)
    s = lwt_demo.summarize_race(per_handle, attempts, False, rf)
    assert s["ops_ok"] == 12 and s["acked_overwritten"] == 10
    assert s["verdict"].startswith("LWW")


def test_race_with_unavailable_cluster_is_safe(tmp_path):
    from cassandra import Unavailable
    cluster = FakeCluster(fail=Unavailable("Cannot achieve consistency level SERIAL"))
    with ResultsLog(str(tmp_path / "u.csv"), "exp6", "race-2down", "run") as log:
        per_handle, attempts, rf = lwt_demo.run_race(cluster, log, ["h0"], 4, lwt=True)
    s = lwt_demo.summarize_race(per_handle, attempts, True, rf)
    assert s["no_winner"] == 1 and s["violations"] == 0 and "unavailable" in s["verdict"]
    rows = list(csv.DictReader(open(tmp_path / "u.csv")))
    assert {r["outcome"] for r in rows} == {"unavailable"} and {r["op"] for r in rows} == {"lwt"}


def test_trace_call_matches_real_driver_signature():
    """The driver's ResponseFuture.get_query_trace takes max_wait (not max_wait_sec)."""
    import inspect
    from cassandra.cluster import ResponseFuture
    assert list(inspect.signature(ResponseFuture.get_query_trace).parameters)[1] == "max_wait"
    import recovery.lwt_demo as ld
    import recovery.verify_convergence as v
    for mod in (ld, v):
        assert "max_wait_sec" not in inspect.getsource(mod)


def test_failed_reads_are_not_counted_as_fresh(tmp_path, monkeypatch):
    from cassandra import Unavailable
    session = ReplicaSession()
    session.fresh = {"k1": 1}
    session.execute_async = lambda *a, **k: FakeFuture(exc=Unavailable("down"))
    with ResultsLog(str(tmp_path / "f.csv"), "exp4", "x", "run") as log:
        s = vc.summarize_sample(vc.do_read_sample(session, log, [("k1", 1)], "ONE", "cass3"))
    assert s["ok"] == 0 and s["failed"] == 1 and s["errors"] == {"unavailable": 1}
