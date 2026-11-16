from types import SimpleNamespace

from chaos import availability_probe


class RecordingLog:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)


def test_probe_records_reads_and_writes_for_each_consistency_level(monkeypatch):
    last_values = {}
    monkeypatch.setattr(
        availability_probe,
        "stmt",
        lambda cql, cl, session=None: (cql, cl),
    )

    def execute(_session, statement, params):
        cql, cl = statement
        if cql.startswith("UPDATE"):
            last_values[params[-1]] = params[0]
            rows = []
        else:
            rows = [SimpleNamespace(last_seq=last_values[params[0]])]
        return SimpleNamespace(
            outcome="ok",
            error_type="",
            latency_ms=0.1,
            coordinator=f"coordinator-{cl}",
            rows=rows,
        )

    monkeypatch.setattr(availability_probe, "timed_execute", execute)
    log = RecordingLog()
    counts = availability_probe.run_probe(
        session=object(),
        log=log,
        run_id="probe-test",
        duration=0.02,
        interval=0.002,
        room_prefix="test-room",
    )

    assert set(counts) == {"ONE", "QUORUM", "ALL"}
    for cl in counts:
        rows = [row for row in log.rows if row["cl"] == cl]
        assert {row["op"] for row in rows} == {"read", "write"}
        assert all(row["outcome"] == "ok" for row in rows)
        assert all(row["stale"] == 0 for row in rows if row["op"] == "read")
