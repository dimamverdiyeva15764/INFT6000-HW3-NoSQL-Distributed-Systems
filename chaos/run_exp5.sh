#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"

usage() {
  cat <<'EOF'
Usage: run_exp5.sh [--node cass3] [--rep 1] [--duration seconds]
                   [--fault-after seconds] [--fault-seconds seconds]

Run a real Docker-network partition with the workload and availability probe active.
The disconnected node is the minority; the other two nodes form the majority.
EOF
}

node=cass3
rep=1
duration=120
fault_after=15
fault_seconds=30
while [ "$#" -gt 0 ]; do
  case "$1" in
    --help) usage; exit 0 ;;
    --node) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; node="$2"; shift 2 ;;
    --rep) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; rep="$2"; shift 2 ;;
    --duration) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; duration="$2"; shift 2 ;;
    --fault-after) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; fault_after="$2"; shift 2 ;;
    --fault-seconds) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; fault_seconds="$2"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

validate_node "$node"
[[ "$rep" =~ ^[1-9][0-9]*$ ]] || die "rep must be a positive integer"
[[ "$duration" =~ ^[1-9][0-9]*$ && "$fault_after" =~ ^[0-9]+$ && "$fault_seconds" =~ ^[1-9][0-9]*$ ]] \
  || die "duration and fault times must be integer seconds"
minimum=$((fault_after + fault_seconds + 30))
[ "$duration" -ge "$minimum" ] || die "duration must be at least ${minimum}s"
command -v "${PYTHON:-python}" >/dev/null 2>&1 || die "Python is required for chaos.detect_down"

bash scripts/wait_for_cluster.sh 3 300
docker compose build client

run_id="exp5-partition-${node}-r${rep}-$(stamp)"
dir="results/logs/exp5/$run_id"
room="p3-partition-r${rep}-$(stamp)"
mkdir -p "$dir"
log "starting Exp 5, run $run_id; evidence: $dir"

docker exec cass1 cqlsh -e \
  "CONSISTENCY ALL; UPDATE chat.room_state SET last_seq=0, updated_by='baseline' WHERE room='$room';" \
  > "$dir/00_baseline.txt" 2>&1

runner_pid=
probe_pid=
cleanup_jobs() {
  local pid
  for pid in "$runner_pid" "$probe_pid"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  if [ "${partitioned:-false}" = true ] && is_running "$node"; then
    bash chaos/heal.sh "$node" 300 || log "WARNING: could not heal $node during cleanup"
  fi
}
trap cleanup_jobs EXIT INT TERM

docker compose run --rm -T client python -m workload.runner \
  --mode mixed --cl QUORUM --rate 50 --threads 4 --duration "$duration" \
  --exp exp5 --variant partition --rep "$rep" --run-id "$run_id-load" \
  > "$dir/runner.log" 2>&1 &
runner_pid=$!
docker compose run --rm -T client python -m chaos.availability_probe \
  --duration "$duration" --rep "$rep" --run-id "$run_id-probe" \
  > "$dir/availability_probe.log" 2>&1 &
probe_pid=$!
sleep "$fault_after"

partitioned=true
bash chaos/partition.sh "$node" 180
partition_ts="$(latest_event_time "$node" partition)"
[ -n "$partition_ts" ] || die "partition event was not recorded"

docker ps --filter "name=^/${node}$" > "$dir/01_partitioned_container.txt"
is_running "$node" || die "partitioned container is not running"
majority=cass1
[ "$node" = cass1 ] && majority=cass2
docker exec "$majority" nodetool status > "$dir/02_majority_status.txt" 2>&1
docker exec "$node" nodetool status > "$dir/03_minority_status.txt" 2>&1

other="$majority"
"${PYTHON:-python}" -m chaos.detect_down --node "$node" --observer "$other" \
  --transition down --since "$partition_ts" --event-action partition --timeout 120 \
  > "$dir/04_detection_majority_view.txt" 2>&1
"${PYTHON:-python}" -m chaos.detect_down --node "$other" --observer "$node" \
  --transition down --since "$partition_ts" --event-action partition --timeout 120 \
  > "$dir/05_detection_minority_view.txt" 2>&1

minority_ts="$("${PYTHON:-python}" -c 'import time; print(time.time_ns() // 1000 + 1000000)')"
majority_ts=$((minority_ts + 1000000))

if docker exec "$node" cqlsh -e \
  "CONSISTENCY QUORUM; UPDATE chat.room_state USING TIMESTAMP $minority_ts SET last_seq=111, updated_by='minority-quorum' WHERE room='$room';" \
  > "$dir/06_minority_quorum.txt" 2>&1; then
  die "minority QUORUM write unexpectedly succeeded; inspect $dir/06_minority_quorum.txt"
fi
grep -Eiq 'Unavailable|WriteTimeout|not enough replicas|consistency level QUORUM' "$dir/06_minority_quorum.txt" \
  || die "minority QUORUM failed for an unexpected reason; inspect $dir/06_minority_quorum.txt"

docker exec "$node" cqlsh -e \
  "CONSISTENCY ONE; UPDATE chat.room_state USING TIMESTAMP $minority_ts SET last_seq=111, updated_by='minority-one' WHERE room='$room';" \
  > "$dir/07_minority_one.txt" 2>&1

docker exec "$majority" cqlsh -e \
  "CONSISTENCY QUORUM; UPDATE chat.room_state USING TIMESTAMP $majority_ts SET last_seq=222, updated_by='majority' WHERE room='$room';" \
  > "$dir/08_majority_quorum.txt" 2>&1

sleep "$fault_seconds"
bash chaos/heal.sh "$node" 300
partitioned=false

docker exec "$majority" cqlsh -e \
  "CONSISTENCY ALL; SELECT last_seq, updated_by, WRITETIME(last_seq) AS write_time FROM chat.room_state WHERE room='$room';" \
  > "$dir/09_post_heal_read.txt" 2>&1
grep -q '222' "$dir/09_post_heal_read.txt" \
  || die "post-heal read did not return the higher-timestamp majority write"
grep -q 'majority' "$dir/09_post_heal_read.txt" \
  || die "post-heal read did not identify the majority write"
docker exec "$majority" nodetool status > "$dir/10_healed_status.txt" 2>&1

wait "$runner_pid" || { cat "$dir/runner.log" >&2; die "workload runner failed"; }
runner_pid=
wait "$probe_pid" || { cat "$dir/availability_probe.log" >&2; die "availability probe failed"; }
probe_pid=

log "completed Exp 5; logs and measurements saved under $dir"
