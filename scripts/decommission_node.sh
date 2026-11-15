#!/usr/bin/env bash
# Decommissions cass4 (UN -> UL -> removed), logs the transition, then deletes
# the container and its volume: a decommissioned node cannot rejoin with its old data.
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

is_running cass4 || die "cass4 is not running (run: make add-node)"

dir=results/logs/exp1
mkdir -p "$dir"
out="$dir/$(stamp)_topology_decommission_cass4.log"

{ echo "## before decommission  $(ts_utc)"; nt status "$KEYSPACE"; echo; } | tee "$out"

(
  start=$(date +%s)
  while :; do
    echo "## +$(( $(date +%s) - start ))s  $(ts_utc)"
    SEED_NODE=cass1 nt status "$KEYSPACE" 2>/dev/null | grep -E '^[UD][NJLM] ' || true
    echo
    sleep 2
  done
) >> "$out" &
poller=$!
trap 'kill "$poller" 2>/dev/null || true' EXIT

start=$(date +%s)
log "decommissioning cass4 (streams its ranges to the remaining nodes)"
docker exec cass4 nodetool decommission
elapsed=$(( $(date +%s) - start ))
sleep 3
kill "$poller" 2>/dev/null || true

{ echo "## after decommission  $(ts_utc)"; SEED_NODE=cass1 nt status "$KEYSPACE"; } | tee -a "$out"

docker compose --profile scale rm -s -f cass4
docker volume rm "${PROJECT}_cass4-data" >/dev/null
log "cass4 decommissioned in ${elapsed}s and removed; log saved to $out"
