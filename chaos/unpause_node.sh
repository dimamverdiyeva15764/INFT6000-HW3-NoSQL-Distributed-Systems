#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"

usage() {
  echo "Usage: $0 <cass1|cass2|cass3>"
  echo "Resume a node frozen with docker pause."
}

[ "${1:-}" != "--help" ] || { usage; exit 0; }
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
node="$1"
validate_node "$node"
require_running "$node"

paused="$(docker inspect -f '{{.State.Paused}}' "$node")"
if [ "$paused" != true ]; then
  log "no-op: $node is not paused"
  exit 0
fi

log_event unpause "$node" "docker unpause"
docker unpause "$node" >/dev/null
log "$node resumed"
