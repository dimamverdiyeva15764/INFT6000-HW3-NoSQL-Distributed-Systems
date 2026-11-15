# Shared helpers for the cluster scripts. Compatible with macOS bash 3.2.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC2034  # used by the scripts that source this file
PROJECT=inft6000-hw3
CORE_NODES="cass1 cass2 cass3"
KEYSPACE=chat

ts_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
stamp() { date -u +%Y%m%dT%H%M%SZ; }
log() { echo "[$(ts_utc)] $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

is_running() {
  [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]
}

# First running core node, so status checks still work when cass1 is the node under test.
live_node() {
  local n
  for n in ${SEED_NODE:-} $CORE_NODES; do
    if is_running "$n"; then echo "$n"; return 0; fi
  done
  return 1
}

nt() {
  local node
  node="$(live_node)" || die "no Cassandra container is running"
  docker exec "$node" nodetool "$@"
}

cql() {
  local node="$1"; shift
  docker exec "$node" cqlsh "$@"
}

count_un() { grep -c '^UN ' || true; }

# Number of distinct schema versions reported by describecluster (1 = agreement).
schema_versions() {
  awk '/Schema versions:/ {f=1; next}
       f && /^[[:space:]]*$/ {f=0}
       f && /: \[/ {n++}
       END {print n+0}'
}

keyspace_exists() {
  cql "$(live_node)" -e "DESCRIBE KEYSPACE $KEYSPACE" >/dev/null 2>&1
}

status_cmd() {
  if keyspace_exists; then nt status "$KEYSPACE"; else nt status; fi
}
