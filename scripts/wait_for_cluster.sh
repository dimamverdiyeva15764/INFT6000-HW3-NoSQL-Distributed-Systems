#!/usr/bin/env bash
# Usage: wait_for_cluster.sh [expected_up_normal_nodes=3] [timeout_seconds=300]
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

expected="${1:-3}"
timeout="${2:-300}"
start=$(date +%s)

while :; do
  elapsed=$(( $(date +%s) - start ))
  up=0; versions=0
  if out="$(nt status 2>/dev/null)"; then
    up="$(printf '%s\n' "$out" | count_un)"
    versions="$(nt describecluster 2>/dev/null | schema_versions)"
  fi
  if [ "$up" -ge "$expected" ] && [ "$versions" -eq 1 ]; then
    log "cluster ready: $up nodes UN, schema in agreement after ${elapsed}s"
    exit 0
  fi
  if [ "$elapsed" -ge "$timeout" ]; then
    printf '%s\n' "${out:-}" >&2
    die "timed out after ${timeout}s: $up/$expected nodes UN, $versions schema version(s)"
  fi
  log "waiting: $up/$expected nodes UN, $versions schema version(s), ${elapsed}s elapsed"
  sleep 5
done
