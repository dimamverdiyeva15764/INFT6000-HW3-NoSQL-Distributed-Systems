# Experiment 1 — Normal Operations

## Goal

Establish the healthy baseline before any fault is injected: every node is Up/Normal,
the schema is in agreement, data is partitioned by consistent hashing and replicated to
all three nodes (RF = 3), and any node can coordinate reads and writes for any key.
This experiment also records cluster start-up time and the topology changes that occur
when a node is added and decommissioned.

## Prerequisites

```bash
make up        # 3 nodes UN; start-up time appended to results/raw/exp1/startup_times.csv
make schema
make smoke
```

## Procedure

```bash
make exp1
```

`scripts/run_exp1.sh` saves every step to `results/logs/exp1/<UTC timestamp>/`:

| File | Command | What it shows |
|---|---|---|
| `01_compose_ps.txt` | `docker compose ps` | All containers running and healthy |
| `02_status.txt` | `nodetool status chat` | 3 × `UN`, 16 tokens each, `Owns (effective)` 100 % per node |
| `03_describecluster.txt` | `nodetool describecluster` | Snitch, partitioner (Murmur3), one schema version |
| `04_getendpoints_general.txt` | `nodetool getendpoints chat messages general` | The 3 replicas of partition `general` |
| `05_ring.txt` | `nodetool ring` | Token ownership of the 48 vnodes |
| `06_write_cass1_quorum.txt` | `cqlsh` on cass1, `CONSISTENCY QUORUM; INSERT …` | Write coordinated by cass1 |
| `07_read_cass3_one_traced.txt` | `cqlsh` on cass3, `CONSISTENCY ONE; TRACING ON; SELECT …` | Same row read through another coordinator; trace lists the replica contacted |
| `08_tablestats_<node>.txt` | `nodetool tablestats chat.messages` on each node | Every node holds and has written the table locally |
| `09_*`, `10_*` | chat CLI `post` / `read --trace` | Same flow through the Python application (runs once `app/chat.py` exists) |
| `11_baseline_runner.txt` + CSV in `results/raw/exp1/` | `workload.runner --mode mixed --cl QUORUM --rate 200 --duration 60` | Baseline latency and throughput (runs once `workload/runner.py` exists) |

The script ends with a PASS/FAIL summary (3 nodes UN, 3 replicas, 100 % effective
ownership on every node).

### Start-up time

Run three times and use the rows of `results/raw/exp1/startup_times.csv`:

```bash
make reset && make up      # repeat 3×; fresh_volumes=true rows are cold starts
```

### Topology change (report evidence)

```bash
make add-node PRELOAD=100000   # cass4: UJ -> UN, streaming, cleanup
make decommission-node         # cass4: UN -> UL -> removed
```

Logs: `results/logs/exp1/*_topology_add_cass4.log` and
`results/logs/exp1/*_topology_decommission_cass4.log`.
With RF 3 on 4 nodes, `Owns (effective)` drops from 100 % to about 75 % per node and
returns to 100 % after decommission. `nodetool cleanup` removes data that the original
nodes no longer own, which is visible as a drop in their `Load`.

## Expected results

- All nodes `UN` with a single schema version.
- `getendpoints` lists all three node addresses (RF = N = 3).
- A row written at QUORUM through cass1 is returned by cass3; the trace shows which
  replica answered.
- `Owns (effective)` is 100 % on every node.

## Screenshots for the report

Save to `results/screenshots/exp1/`: `nodetool status`, `getendpoints`, the traced read,
and one UJ and one UL line from the topology logs.

## Failure conditions and recovery

| Symptom | Likely cause | Recovery |
|---|---|---|
| Container exits with code 137 | Docker memory too low | Docker Desktop → Settings → Resources → Memory ≥ 6 GB, then `make reset && make up` |
| Node stuck in `UJ` or `DN` | Slow start or leftover data from an earlier cluster | `docker logs cassN`; `make reset && make up` |
| More than one schema version | Schema change still propagating | Wait 30 s, rerun `make schema` |
| `NoHostAvailable` from Python on the host | Driver cannot reach container IPs from macOS | Always run Python through the client container (`docker compose run --rm client …`) |
