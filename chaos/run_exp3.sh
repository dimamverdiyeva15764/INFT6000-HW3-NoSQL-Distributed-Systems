#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"

usage() {
  cat <<'EOF'
Usage: run_exp3.sh [--variant 3a|3b|3c] [--node cass3] [--rep 1]
                   [--duration seconds] [--fault-after seconds] [--fault-seconds seconds]

3a: kill one node under traffic, observe, then restart it.
3b: kill two nodes under traffic, observe, then restart them.
3c: compare graceful stop/start with kill/start under the same traffic.
EOF
}

variant=3a
node=cass3
rep=1
duration=120
duration_set=false
fault_after=15
fault_seconds=20
while [ "$#" -gt 0 ]; do
  case "$1" in
    --help) usage; exit 0 ;;
    --variant) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; variant="$2"; shift 2 ;;
    --node) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; node="$2"; shift 2 ;;
    --rep) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; rep="$2"; shift 2 ;;
    --duration) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; duration="$2"; duration_set=true; shift 2 ;;
    --fault-after) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; fault_after="$2"; shift 2 ;;
    --fault-seconds) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; fault_seconds="$2"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

case "$variant" in 3a|3b|3c) ;; *) die "variant must be 3a, 3b, or 3c" ;; esac
if [ "$duration_set" = false ] && [ "$variant" = 3c ]; then
  duration=180
fi
validate_node "$node"
[[ "$rep" =~ ^[1-9][0-9]*$ ]] || die "rep must be a positive integer"
[[ "$duration" =~ ^[1-9][0-9]*$ && "$fault_after" =~ ^[0-9]+$ && "$fault_seconds" =~ ^[1-9][0-9]*$ ]] \
  || die "duration and fault times must be integer seconds"
command -v "${PYTHON:-python}" >/dev/null 2>&1 || die "Python is required for chaos.detect_down"

if [ "$variant" = 3c ]; then
  minimum=$((fault_after + 2 * fault_seconds + 45))
else
  minimum=$((fault_after + fault_seconds + 30))
fi
[ "$duration" -ge "$minimum" ] || die "duration must be at least ${minimum}s for this scenario"

bash scripts/wait_for_cluster.sh 3 300
docker compose build client

run_id="exp3-${variant}-${node}-r${rep}-$(stamp)"
dir="results/logs/exp3/$run_id"
mkdir -p "$dir"
log "starting $variant, run $run_id; evidence: $dir"

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
  for node_to_restore in $CORE_NODES; do
    if ! is_running "$node_to_restore"; then
      bash chaos/start_node.sh "$node_to_restore" 300 || \
        log "WARNING: could not restore $node_to_restore during cleanup"
    fi
  done
}
trap cleanup_jobs EXIT INT TERM

docker compose run --rm -T client python -m workload.runner \
  --mode mixed --cl QUORUM --rate 50 --threads 4 --duration "$duration" \
  --exp exp3 --variant "$variant" --rep "$rep" --run-id "$run_id-load" \
  > "$dir/runner.log" 2>&1 &
runner_pid=$!
docker compose run --rm -T client python -m chaos.availability_probe \
  --duration "$duration" --rep "$rep" --run-id "$run_id-probe" \
  > "$dir/availability_probe.log" 2>&1 &
probe_pid=$!
sleep "$fault_after"

run_detection() {
  local target="$1" transition="$2" observer="${3:-}"
  local args=(--node "$target" --transition "$transition" --timeout 120 \
    --output "$dir/detection_times.csv")
  [ -n "$observer" ] && args+=(--observer "$observer")
  "${PYTHON:-python}" -m chaos.detect_down "${args[@]}" >> "$dir/detection.log" 2>&1
}

stop_and_measure() {
  local target="$1" kind="$2" observer="${3:-}"
  if [ "$kind" = graceful ]; then
    bash chaos/stop_node.sh "$target"
  else
    bash chaos/kill_node.sh "$target"
  fi
  run_detection "$target" down "$observer"
}

start_and_measure() {
  local target="$1" observer="${2:-}"
  bash chaos/start_node.sh "$target" 300
  run_detection "$target" up "$observer"
}

if [ "$variant" = 3a ]; then
  stop_and_measure "$node" kill
  sleep "$fault_seconds"
  start_and_measure "$node"
elif [ "$variant" = 3b ]; then
  other=cass2
  [ "$node" = cass2 ] && other=cass3
  stop_and_measure "$other" kill cass1
  stop_and_measure "$node" kill cass1
  sleep "$fault_seconds"
  start_and_measure "$other" cass1
  start_and_measure "$node" cass1
else
  stop_and_measure "$node" graceful
  sleep "$fault_seconds"
  start_and_measure "$node"
  sleep 5
  stop_and_measure "$node" kill
  sleep "$fault_seconds"
  start_and_measure "$node"
fi

wait "$runner_pid" || {
  rc=$?
  if [ "$variant" != 3b ] || [ "$rc" -ne 3 ]; then
    cat "$dir/runner.log" >&2
    die "workload runner failed with exit code $rc"
  fi
  log "runner reported no successful QUORUM operation during the two-node outage (expected)"
}
runner_pid=
wait "$probe_pid" || { cat "$dir/availability_probe.log" >&2; die "availability probe failed"; }
probe_pid=

docker exec cass1 nodetool status > "$dir/final_status.txt" 2>&1
log "completed $variant; logs and detection measurements saved under $dir"
