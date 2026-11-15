#!/usr/bin/env bash
# Applies every schema/*.cql file in name order, then waits for schema agreement.
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

node="$(live_node)" || die "cluster is not running (run: make up)"

for f in schema/*.cql; do
  log "applying $f via $node"
  docker cp "$f" "$node:/tmp/$(basename "$f")"
  cql "$node" -f "/tmp/$(basename "$f")"
done

for _ in $(seq 1 30); do
  if [ "$(nt describecluster | schema_versions)" -eq 1 ]; then
    log "schema agreement reached"
    cql "$node" -e "DESCRIBE KEYSPACE $KEYSPACE" | grep -E "^CREATE (KEYSPACE|TABLE)"
    exit 0
  fi
  sleep 2
done
die "schema versions still disagree after 60s; check: docker exec $node nodetool describecluster"
