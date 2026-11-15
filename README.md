# CassChat — Apache Cassandra Distributed Systems Study

INFT 6000 Homework 3, Group 4. A three-node Apache Cassandra 5.0 cluster in Docker
Compose with a terminal message board, a workload generator and fault-injection
experiments that examine partitioning, tunable consistency, failure detection,
anti-entropy and Paxos lightweight transactions.

## Requirements

| Tool | Version | Notes |
|---|---|---|
| Docker Desktop (macOS/Windows) or Docker Engine (Linux) | Engine ≥ 24, Compose v2 ≥ 2.20 | Allocate **≥ 6 GB memory** and ≥ 4 CPUs to Docker |
| GNU Make | any | macOS: `xcode-select --install` |
| Bash | 3.2+ | The macOS system bash is sufficient |

No local Python or Java installation is needed: Cassandra runs in containers and all
Python code runs in the `client` container.

## Quick start

```bash
git clone <repository-url> inft6000-hw3-cassandra
cd inft6000-hw3-cassandra
make up        # starts cass1 → cass2 → cass3 and waits until all are Up/Normal (a few minutes on the first start)
make schema    # creates keyspace chat (RF 3) and tables
make smoke     # end-to-end check, prints PASS lines
```

`make status` prints and saves the cluster state, `make down` stops the containers and
keeps data, `make reset` deletes containers **and** data volumes.

## Cluster configuration

| Setting | Value |
|---|---|
| Image | `cassandra:5.0.8` (override with `CASSANDRA_IMAGE`) |
| Cluster name | `inft6000-g4` |
| Nodes | `cass1` 172.28.0.11 (seed), `cass2` 172.28.0.12 (seed), `cass3` 172.28.0.13 |
| Optional node | `cass4` 172.28.0.14 (compose profile `scale`) |
| Network | bridge `cassnet` 172.28.0.0/16; dynamic addresses only from 172.28.1.0/24 |
| Snitch / topology | `GossipingPropertyFileSnitch`, datacenter `dc1`, rack `rack1` |
| Tokens | 16 vnodes per node, Murmur3Partitioner |
| Heap | 512 MB per node |
| Keyspace | `chat`, `NetworkTopologyStrategy {dc1: 3}` |
| Host access | CQL on `127.0.0.1:9042` (cass1 only) |

Nodes start sequentially: each waits until the previous node is healthy, because
bootstrapping several nodes at the same time is unsafe. A node is reported healthy once
it answers CQL, which Cassandra only allows after the node has joined the ring.

### Why Python runs in a container

The driver discovers every node through `system.peers` and connects to the nodes'
internal addresses (172.28.0.x). Those addresses are not routable from the macOS or
Windows host, so the `client` service (profile `tools`) runs all Python code inside the
cluster network:

```bash
make shell                                    # interactive shell in the client container
docker compose run --rm client python -m <module> [args]
```

The client image is built automatically on first use (`make client` rebuilds it).

## Data model

```sql
CREATE TABLE chat.messages   (room text, msg_id timeuuid, author text, body text, writer_run text,
                              PRIMARY KEY (room, msg_id)) WITH CLUSTERING ORDER BY (msg_id DESC);
CREATE TABLE chat.room_state (room text PRIMARY KEY, last_seq bigint, updated_by text);
```

Every `schema/*.cql` file is applied in name order by `make schema`; statements use
`IF NOT EXISTS`, so the command is safe to rerun.

## Repository layout

```
docker-compose.yml   cluster, optional cass4, client container
Makefile             one entry point for every task
client/              client container image and Python dependencies
schema/              CQL schema
scripts/             cluster lifecycle, smoke test, topology change, Experiment 1
app/                 data-access layer and chat CLI
workload/            workload generator and consistency experiment
chaos/               fault injection and failure-detection tooling
recovery/            recovery verification and lightweight-transaction demo
analysis/            summaries and figures from results/
experiments/         runbook per experiment
results/             raw CSV, logs, screenshots, figures (committed)
docs/                diagrams, report, presentation, references
```

## Experiments

| Command | Experiment |
|---|---|
| `make exp1` | Normal operations: ring, replicas, cross-coordinator reads/writes, baseline load |
| `make exp2` | Consistency tuning: ONE / QUORUM / ALL latency, throughput, freshness |
| `make exp3` | Node failure under live traffic |
| `make exp4` | Recovery: hinted handoff, read repair, anti-entropy repair |
| `make exp5` | Network partition and last-write-wins reconciliation |
| `make exp6` | Paxos lightweight transactions |
| `make figures` | Summary tables and figures from `results/raw/` |

### Experiment 1 — Normal operations

See [experiments/EXP1_normal_operations.md](experiments/EXP1_normal_operations.md).

```bash
make exp1                        # evidence in results/logs/exp1/<timestamp>/
make reset && make up            # repeat for start-up timing (results/raw/exp1/startup_times.csv)
make add-node PRELOAD=100000     # bootstrap cass4 and record UJ -> UN
make decommission-node           # decommission cass4 and record UL -> removed
```

## Results conventions

- Raw data: `results/raw/expN/<exp>_<variant>_<cl>_r<rep>_<YYYYmmddTHHMMZ>.csv`
- Logs: `results/logs/` (status snapshots, experiment logs); all timestamps are UTC
- Results are committed as produced and never overwritten.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `make up` times out, a container exited with code 137 | Docker is out of memory: raise it to ≥ 6 GB, then `make reset && make up` |
| `pull access denied` / `manifest unknown` for the Cassandra image | Use an existing 5.0 tag: `CASSANDRA_IMAGE=cassandra:5.0 make up`, and update the default in `docker-compose.yml` so everyone runs the same version |
| Port 9042 already in use | Stop the other Cassandra instance, or change the host port of `cass1` |
| A node stays `UJ` or `DN` | `docker logs cassN`; if the cluster state is unclear, `make reset && make up` |
| Several schema versions in `nodetool describecluster` | Wait 30 s and rerun `make schema` |
| `NoHostAvailable` when running Python on the host | Run it in the client container (`make shell`) |
| `cass4` fails to start after an earlier decommission | `make decommission-node` removes its volume; otherwise `docker volume rm inft6000-hw3_cass4-data` |
