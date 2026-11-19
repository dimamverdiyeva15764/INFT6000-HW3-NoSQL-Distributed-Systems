# Experiment 6 — Consensus via Paxos Lightweight Transactions

Owner: Habib Hasanov (driver usage reviewed by Person 2). Optional in the PDF, recommended in
our plan: it turns the "consensus" part of the rubric from theory into evidence.

## Goal

Show that Cassandra's only data-path consensus protocol, the per-partition Paxos round behind
`IF NOT EXISTS`, gives exactly one winner under a real race, what it costs compared with an
ordinary QUORUM write, and that it needs a majority of replicas.

## Prerequisites

```bash
make up && make schema          # schema/03_lwt.cql creates chat.usernames
```

## Run

```bash
make exp6                        # full sequence (~3 min), REP=1; restarts cass2/cass3 at the end
make exp6-race                   # demo only: one LWT race (10 clients x 20 handles)
bash recovery/run_exp6.sh --help
make figures                     # LaTeX numbers + exp6_lwt_latency.png
```

| Step | Command (inside the client container) | Expected |
|---|---|---|
| 1 LWT race | `python -m recovery.lwt_demo race --clients 10 --handles 20` | exactly one `[applied]=True` per handle; losers get the winner's owner |
| 2 plain race | `... race --clients 10 --handles 20 --plain` | every client told "success"; LWW keeps one owner, 9 acknowledged writes per handle silently lost |
| 3 latency | `... latency --n 200` | LWT median several times the plain QUORUM write (4 round trips vs 1) |
| 4 trace | `... trace` | `paxos_variant`; trace lines for prepare/promise, propose/accept, commit; CAS precondition failure for the second insert |
| 5 cass3 down | `chaos/kill_node.sh cass3`, race | still one winner per handle (2 of 3 = majority) |
| 6 cass2 + cass3 down | `chaos/kill_node.sh cass2`, race | no LWT completes (`Unavailable` / timeouts), never two winners |
| 7 | `chaos/start_node.sh cass2`, `cass3` | 3×UN |

Contention timeouts (`WriteTimeout`, write type CAS) are a valid observation: the outcome of
such an LWT is *unknown*. The race classifier reports a handle whose only "winner" timed out
as `timeout-winner` (the SERIAL read-back shows it committed) - that is not a violation.

## Evidence

| What | Where |
|---|---|
| per-operation CSV | `results/raw/exp6/exp6_<variant>_<SERIAL|QUORUM>_r<rep>_<stamp>.csv` |
| per-handle outcome (applied, returned owner, final owner, category) | `results/logs/exp6/<run>-<step>/<variant>_detail.csv` |
| race summaries (append-only) | `results/logs/exp6/races.csv` |
| console output of each step, nodetool status with 1/2 nodes down | `results/logs/exp6/<run>/0*_*.txt` |
| Paxos trace | `results/logs/exp6/<run>/04_paxos_trace.txt` |
| latency figure | `results/figures/exp6_lwt_latency.png` |

The script exits non-zero only on a **safety violation** (two winners for one handle).

## Live demo segment (2.5 min, see docs/presentation/hasanov_talk.md)

`make exp6-race` prints one line per handle: `applied/ok/failed  final owner  exactly-one`.

## Recovery

`bash chaos/start_node.sh cass2; bash chaos/start_node.sh cass3; bash scripts/wait_for_cluster.sh`;
under heavy contention reduce `--clients` to 5.
