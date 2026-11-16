from datetime import timezone

import pytest

from chaos import detect_down


@pytest.mark.parametrize(
    "line,node,transition,expected",
    [
        ("INFO Node /172.28.0.13 is now DOWN", "cass3", "down", True),
        ("INFO Node /172.28.0.13 is now UP", "cass3", "up", True),
        ("INFO Node /172.28.0.12 is now DOWN", "cass3", "down", False),
        ("INFO Node /172.28.0.13 is now DOWN", "cass3", "up", False),
    ],
)
def test_matching_detection_requires_target_and_transition(line, node, transition, expected):
    assert detect_down.matching_detection(line, node, transition) is expected


def test_parse_time_normalizes_docker_utc_timestamp():
    parsed = detect_down.parse_time("2026-11-16T10:15:03.123456Z")
    assert parsed.tzinfo == timezone.utc
    assert parsed.microsecond == 123456


def test_latest_event_selects_latest_matching_node_action(tmp_path, monkeypatch):
    event_file = tmp_path / "events.csv"
    event_file.write_text(
        "ts_utc,action,node,note\n"
        "2026-11-16T10:00:00Z,kill,cass3,first\n"
        "2026-11-16T10:01:00Z,kill,cass2,other node\n"
        "2026-11-16T10:02:00Z,start,cass3,restarted\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(detect_down, "EVENT_FILE", event_file)
    assert detect_down.latest_event("cass3", "down") == (
        "2026-11-16T10:00:00Z",
        "kill",
    )
