# Interface contracts (IC0)

Agreed values that every member's code relies on. Recorded by Person 2. Change them
only by pull request reviewed by all owners affected.

## Cluster

| Item | Value |
|---|---|
| Cluster name | `inft6000-g4` |
| Nodes | `cass1` 172.28.0.11, `cass2` 172.28.0.12, `cass3` 172.28.0.13 (optional `cass4` 172.28.0.14) |
| Network | bridge `cassnet` 172.28.0.0/16 |
| Topology | DC `dc1`, rack `rack1`, `GossipingPropertyFileSnitch`, 16 vnodes |
| Image | `cassandra:5.0.8` |
| CQL port | 9042 |
| Keyspace | `chat`, `NetworkTopologyStrategy {dc1: 3}` |

## Python runtime

- Python 3.11 in the client container; dependencies pinned in `client/requirements.txt`.
- Every module runs as `python -m <package>.<module>` from the repository root (`/work`).
- Environment: `CASSANDRA_HOSTS` (default the three addresses above), `KEYSPACE` (`chat`),
  `LOCAL_DC` (`dc1`), `CLIENT_TIMEOUT_S` (`5`).

## Data-access API (`app/db.py`)

```python
from app.db import get_session, stmt, classify_error          # frozen
from app.db import timed_execute, coordinator_profile, shutdown  # helpers

session = get_session(hosts=None, whitelist=None)   # whitelist pins the default coordinator(s)
ps = stmt("SELECT ... WHERE room = ?", "QUORUM", serial_cl=None)   # cached, CL fixed on the object
res = timed_execute(session, ps, ["general"], profile=coordinator_profile("cass3"), trace=False)
res.outcome, res.error_type, res.latency_ms, res.coordinator, res.rows, res.error
```

- CL names are strings: `ONE`, `TWO`, `THREE`, `QUORUM`, `ALL`, `LOCAL_ONE`, `LOCAL_QUORUM`,
  `EACH_QUORUM`, `ANY`, `SERIAL`, `LOCAL_SERIAL` (case-insensitive).
- Driver policies: `TokenAwarePolicy(DCAwareRoundRobinPolicy("dc1"))`,
  `FallthroughRetryPolicy` (no retries), no speculative execution, request timeout 5 s.
  Pinned profiles (`coordinator_profile(host)`) use `WhiteListRoundRobinPolicy([host])`.
- `classify_error(exc)` → `ok`, `unavailable`, `write_timeout`, `read_timeout`,
  `write_failure`, `read_failure`, `no_host`, `client_timeout`, `other`.

## Results CSV (`app/results_log.py`)

Columns, in this order:

```
ts_utc, exp, variant, run_id, op, cl, key, latency_ms, outcome, error_type,
expected_seq, observed_seq, stale, coordinator
```

| Column | Meaning |
|---|---|
| `ts_utc` | ISO-8601 UTC with microseconds, e.g. `2026-11-16T10:15:03.123456Z` (operation start) |
| `exp`, `variant`, `run_id` | experiment (`exp2`), variant (`write`, `probe`, …), unique run id |
| `op` | `write`, `read` (other experiments may add e.g. `lwt`) |
| `cl` | consistency level of this operation |
| `key` | partition key (room) |
| `latency_ms` | client-observed latency, 3 decimals |
| `outcome` | `classify_error()` string; `ok` on success |
| `error_type` | driver exception class name (`Unavailable`, `WriteTimeout`, …); empty on success |
| `expected_seq`, `observed_seq`, `stale` | freshness probes only; `stale` is 1/0, empty if the read failed |
| `coordinator` | address of the coordinator node |

Empty cells are allowed for fields that do not apply. Use `ResultsLog` to write the file:
it is thread-safe, flushes every row and refuses to overwrite an existing file.

## Chaos event log

`results/logs/chaos_events.csv`: `ts_utc, action, node, note`.

## File naming

`results/raw/expN/<exp>_<variant>_<cl>_r<rep>_<YYYYmmddTHHMMZ>.csv` — fields contain no `_`
(`ONE-QUORUM`, not `ONE_QUORUM`). Results are committed as produced and never overwritten.

## Script conventions

Every script has `--help`, exits non-zero on failure, writes only under `results/`
(report figures/tables generated from results may go to `docs/report/generated/`), and is
invoked from a Makefile target.
