#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"

usage() {
  echo "Usage: $0 <cass1|cass2|cass3> [timeout_seconds]"
  echo "Start a stopped node and wait until its peers report it Up/Normal."
}

[ "${1:-}" != "--help" ] || { usage; exit 0; }
[ "$#" -ge 1 ] && [ "$#" -le 2 ] || { usage >&2; exit 2; }
node="$1"
timeout="${2:-300}"
validate_node "$node"

if is_running "$node"; then
  log "no-op: $node is already running"
  exit 0
fi

log_event start "$node" "docker start"
docker start "$node" >/dev/null
if ! wait_for_peer_state "$node" UN "$timeout"; then
  die "timed out waiting for peers to report $node Up/Normal"
fi
log "$node is Up/Normal according to its peers"
