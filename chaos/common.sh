#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/../scripts/common.sh"

node_ip() {
  case "$1" in
    cass1) echo 172.28.0.11 ;;
    cass2) echo 172.28.0.12 ;;
    cass3) echo 172.28.0.13 ;;
    *) die "unsupported core node '$1' (choose cass1, cass2, or cass3)" ;;
  esac
}

validate_node() {
  case "$1" in
    cass1|cass2|cass3) ;;
    *) die "unsupported core node '$1' (choose cass1, cass2, or cass3)" ;;
  esac
}

compose_network() {
  local network labels
  while IFS= read -r network; do
    [ -n "$network" ] || continue
    labels="$(docker network inspect -f '{{.Labels}}' "$network" 2>/dev/null || true)"
    if [[ "$labels" == *"com.docker.compose.network:cassnet"* ]]; then
      echo "$network"
      return 0
    fi
  done < <(docker network ls --filter label=com.docker.compose.network=cassnet --format '{{.Name}}')
  return 1
}

node_connected_to() {
  local network="$1" node="$2"
  docker inspect -f '{{range $name, $value := .NetworkSettings.Networks}}{{$name}} {{end}}' \
    "$node" 2>/dev/null | tr ' ' '\n' | grep -Fxq "$network"
}

require_running() {
  is_running "$1" || die "container '$1' is not running"
}

log_event() {
  local action="$1" node="$2" note="${3:-}"
  local file=results/logs/chaos_events.csv
  mkdir -p "$(dirname "$file")"
  [ -f "$file" ] || echo "ts_utc,action,node,note" > "$file"
  LAST_EVENT_TS="$(ts_utc)"
  note="${note//,/;}"
  note="${note//$'\n'/ }"
  printf '%s,%s,%s,%s\n' "$LAST_EVENT_TS" "$action" "$node" "$note" >> "$file"
}

status_has_node_state() {
  local observer="$1" node="$2" expected="$3" output
  output="$(docker exec "$observer" nodetool status 2>/dev/null)" || return 1
  printf '%s\n' "$output" | awk -v state="$expected" -v ip="$(node_ip "$node")" \
    '$1 == state && $2 == ip { found=1 } END { exit !found }'
}

wait_for_peer_state() {
  local node="$1" expected="$2" timeout="${3:-180}" start now observer peers matched
  start="$(date +%s)"
  while :; do
    peers=0
    matched=0
    for observer in $CORE_NODES; do
      [ "$observer" = "$node" ] && continue
      is_running "$observer" || continue
      peers=$((peers + 1))
      if status_has_node_state "$observer" "$node" "$expected"; then
        matched=$((matched + 1))
      fi
    done
    if [ "$peers" -gt 0 ] && [ "$matched" -eq "$peers" ]; then
      return 0
    fi
    now="$(date +%s)"
    [ $((now - start)) -lt "$timeout" ] || return 1
    sleep 5
  done
}

wait_for_all_un() {
  local timeout="${1:-300}" start now observer node healthy
  start="$(date +%s)"
  while :; do
    healthy=true
    for node in $CORE_NODES; do
      is_running "$node" || healthy=false
    done
    if [ "$healthy" = true ]; then
      for observer in $CORE_NODES; do
        for node in $CORE_NODES; do
          if ! status_has_node_state "$observer" "$node" UN; then
            healthy=false
            break
          fi
        done
        [ "$healthy" = true ] || break
      done
    fi
    [ "$healthy" = true ] && return 0
    now="$(date +%s)"
    [ $((now - start)) -lt "$timeout" ] || return 1
    sleep 5
  done
}

latest_event_time() {
  local node="$1" action="$2"
  awk -F, -v node="$node" -v action="$action" \
    '$2 == action && $3 == node { ts=$1 } END { if (ts != "") print ts }' \
    results/logs/chaos_events.csv
}
