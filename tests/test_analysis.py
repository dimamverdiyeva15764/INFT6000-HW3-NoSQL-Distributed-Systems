"""Unit tests for analysis/ (owner: Habib Hasanov). Synthetic data only; no cluster."""
import csv
import os

import pandas as pd
import pytest

from analysis import common, plots, summarize
from app.results_log import ResultsLog

T0 = pd.Timestamp("2026-11-16T10:00:00Z")


def _ts(s):
    return (T0 + pd.Timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _events(rows):
    ev = pd.DataFrame(rows, columns=["ts_utc", "action", "node", "note"])
    ev["ts"] = pd.to_datetime(ev["ts_utc"], utc=True)
    return ev


def test_fault_intervals_pair_fault_with_recovery_command():
    ev = _events([(_ts(10), "stop", "cass3", ""), (_ts(40), "start", "cass3", ""),
                  (_ts(55), "kill", "cass3", ""), (_ts(90), "start", "cass3", ""),
                  (_ts(500), "kill", "cass2", "other run")])
    iv = common.fault_intervals(ev, T0, T0 + pd.Timedelta(seconds=120))
    assert [(a, n) for _s, _e, n, a in iv] == [("stop", "cass3"), ("kill", "cass3")]


def test_unrecovered_fault_lasts_until_run_end():
    ev = _events([(_ts(10), "partition", "cass3", "")])
    (start, end, _n, _a), = common.fault_intervals(ev, T0, T0 + pd.Timedelta(seconds=60))
    assert end == T0 + pd.Timedelta(seconds=60)


def test_assign_phase_labels():
    iv = [(T0 + pd.Timedelta(seconds=10), T0 + pd.Timedelta(seconds=20), "cass3", "stop"),
          (T0 + pd.Timedelta(seconds=30), T0 + pd.Timedelta(seconds=40), "cass3", "kill")]
    ts = pd.Series([T0 + pd.Timedelta(seconds=s) for s in (5, 15, 25, 35, 45)])
    assert list(common.assign_phase(ts, iv)) == ["before", "fault", "between", "fault", "after"]


# --------------------------------------------------------------------------- synthetic repo
def _probe_csv(root, run_id, fail_from, fail_to):
    path = root / "results/raw/exp3/exp3_availability_ONE-QUORUM-ALL_r1_20261116T1000Z.csv"
    with ResultsLog(str(path), "exp3", "availability", run_id) as log:
        for s in range(60):
            for cl in ("ONE", "QUORUM", "ALL"):
                bad = cl == "ALL" and fail_from <= s < fail_to
                log.log(op="write", cl=cl, key="k", latency_ms=2.0, outcome="unavailable" if bad else "ok",
                        error_type="Unavailable" if bad else "", ts_utc=_ts(s))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs("results/logs", exist_ok=True)
    with open("results/logs/chaos_events.csv", "w") as fh:
        fh.write(f"ts_utc,action,node,note\n{_ts(20)[:19]}Z,kill,cass3,x\n{_ts(40)[:19]}Z,start,cass3,x\n")
    _probe_csv(tmp_path, "exp3-3a-cass3-r1-20261116T100000Z-probe", 20, 45)
    return tmp_path


def test_summarize_refuses_without_data(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert summarize.main(["--quiet"]) == 2
    assert not os.path.exists("results/summary")


def test_summarize_phase_table(repo):
    assert summarize.main(["--quiet"]) == 0
    ph = pd.read_csv("results/summary/availability_phases.csv")
    row = lambda phase, cl: ph[(ph.phase == phase) & (ph.cl == cl)].iloc[0]  # noqa: E731
    assert row("before", "ALL").success_pct == 100.0
    assert row("fault", "ALL").success_pct == 0.0 and row("fault", "QUORUM").success_pct == 100.0
    assert row("after", "ALL").attempted == 20 and row("after", "ALL").ok == 15
    tex = open("docs/report/generated/fault_tables.tex").read()
    assert "tab:fault-phases" in tex
    assert "expfour@" not in open("docs/report/generated/exp46_numbers.tex").read()


def test_exp4_and_exp6_numbers_from_evidence(repo):
    run = "exp4-all-cass3-r1-20261119T100000Z"
    os.makedirs(f"results/logs/exp4/{run}", exist_ok=True)
    rows = [
        {"run_id": run, "step": "4b-after-restart", "check": "preview-repair", "verdict": "met",
         "in_sync": "0", "ranges": "48", "bytes": "2048"},
        {"run_id": run, "step": "4b-one-before", "check": "read-sample-ONE", "verdict": "met", "checked": "50",
         "stale": "50", "note": "set A; coordinator cass3; served_by_target 50; stale_on_target 50; repair_traces 0"},
        {"run_id": run, "step": "4c-after-repair", "check": "preview-repair", "verdict": "met", "in_sync": "1",
         "ranges": "0", "bytes": "0"},
        {"run_id": run, "step": "4c-final", "check": "acked-ALL", "verdict": "PASS", "checked": "10000",
         "missing": "0", "wrong": "0"},
        {"run_id": run, "step": "4c-final", "check": "convergence", "verdict": "PASS"},
    ]
    with open("results/logs/exp4/convergence_checks.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=summarize_fields())
        w.writeheader()
        for r in rows:
            w.writerow(r)
    with open(f"results/logs/exp4/{run}/measurements.csv", "w") as fh:
        fh.write("variant,metric,value,unit\n4a,hint_bytes_before_restart,524288,bytes\n4c,repair_seconds,3.2,s\n")
    os.makedirs("results/logs/exp6", exist_ok=True)
    with open("results/logs/exp6/races.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["run_id", "variant", "handles", "clients", "ops_ok", "ops_failed",
                                           "exactly_one", "timeout_winner", "no_winner", "violations",
                                           "acked_overwritten", "verdict"])
        w.writeheader()
        w.writerow({"run_id": "r", "variant": "race", "handles": 20, "clients": 10, "ops_ok": 200,
                    "ops_failed": 0, "exactly_one": 20, "timeout_winner": 0, "no_winner": 0, "violations": 0,
                    "acked_overwritten": 0, "verdict": "SAFE: one winner per handle"})
    lat = "results/raw/exp6/exp6_latency_SERIAL-QUORUM_r1_20261119T1000Z.csv"
    with ResultsLog(lat, "exp6", "latency", "lat-run") as log:
        for i in range(40):
            log.log(op="lwt", cl="SERIAL", key=f"l{i}", latency_ms=8.0 + i % 3, outcome="ok", ts_utc=_ts(i))
            log.log(op="write", cl="QUORUM", key=f"p{i}", latency_ms=2.0, outcome="ok", ts_utc=_ts(i))
    assert summarize.main(["--quiet"]) == 0
    tex = open("docs/report/generated/exp46_numbers.tex").read()
    for needle in ("expfour@4b-preview-ranges\\endcsname{48}", "expfour@4b-before-target-stale\\endcsname{50}",
                   "expfour@4c-preview\\endcsname{in sync}", "expfour@4c-verdict\\endcsname{PASS}",
                   "expfour@4a-hint-kib\\endcsname{512.0}", "expsix@race-exactlyone\\endcsname{20}",
                   "expsix@lat-ratio\\endcsname{4.5}"):
        assert needle in tex, needle
    assert plots.plot_lwt_latency(common.load_raw(verbose=False), "results/figures")


def summarize_fields():
    from recovery.verify_convergence import CHECK_FIELDS
    return CHECK_FIELDS


def test_plots_from_synthetic_repo(repo):
    assert plots.main([]) == 0
    assert os.path.exists("results/figures/fault_availability_timeline.png")


def test_hints_drain_plot(tmp_path):
    t = tmp_path / "4a_hints_timeline.csv"
    t.write_text("t_s,ts_utc,peer_view_un,cass1_files,cass1_bytes,cass2_files,cass2_bytes\n"
                 "0,x,0,2,40960,2,40960\n5,x,1,2,40960,1,20480\n9,x,1,0,0,0,0\n")
    assert plots.plot_hints_drain(str(t), str(tmp_path / "fig"))
