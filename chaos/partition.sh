#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"

usage() {
  echo "Usage: $0 <cass1|cass2|cass3> [timeout_seconds]"
  echo "Disconnect a running node from cassnet while keeping its container alive."
}

[ "${1:-}" != "--help" ] || { usage; exit 0; }
[ "$#" -ge 1 ] && [ "$#" -le 2 ] || { usage >&2; exit 2; }
node="$1"
timeout="${2:-180}"
validate_node "$node"
require_running "$node"

network="$(compose_network)" || die "could not find the Compose network labeled cassnet"
if ! node_connected_to "$network" "$node"; then
  log "no-op: $node is already disconnected from $network"
  exit 0
fi

log_event partition "$node" "docker network disconnect $network"
docker network disconnect "$network" "$node"
is_running "$node" || die "$node stopped during partition; expected a live container"
log "$node remains running but is disconnected from $network"

if ! wait_for_peer_state "$node" DN "$timeout"; then
  die "peers did not all report $node Down/Normal within ${timeout}s"
fi
log "peers report $node Down/Normal"
