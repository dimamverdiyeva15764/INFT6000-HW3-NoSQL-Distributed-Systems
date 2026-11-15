#!/usr/bin/env bash
# Starts cass1..cass3 one after another and records the time until all are UN.
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

fresh=true
docker volume inspect "${PROJECT}_cass1-data" >/dev/null 2>&1 && fresh=false

start=$(date +%s)
log "starting cass1, cass2, cass3 (fresh volumes: $fresh)"
docker compose up -d --wait --wait-timeout 900 cass1 cass2 cass3
bash scripts/wait_for_cluster.sh 3 300
seconds=$(( $(date +%s) - start ))

out=results/raw/exp1/startup_times.csv
mkdir -p "$(dirname "$out")"
[ -f "$out" ] || echo "ts_utc,seconds_to_all_un,fresh_volumes" > "$out"
echo "$(ts_utc),$seconds,$fresh" >> "$out"

log "cluster up in ${seconds}s (recorded in $out)"
nt status
