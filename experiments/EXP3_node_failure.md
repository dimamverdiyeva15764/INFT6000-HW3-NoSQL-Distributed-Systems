# Experiment 3 — Node Failure Under Active Traffic

## Goal

Measure how Cassandra behaves when one or two nodes fail while client traffic is
running, and compare gossip failure-detection time after a graceful stop and a sudden
SIGKILL.

## Prerequisites

```bash
make up
make schema
make smoke
make client
```

Run each variant three times, changing `REP` for each run:

```bash
make exp3 VARIANT=3a REP=1
make exp3 VARIANT=3a REP=2
make exp3 VARIANT=3a REP=3
make exp3 VARIANT=3b REP=1
make exp3 VARIANT=3b REP=2
make exp3 VARIANT=3b REP=3
make exp3 VARIANT=3c REP=1
make exp3 VARIANT=3c REP=2
make exp3 VARIANT=3c REP=3
```

Variant `3a` kills one node; `3b` kills two nodes while leaving cass1 available; `3c`
performs a graceful stop/restart followed by a kill/restart of the selected node. Each
run starts a QUORUM mixed workload and independent writes/reads at ONE, QUORUM, and ALL.
The default run lasts 120 seconds (180 seconds for 3c), waits 15 seconds before injecting
the fault, and leaves it in place for 20 seconds.

## Expected behavior

- With one node down, QUORUM continues to succeed and ALL writes fail.
- With two nodes down, QUORUM requests fail; ONE can still succeed when the surviving
  replica has the partition.
- After restart, nodes return to Up/Normal and the workload continues.
- The detection table compares injection and gossip log timestamps for stop/kill and
  records the observer node.

## Evidence

Each run creates `results/logs/exp3/<run-id>/` with runner output, availability-probe
output, detection results, and final node status. Per-operation measurements are written
to `results/raw/exp3/`; injection timestamps are in
`results/logs/chaos_events.csv`. Preserve the three runs for each variant and use the
probe CSVs to plot availability by consistency level.

## Recovery

If a run is interrupted, restore the cluster before retrying:

```bash
bash chaos/start_node.sh cass2
bash chaos/start_node.sh cass3
```

Check `docker compose ps` and `nodetool status` before starting another run.
