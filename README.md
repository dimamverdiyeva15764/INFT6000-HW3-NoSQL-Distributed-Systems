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
make test      # unit tests of the Python code (no cluster needed)
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
| `make exp2` | Consistency tuning: ONE / QUORUM / ALL latency, throughput, freshness (`make exp2-report` for tables/figures) |
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

### Experiment 2 — Consistency tuning

See [experiments/EXP2_consistency_tuning.md](experiments/EXP2_consistency_tuning.md).

```bash
make test          # unit tests (client image only, no cluster needed)
make exp2-quick    # ~4-minute dry run of the whole grid
make exp2          # full grid: 27 fixed-rate runs, 3 saturation runs, 15 probe runs (~40 min)
make exp2-report   # tables, figures, report numbers from results/raw/exp2/
make demo-exp2     # live demo: 20 s at ONE, then 20 s at ALL, per-second output
```

Output: raw CSVs in `results/raw/exp2/`, run logs in `results/logs/exp2/<stamp>/`,
tables in `results/summary/exp2_*`, figures in `results/figures/exp2_*.png`.

### Experiments 3 and 5 — Fault injection

The fault scripts use the Compose network label to find the project network (whose
actual Docker name is prefixed by Compose), preserve each node's static IP when healing,
and append injection events to `results/logs/chaos_events.csv`. The client traffic and
availability probe run in separate client containers, so a failed consistency level does
not stop measurements at the other levels.

```bash
make exp3 VARIANT=3a REP=1       # one-node SIGKILL during active traffic
make exp3 VARIANT=3b REP=1       # two nodes killed; QUORUM should fail, ONE may work
make exp3 VARIANT=3c REP=1       # graceful stop/start vs. SIGKILL/restart
make exp5 REP=1                  # partition cass3, demonstrate minority/majority behavior, heal
```

Run each experiment with `REP=1`, `REP=2`, and `REP=3` for the required repetitions.
Override `NODE`, `DURATION`, `FAULT_AFTER`, and `FAULT_SECONDS` if needed. Run
`bash chaos/run_exp3.sh --help` or `bash chaos/run_exp5.sh --help` for defaults.
Exp 3/5 CSVs go to `results/raw/exp3/` and `results/raw/exp5/`; orchestration logs,
status snapshots, and detection measurements go under `results/logs/exp3/` and
`results/logs/exp5/`. `chaos/detect_down.py` is host-side and uses only the Python
standard library. Keep the Docker cluster running while an experiment is in progress.

## Application and workload generator

All Python talks to Cassandra through `app/db.py` (token-aware routing, no driver
retries, 5 s client timeout), so every failure is visible and counted. Interfaces and
the CSV schema are fixed in [docs/CONTRACTS.md](docs/CONTRACTS.md).

### CassChat CLI (`app/chat.py`)

```bash
docker compose run --rm client python -m app.chat post --room general --author alice --text "hello" --cl QUORUM
docker compose run --rm client python -m app.chat read --room general --limit 5 --cl ONE
docker compose run --rm client python -m app.chat --trace read --room general --cl ALL      # query trace
docker compose run --rm client python -m app.chat --coordinator cass3 read --room general --cl ONE
docker compose run --rm client python -m app.chat tail --room general --interval 1 --cl QUORUM
docker compose run --rm client python -m app.chat hosts                                      # driver's view of nodes
```

A failed request prints its classified outcome, e.g.
`FAILED post at ALL: outcome=unavailable (Unavailable)`, and exits with status 1.

### Workload generator (`workload/runner.py`)

| Option | Meaning |
|---|---|
| `--mode write\|read\|mixed\|probe` | traffic type; `probe` = write then read back through a different coordinator, logs stale reads |
| `--cl X` or `--write-cl X --read-cl Y` | consistency levels |
| `--rate R` / `--max` | open loop at R ops/s (default 200) / closed loop, as fast as possible |
| `--threads`, `--duration`, `--warmup` | concurrency, measured seconds, unlogged warm-up seconds |
| `--probes N` | probe mode: stop after N probes |
| `--rooms`, `--preload N`, `--read-ratio`, `--read-limit`, `--payload` | data shape |
| `--exp --variant --rep --run-id --out` | labels and CSV path (default follows the naming convention) |

It prints one summary line per second (ops/s, ok, errors by type, p50/p99) and a final
summary; Ctrl-C stops cleanly and keeps the CSV. Exit status 0 = run completed,
2 = could not connect / bad arguments, 3 = no operation succeeded.

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
| Bash cannot find Docker while running a script from WSL | Enable Docker Desktop's WSL integration for that distribution, or use a Bash shell with access to the Windows Docker CLI |
| `ModuleNotFoundError: pandas` (or other module) in the client container | The image predates `client/requirements.txt`: `make client` |
| Result files owned by root (Linux hosts) | Files written by the client container: `sudo chown -R $USER results docs/report/generated` |
| `cass4` fails to start after an earlier decommission | `make decommission-node` removes its volume; otherwise `docker volume rm inft6000-hw3_cass4-data` |
