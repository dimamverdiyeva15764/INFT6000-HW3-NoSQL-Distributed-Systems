# Person 2 — talk segment (≈ 5 min: 2 min slides + 3 min demo)

Person 4 assembles the deck; these are the slide contents, speaker notes and the exact
demo commands for this segment.

## Slide 1 — Tunable consistency (≈ 40 s)

- Every request carries a consistency level: how many replicas must answer.
- N = RF = 3 → ONE = 1, QUORUM = 2, ALL = 3. The write still goes to **all** replicas.
- Defaults: cqlsh ONE, Python driver LOCAL_ONE — our app always sets it explicitly.
- Visual: `docs/diagrams/quorum_overlap.png`

*Say:* "The level does not change how much data is replicated — only how long the
coordinator waits before it answers you."

## Slide 2 — Write and read paths (≈ 50 s)

- Write: coordinator → all replicas → commit log + memtable → reply after W acks.
  Down replica → hint (does not count toward W). Timeout ≠ rollback.
- Read: 1 data + (R−1) digest requests → mismatch → full reads → last-write-wins →
  **blocking read repair** before replying (monotonic quorum reads, default since 4.0).
- Visuals: `docs/diagrams/write_path.png`, `docs/diagrams/read_path.png`

## Slide 3 — Quorum math and what it does not give (≈ 30 s)

| W | R | R+W | overlap? | failures tolerated |
|---|---|---|---|---|
| ONE | ONE | 2 | no | 2 / 2 |
| QUORUM | QUORUM | 4 | yes | 1 / 1 |
| ALL | ONE | 4 | yes | 0 / 2 |

- R + W > N ⇒ read sees the latest *acknowledged* write — not linearizability
  (clock-based LWW, no rollback of failed writes, concurrent writers lose data → LWT).

## Demo (≈ 3 min) — cluster already running (`make up && make schema` 15 min before)

```bash
# 1. post and read through two different coordinators (15 s)
docker compose run --rm client python -m app.chat --coordinator cass1 post --room demo --author p2 --text "hello at QUORUM" --cl QUORUM
docker compose run --rm client python -m app.chat --coordinator cass3 --trace read --room demo --limit 3 --cl ALL
#    -> point at "coordinator: cass3" and "nodes involved: cass1, cass2, cass3"

# 2. live load: 20 s at ONE, then 20 s at ALL (per-second lines) (60 s)
make demo-exp2
#    -> compare the p50/p99 columns of the two runs

# 3. pre-recorded results (60 s)
cat results/summary/exp2_summary.md
#    -> show results/figures/exp2_latency_percentiles.png and exp2_staleness.png
```

Fallback if the cluster misbehaves: show `results/screenshots/exp2/runner_live.png` and the
committed figures; nothing in this segment depends on live data.

## Likely Q&A (I lead)

- *Why is ALL barely slower than ONE here?* — One host, sub-millisecond replica RTT; the
  coordinator's wait is the only difference. Across DCs the gap is the WAN RTT.
- *Why did ONE/ONE show (almost) no stale reads?* — Replication completes faster than one
  client round trip; staleness is probabilistic (PBS). Exp 4b/5 show it once a replica
  misses writes.
- *Does QUORUM give strong consistency?* — Read-latest-acknowledged-write only; not
  linearizable (LWW, timeouts not rolled back). Use LWT/SERIAL for compare-and-set.
- *How did you avoid measurement artefacts?* — No driver retries, open-loop schedule,
  warm-up discarded, 3 repetitions with rotated order, `docker stats` sampled.
