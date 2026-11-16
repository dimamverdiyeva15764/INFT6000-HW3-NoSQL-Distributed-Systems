# Experiment 5 — Network Partition and Reconciliation

## Goal

Create a genuine network partition while client traffic is active, compare minority and
majority behavior, then verify the reconciled value after healing.

## Prerequisites

```bash
make up
make schema
make smoke
make client
```

Run three repetitions:

```bash
make exp5 REP=1
make exp5 REP=2
make exp5 REP=3
```

The default experiment partitions cass3 after 15 seconds of live QUORUM traffic and
consistency-level probes. The container must remain running while disconnected. The
script verifies the partitioned node's and majority's `nodetool status` views, and reconnects
the minority using its original static address.

## Expected behavior

- On the minority, QUORUM is rejected while a ONE write succeeds.
- On the majority, a QUORUM write succeeds; the availability probe continues measuring
  ONE, QUORUM, and ALL.
- The minority and majority writes use ordered explicit timestamps so reconciliation is
  measurable. After healing, an ALL read must return the higher-timestamp majority value.

## Evidence

`results/logs/exp5/<run-id>/` contains both partition status views, the still-running
container listing, detection timing from both sides, CQL output for the minority and
majority writes, the post-heal `WRITETIME` read, and workload/probe logs. Per-operation
results are under `results/raw/exp5/`; injection events are appended to
`results/logs/chaos_events.csv`. Keep all three runs and use P4's plotting script to
generate the availability timeline.

## Recovery

If an experiment is interrupted while a node is partitioned, reconnect and verify
convergence before proceeding:

```bash
bash chaos/heal.sh cass3
docker compose ps
docker exec cass1 nodetool status
```
