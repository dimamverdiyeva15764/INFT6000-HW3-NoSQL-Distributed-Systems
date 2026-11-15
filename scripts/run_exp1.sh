#!/usr/bin/env bash
# Experiment 1: normal operations. Evidence goes to results/logs/exp1/<timestamp>/.
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

run="$(stamp)"
dir="results/logs/exp1/$run"
mkdir -p "$dir" results/raw/exp1

save() { local file="$dir/$1"; shift; log "$file"; "$@" 2>&1 | tee "$file"; }

bash scripts/wait_for_cluster.sh 3 60
keyspace_exists || die "keyspace '$KEYSPACE' missing (run: make schema)"

save 01_compose_ps.txt docker compose ps --format 'table {{.Name}}\t{{.State}}\t{{.Status}}'
save 02_status.txt nt status "$KEYSPACE"
save 03_describecluster.txt nt describecluster
save 04_getendpoints_general.txt nt getendpoints "$KEYSPACE" messages general
save 05_ring.txt nt ring

body="hello from cass1 at $(ts_utc)"
save 06_write_cass1_quorum.txt cql cass1 -e "CONSISTENCY QUORUM;
  INSERT INTO chat.messages (room, msg_id, author, body, writer_run)
  VALUES ('general', now(), 'exp1', '$body', 'exp1-$run');"
save 07_read_cass3_one_traced.txt cql cass3 -e "CONSISTENCY ONE; TRACING ON;
  SELECT room, msg_id, author, body, WRITETIME(body) FROM chat.messages
  WHERE room = 'general' LIMIT 5;"

for node in $CORE_NODES; do
  save "08_tablestats_${node}.txt" docker exec "$node" nodetool tablestats "$KEYSPACE.messages"
done

if [ -f app/chat.py ]; then
  save 09_chat_cli_post.txt docker compose run --rm -T client python -m app.chat post \
    --room general --author exp1 --text "posted through the chat CLI at $(ts_utc)" --cl QUORUM
  save 10_chat_cli_read_traced.txt docker compose run --rm -T client python -m app.chat \
    --trace read --room general --limit 5 --cl ONE
else
  log "SKIP chat CLI steps (app/chat.py not in the repository yet)"
fi

if [ -f workload/runner.py ]; then
  csv="results/raw/exp1/exp1_baseline_QUORUM_r1_$(date -u +%Y%m%dT%H%MZ).csv"
  save 11_baseline_runner.txt docker compose run --rm -T client python -m workload.runner \
    --mode mixed --cl QUORUM --rate 200 --duration 60 \
    --exp exp1 --variant baseline --run-id "exp1-$run" --out "$csv"
else
  log "SKIP baseline workload (workload/runner.py not in the repository yet)"
fi

up="$(count_un < "$dir/02_status.txt")"
replicas="$(grep -c '^[0-9]' "$dir/04_getendpoints_general.txt")"
full_owners="$(grep '^UN ' "$dir/02_status.txt" | grep -c '100\.0%' || true)"
echo
echo "Experiment 1 summary ($dir)"
echo "  nodes UN:                         $up / 3"
echo "  replicas of partition 'general':  $replicas / 3"
echo "  nodes owning 100% (effective):    $full_owners / 3"
[ "$up" -eq 3 ] && [ "$replicas" -eq 3 ] && [ "$full_owners" -eq 3 ] || die "Experiment 1 checks failed"
echo "  result: PASS"
