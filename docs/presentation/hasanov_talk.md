# Habib Hasanov — talk segment (≈ 5 min: 1.5 min slides + 2.5 min demo + 1 min conclusion)

Slot 15:00–20:00 of the run-of-show. Slides are in the assembled deck
(`docs/presentation/group4_deck.pptx`, slides 11–14); this file has the speaker notes and the
exact demo commands.

## Slide 1 — Three ways replicas heal (≈ 45 s)

- Visual: `docs/diagrams/antientropy_merkle.png`
- **Hints**: the coordinator keeps the writes a dead replica missed (≤ 3 h) and replays them
  when gossip sees it come back. Best effort; never counts toward the CL.
- **Read repair**: a read at QUORUM/ALL finds a digest mismatch and writes the newest value back
  *before* answering — but only for the rows that were read.
- **Anti-entropy repair**: Merkle trees per token range; compare top-down, stream only the
  differing ranges. The only mechanism that covers never-read rows and deletes; must run within
  `gc_grace_seconds` (10 days) or deleted rows come back as zombies.

*Say:* "Hints fix short outages for free, read repair fixes hot data, and full repair is the
safety net. Conflicts in all three are resolved the same way: highest timestamp wins."

## Slide 2 — Consensus: where Cassandra has it and where it doesn't (≈ 45 s)

- Visual: `docs/diagrams/paxos_lwt.png`
- Ordinary reads/writes: **no leader, no log, no election** — any node coordinates; quorum
  overlap ≠ agreement; concurrent writers resolved by last-write-wins.
- Gossip = membership dissemination + φ-accrual suspicion (we measured ≈ 19.6 s to detect a
  crash, 0.7 s for a graceful stop) — not agreement.
- **LWT = Paxos per partition**: prepare/promise → read → propose/accept → commit (4 round trips
  in v1). Ballots, not a leader. Majorities intersect → no split-brain for LWTs.
- 6.0 (alpha): Transactional Cluster Metadata (CEP-21) and Accord (CEP-15).

## Demo (≈ 2.5 min) — continues from Person 3's segment

Before the talk: cluster up, `make schema`, `make verify` shows PASS. Person 3 ends with cass3
stopped (if not: `bash chaos/kill_node.sh cass3` and wait ~20 s).

```bash
# 1. writes while cass3 is down -> the coordinators keep hints   (20 s)
docker compose run --rm client python -m recovery.verify_convergence write --n 2000 --variant demo
sleep 12; docker exec cass1 nodetool listpendinghints
#    -> "cass3 ... Total files 1..2": hints waiting for cass3

# 2. bring cass3 back; hints are replayed automatically            (40 s, talk over it)
bash chaos/start_node.sh cass3
docker exec cass1 nodetool listpendinghints
#    -> no pending hints left

# 3. prove convergence without a manual repair                    (20 s)
make verify LABEL=demo
#    -> "PREVIEW demo: IN SYNC (Merkle trees match; nothing to stream)"  "CONVERGENCE demo: PASS"

# 4. consensus: 10 clients race for each of 20 usernames          (40 s)
make exp6-race
#    -> one line per handle: "1/10/0 ... exactly-one"; "SAFETY VIOLATIONS: 0"
```

Backup if Docker misbehaves: recorded video `results/screenshots/exp4/` and
`results/logs/exp4/<run>/` / `results/logs/exp6/<run>/` text outputs.

## Conclusion (≈ 1 min) — slide 14

1. Cassandra is leaderless: availability first, consistency chosen **per request** (ONE/QUORUM/ALL).
2. Failures are detected locally by gossip in ~20 s; ALL stops, QUORUM survives one node.
3. Divergence is healed by hints, read repair and Merkle-tree repair; no acknowledged QUORUM
   write was lost (Exp 4).
4. Concurrent writes lose data silently under LWW; when that matters, Paxos LWTs give one winner
   at roughly several times the latency (Exp 6).
5. Limitations: one host (sub-ms network), short outages, Cassandra 5.0 only (TCM/Accord in 6.0
   not tested).

Then: "We are happy to take questions" → hand to Q&A (each member answers their area).

## Likely Q&A (I lead)

| Question | Short answer |
|---|---|
| Does Cassandra elect a leader? | No. Not for data (any coordinator, per-request quorums), not for LWTs (per-instance ballots). Only 6.0's CMS for metadata has designated members. |
| Is QUORUM read + write linearizable? | No. It guarantees overlap with the latest *acknowledged* write; concurrent writers are LWW, failed writes are not rolled back. Linearizable = LWT/SERIAL. |
| Why LWW and not vector clocks? | No siblings, no client-side merge, cheap compaction; cost = silent loss of concurrent updates (Exp 5, Exp 6 plain race). |
| What if a node is down longer than 3 h? | No more hints for it; read repair + full repair must reconcile it; repair within `gc_grace_seconds` or deletes resurrect. |
| Why did the LWT race still succeed with one node down? | 2 of 3 replicas are a majority for both Paxos phases. With 2 down there is no majority → Unavailable, never two winners. |
| Incremental vs full repair? | Incremental validates only un-repaired SSTables and marks them repaired (cheaper, default); full rebuilds trees over everything (we use it so the evidence is unambiguous). |
| How sure are your numbers? | Every number is computed from committed CSVs by `make figures`; 3 repetitions; single-host caveat. In Exp 5 one probe level per run was stuck on the isolated coordinator (client-side timeouts) — shown in the per-repetition table. |
| Paxos v1 vs v2? | v2 (4.1+, opt-in) merges read into prepare: 2 round trips uncontended, Paxos state cleaned by Paxos repair. We record `paxos_variant` in the trace output. |
