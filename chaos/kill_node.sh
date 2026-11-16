#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"

usage() {
  echo "Usage: $0 <cass1|cass2|cass3>"
  echo "Suddenly kill a Cassandra node with SIGKILL and log the injection."
}

[ "${1:-}" != "--help" ] || { usage; exit 0; }
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
node="$1"
validate_node "$node"

if ! is_running "$node"; then
  log "no-op: $node is already stopped"
  exit 0
fi

log_event kill "$node" "SIGKILL via docker kill"
docker kill --signal KILL "$node" >/dev/null
log "killed $node"
