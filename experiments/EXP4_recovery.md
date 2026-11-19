# Experiment 4 — Recovery and Data Reconciliation

Owner: Habib Hasanov (uses Person 3's chaos scripts and Person 2's data-access layer).

## Goal

Show, one mechanism at a time, how a replica that missed writes is brought back in line, and
prove that no write acknowledged at QUORUM is ever lost:

| Variant | Mechanism isolated | How it is isolated |
|---|---|---|
| 4a | hinted handoff | handoff enabled; kill cass3, write, restart within `max_hint_window` |
| 4b | read repair | `nodetool disablehandoff` on cass1 and cass2, so no hints exist |
| 4c | anti-entropy (Merkle-tree) repair | `nodetool repair --full chat` after 4b |

## Prerequisites

```bash
make up && make schema && make smoke
make verify          # healthy cluster: preview repair must print IN SYNC -> CONVERGENCE PASS
```

Host needs Docker and Python 3 (standard library only), like Exp 3/5.

## Run

```bash
make exp4                    # baseline + 4a + 4b + 4c (~5 min), REP=1
make exp4 REP=2              # repetitions
make exp4 VARIANT=4a         # one variant only (4c verifies the newest 4b writes)
bash recovery/hints_vs_repair.sh --help
make figures                 # tables, LaTeX numbers, exp4_hints_drain.png
```

## Procedure (what the script does)

0. **Baseline** – records hint/repair settings (`system_views.settings`), runs
   `nodetool repair --full chat` so the cluster starts converged, checks that the preview
   repair reports *in sync*, truncates old hints, enables handoff everywhere.
1. **4a** – `chaos/kill_node.sh cass3`, wait until both peers report it `DN`, write 5,000
   keys at QUORUM (`verify_convergence write`, one partition per key). Wait 15 s (hints are
   flushed to files every 10 s), capture `nodetool listpendinghints` + hint files on cass1/cass2
   **before** the restart. `docker start cass3` and sample the hint files every second until
   cass3 is `UN` and the files are gone (`4a_hints_timeline.csv`). Save hint log lines, run the
   preview repair (expect *in sync*), read 50 sample keys at ONE through cass3 with tracing
   (expect 0 stale), then `full` check (preview + every key at ALL).
2. **4b** – disable handoff on cass1/cass2, kill cass3, write 5,000 keys, check that no hints
   exist, restart cass3. Preview repair (expect *divergent*). Sample **set A** (50 keys): read at
   ONE through cass3 (expect stale), read at ALL through cass3 with tracing (digest mismatch →
   blocking read repair), read at ONE again (expect fresh). Control **set B** (50 different
   keys, never read at ALL): read at ONE (expect still stale). Preview again (still divergent).
3. **4c** – `nodetool repair --full chat` on cass3 (timed), preview (expect *in sync*), set B at
   ONE (expect fresh), re-enable handoff, final `full` check over all 4a and 4b keys → **PASS**.

Handoff is re-enabled and cass3 restarted by an exit trap even if the script fails.

## Expected results

- 4a: hints accumulate while cass3 is down and drain within seconds of it becoming `UN`;
  the preview repair reports *in sync* without any manual repair.
- 4b: without hints the restarted replica is stale; only the keys read at ALL are repaired,
  the control set stays stale and the preview still reports divergence.
- 4c: Merkle-tree repair reconciles everything; the convergence check passes.
- In every variant, no write acknowledged at QUORUM is lost.

If an observation differs, the generated report text says so (`NOTE: ...`); report what was
observed and explain it.

## Measurements and evidence

| Measurement | Where |
|---|---|
| acknowledged writes (per key, latency, outcome) | `results/raw/exp4/exp4_4a-write_QUORUM_r<rep>_<stamp>.csv`, `..._4b-write_...` |
| sample reads (stale, coordinator) | `results/raw/exp4/exp4_<step>_<CL>_r<rep>_<stamp>.csv` |
| which replica served each read, trace excerpts | `results/logs/exp4/<run>/<step>_reads.csv` |
| pending hints before restart / after drain | `results/logs/exp4/<run>/4a_03_*.txt`, `4a_05_*.txt` |
| hint drain timeline | `results/logs/exp4/<run>/4a_hints_timeline.csv` |
| hint dispatch log lines | `results/logs/exp4/<run>/4a_04_hint_dispatch_log.txt` |
| preview repair raw output + verdicts | `results/logs/exp4/<run>/<label>_preview.txt` |
| repair duration, drain times | `results/logs/exp4/<run>/measurements.csv` |
| every verdict (append-only) | `results/logs/exp4/convergence_checks.csv` |
| final PASS/FAIL | `results/logs/exp4/<run>/4c_99_verdict.txt` |

Screenshots for the report/slides: `results/screenshots/exp4/` (listpendinghints before
restart, the 4b ONE-before/ALL/ONE-after lines, the final `CONVERGENCE ... PASS`).

## Exp 5 step 6 (convergence after the partition)

After `make exp5`, run `make verify` (preview + check). If it reports divergence, run
`docker exec cass1 nodetool repair --full chat` and `make verify` again; commit both outputs.

## Failure conditions and recovery

| Symptom | Cause / fix |
|---|---|
| 0 hint files before restart | hints not flushed yet: raise `--hints-wait`; or handoff disabled from an earlier aborted run: `nodetool enablehandoff` on all nodes |
| 4b ONE reads not stale | the read was served by another replica (dynamic snitch / speculative retry): check `served_by` in `4b-one-before_reads.csv`; only `stale_on_target` counts |
| preview prints neither "in sync" nor an estimate | repair needs all replicas up: wait for 3×UN (`make status`), check `<label>_preview.txt` |
| `Repair command ... failed` | `docker logs cassN`; rerun `nodetool repair --full chat`; `make reset` if state is unclear |
| state unclear after an abort | `for n in cass1 cass2 cass3; do docker exec $n nodetool enablehandoff; done`, then `make verify` |
