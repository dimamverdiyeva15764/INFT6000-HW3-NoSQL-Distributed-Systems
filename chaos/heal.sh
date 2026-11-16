#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"

usage() {
  echo "Usage: $0 <cass1|cass2|cass3> [timeout_seconds]"
  echo "Reconnect a partitioned node using its original static IP and wait for convergence."
}

[ "${1:-}" != "--help" ] || { usage; exit 0; }
[ "$#" -ge 1 ] && [ "$#" -le 2 ] || { usage >&2; exit 2; }
node="$1"
timeout="${2:-300}"
validate_node "$node"
require_running "$node"

network="$(compose_network)" || die "could not find the Compose network labeled cassnet"
if node_connected_to "$network" "$node"; then
  log "no-op: $node is already connected to $network"
else
  log_event heal "$node" "reconnect with static IP $(node_ip "$node")"
  docker network connect --ip "$(node_ip "$node")" "$network" "$node"
fi

if ! wait_for_all_un "$timeout"; then
  die "timed out waiting for all core nodes to report Up/Normal on every node"
fi
log "all core nodes report Up/Normal on every node"
