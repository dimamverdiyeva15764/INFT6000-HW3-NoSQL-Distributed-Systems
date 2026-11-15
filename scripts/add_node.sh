#!/usr/bin/env bash
# Usage: add_node.sh [--preload ROWS]
# Bootstraps cass4 into the running cluster and logs the UJ -> UN transition,
# streaming progress and the ownership change. --preload inserts ROWS chat
# messages first so that bootstrap streaming is large enough to observe.
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

rows=0
case "${1:-}" in
  --preload) rows="${2:?--preload needs a row count}" ;;
  "") ;;
  *) die "usage: $0 [--preload ROWS]" ;;
esac

bash scripts/wait_for_cluster.sh 3 60
keyspace_exists || die "keyspace '$KEYSPACE' missing (run: make schema)"
is_running cass4 && die "cass4 is already running"

dir=results/logs/exp1
mkdir -p "$dir"
out="$dir/$(stamp)_topology_add_cass4.log"

if [ "$rows" -gt 0 ]; then
  log "preloading $rows messages into $KEYSPACE.messages"
  docker exec cass1 python3 -c "
import uuid
with open('/tmp/preload.csv', 'w') as f:
    for i in range($rows):
        f.write('preload-%d,%s,loader,%s,preload\n' % (i % 200, uuid.uuid1(), 'x' * 200))
"
  cql cass1 -e "CONSISTENCY QUORUM;
    COPY $KEYSPACE.messages (room, msg_id, author, body, writer_run) FROM '/tmp/preload.csv';"
fi

snapshot() {
  echo "## $1  $(ts_utc)"
  nt status "$KEYSPACE"
  echo
}

snapshot "before adding cass4" | tee "$out"

log "starting cass4"
docker compose --profile scale up -d cass4
start=$(date +%s)

while :; do
  elapsed=$(( $(date +%s) - start ))
  states="$(nt status "$KEYSPACE" 2>/dev/null | grep -E '^[UD][NJLM] ' || true)"
  {
    echo "## +${elapsed}s  $(ts_utc)"
    printf '%s\n' "$states"
    if printf '%s\n' "$states" | grep -q '^UJ '; then
      docker exec cass4 nodetool netstats -H 2>/dev/null | head -25 || true
    fi
    echo
  } >> "$out"
  printf '%s\n' "$states" | grep -q '172.28.0.14' && log "+${elapsed}s $(printf '%s\n' "$states" | grep '172.28.0.14' | cut -c1-2) cass4"
  [ "$(printf '%s\n' "$states" | count_un)" -ge 4 ] && break
  [ "$elapsed" -ge 900 ] && die "cass4 did not reach UN within 900s (see $out)"
  sleep 5
done

snapshot "after cass4 joined (before cleanup)" | tee -a "$out"
for node in $CORE_NODES; do
  log "nodetool cleanup on $node (drops data for ranges it no longer owns)"
  docker exec "$node" nodetool cleanup "$KEYSPACE"
done
snapshot "after cleanup" | tee -a "$out"
log "cass4 joined in ${elapsed}s; log saved to $out"
