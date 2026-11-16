#!/usr/bin/env bash
# Experiment 2 - consistency tuning (ONE / QUORUM / ALL).
#
# Usage: bash workload/consistency_matrix.sh [--help]      (normally: make exp2)
#
# Runs, through the client container:
#   1. one preload of PRELOAD messages (so reads return data)
#   2. fixed-rate open-loop grid: mode {write, read, mixed} x CL {ONE, QUORUM, ALL}
#      x REPS repetitions, DURATION s each after a WARMUP s warm-up that is not logged;
#      the CL order rotates per repetition so slow drift does not favour one level
#   3. one closed-loop (--max) mixed run per CL to find saturation throughput
#   4. freshness probes for the write/read CL pairs ONE/ONE, ONE/QUORUM,
#      QUORUM/QUORUM, ALL/ONE, ONE/ALL - PROBES probes each, REPS repetitions
#   5. the Exp 2 summary (tables + figures), unless SUMMARY=0
#
# Raw CSVs:   results/raw/exp2/exp2_<variant>_<cl>_r<rep>_<YYYYmmddTHHMMZ>.csv
# Run logs:   results/logs/exp2/<UTC stamp>/ (runner output, docker stats, manifest.csv)
#
# Tunables (environment variables, defaults in brackets):
#   RATE [200] THREADS [8] DURATION [60] WARMUP [10] REPS [3] PRELOAD [10000]
#   MAX_THREADS [32] MAX_DURATION [30] PROBES [2000] PROBE_THREADS [4] SUMMARY [1]
#   QUICK=1  -> dry run of about 4 minutes (DURATION 10, WARMUP 2, REPS 1, PROBES 200 ...)
# shellcheck source=../scripts/common.sh
source "$(dirname "$0")/../scripts/common.sh"

case "${1:-}" in
  -h|--help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  "") ;;
  *) die "unknown argument: $1 (see --help)" ;;
esac

if [ "${QUICK:-0}" = "1" ]; then
  : "${DURATION:=10}" "${WARMUP:=2}" "${REPS:=1}" "${PRELOAD:=1000}" \
    "${PROBES:=200}" "${MAX_DURATION:=10}"
fi
RATE="${RATE:-200}"
THREADS="${THREADS:-8}"
DURATION="${DURATION:-60}"
WARMUP="${WARMUP:-10}"
REPS="${REPS:-3}"
PRELOAD="${PRELOAD:-10000}"
MAX_THREADS="${MAX_THREADS:-32}"
MAX_DURATION="${MAX_DURATION:-30}"
PROBES="${PROBES:-2000}"
PROBE_THREADS="${PROBE_THREADS:-4}"
SUMMARY="${SUMMARY:-1}"

CLS="ONE QUORUM ALL"
MODES="write read mixed"
PROBE_PAIRS="ONE:ONE ONE:QUORUM QUORUM:QUORUM ALL:ONE ONE:ALL"

bash scripts/wait_for_cluster.sh 3 60
keyspace_exists || die "keyspace '$KEYSPACE' missing (run: make schema)"

run="$(stamp)"
dir="results/logs/exp2/$run"
mkdir -p "$dir" results/raw/exp2
manifest="$dir/manifest.csv"
echo "ts_utc,kind,mode,write_cl,read_cl,rep,exit_code,csv,log" > "$manifest"
failures=0
started=$(date +%s)

{
  echo "exp2 run $run started $(ts_utc)"
  echo "RATE=$RATE THREADS=$THREADS DURATION=$DURATION WARMUP=$WARMUP REPS=$REPS PRELOAD=$PRELOAD"
  echo "MAX_THREADS=$MAX_THREADS MAX_DURATION=$MAX_DURATION PROBES=$PROBES PROBE_THREADS=$PROBE_THREADS"
  echo; docker version --format 'docker {{.Server.Version}}' 2>/dev/null || true
  echo; nt status "$KEYSPACE"
} > "$dir/00_parameters.txt" 2>&1

# Background CPU/memory sampling so host saturation can be ruled out afterwards.
(
  echo "ts_utc,container,cpu_percent,mem_usage"
  while :; do
    now="$(ts_utc)"
    docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' 2>/dev/null \
      | sed "s|^|$now,|"
    sleep 5
  done
) > "$dir/docker_stats.csv" &
stats_pid=$!
trap 'kill "$stats_pid" 2>/dev/null || true' EXIT

# runner <kind> <mode> <write_cl> <read_cl> <rep> <args...>
runner() {
  local kind="$1" mode="$2" wcl="$3" rcl="$4" rep="$5"; shift 5
  local logf="$dir/${kind}_${mode}_${wcl}-${rcl}_r${rep}.txt" rc=0 csv
  log "$kind mode=$mode write_cl=$wcl read_cl=$rcl rep=$rep"
  if docker compose run --rm -T client python -m workload.runner \
       --exp exp2 --mode "$mode" --write-cl "$wcl" --read-cl "$rcl" --rep "$rep" --quiet "$@" \
       2>&1 | tee "$logf"; then rc=0; else rc=$?; fi
  csv="$(awk '/^csv:/ {print $2}' "$logf" | tail -1)"
  echo "$(ts_utc),$kind,$mode,$wcl,$rcl,$rep,$rc,${csv:-},$logf" >> "$manifest"
  if [ "$rc" -ne 0 ]; then
    failures=$((failures + 1))
    log "WARNING: run failed with exit code $rc (see $logf)"
  fi
}

# 1. Preload ------------------------------------------------------------------------
log "preloading $PRELOAD messages into 100 rooms"
docker compose run --rm -T client python -m workload.runner \
  --exp exp2 --preload "$PRELOAD" --duration 0 2>&1 | tee "$dir/01_preload.txt"

# 2. Fixed-rate grid ----------------------------------------------------------------
rotate() {  # rotate "A B C" by N positions
  local n="$1"; shift
  local -a a=($*)
  local i out=""
  for i in 0 1 2; do out="$out ${a[$(( (i + n) % 3 ))]}"; done
  echo "$out"
}
for rep in $(seq 1 "$REPS"); do
  for mode in $MODES; do
    for cl in $(rotate $(( rep - 1 )) $CLS); do
      runner grid "$mode" "$cl" "$cl" "$rep" --variant "$mode" \
        --rate "$RATE" --threads "$THREADS" --duration "$DURATION" --warmup "$WARMUP"
    done
  done
done

# 3. Saturation (closed loop) -------------------------------------------------------
for cl in $CLS; do
  runner max mixed "$cl" "$cl" 1 --variant max --max --threads "$MAX_THREADS" \
    --duration "$MAX_DURATION" --warmup 5
done

# 4. Freshness probes ----------------------------------------------------------------
for rep in $(seq 1 "$REPS"); do
  for pair in $PROBE_PAIRS; do
    runner probe probe "${pair%%:*}" "${pair##*:}" "$rep" --variant probe \
      --probes "$PROBES" --threads "$PROBE_THREADS"
  done
done

kill "$stats_pid" 2>/dev/null || true
elapsed=$(( $(date +%s) - started ))
echo
log "Experiment 2 finished in ${elapsed}s: $(( $(wc -l < "$manifest") - 1 )) runs, $failures failed"
log "raw CSVs: results/raw/exp2/   logs + manifest: $dir"

# 5. Summary ------------------------------------------------------------------------
if [ "$SUMMARY" = "1" ]; then
  docker compose run --rm -T client python -m workload.exp2_summary \
    || log "WARNING: summary failed; rerun with: make exp2-report"
fi

[ "$failures" -eq 0 ] || die "$failures run(s) failed - rerun only those cells (see $manifest)"
