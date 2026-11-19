#!/usr/bin/env bash
# Experiment 4 - recovery and data reconciliation. Owner: Habib Hasanov.
# Isolates Cassandra's three repair mechanisms after a replica misses writes:
#   4a hinted handoff   coordinators store hints for the dead replica and replay them
#   4b read repair      hints disabled; only keys read at a CL that contacts the stale
#                       replica are repaired (digest mismatch -> blocking read repair)
#   4c anti-entropy     nodetool repair --full: Merkle-tree comparison repairs everything
# Uses Person 3's chaos scripts (kill/start, event log) and Person 2's data-access layer.
source "$(dirname "$0")/../chaos/common.sh"

usage() {
  cat <<'EOF'
Usage: recovery/hints_vs_repair.sh [--variant all|4a|4b|4c] [--node cass3] [--rep 1]
                                   [--rows 5000] [--sample 50] [--hints-wait 15]

Runs Experiment 4 against the running 3-node cluster (make up && make schema first).
  all  (default) baseline repair, then 4a, 4b and 4c in sequence
  4a   hinted handoff only
  4b   read repair with hinted handoff disabled (leaves the replica divergent)
  4c   full anti-entropy repair + convergence verdict (after 4b)

Evidence: results/logs/exp4/<run_id>/ (nodetool outputs, hint timeline, traces,
measurements.csv); raw CSVs: results/raw/exp4/; verdicts: results/logs/exp4/convergence_checks.csv.
Handoff is always re-enabled on exit, and a killed node is restarted.
EOF
}

variant=all
node=cass3
rep=1
rows=5000
sample=50
hints_wait=15
while [ "$#" -gt 0 ]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --variant) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; variant="$2"; shift 2 ;;
    --node) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; node="$2"; shift 2 ;;
    --rep) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; rep="$2"; shift 2 ;;
    --rows) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; rows="$2"; shift 2 ;;
    --sample) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; sample="$2"; shift 2 ;;
    --hints-wait) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; hints_wait="$2"; shift 2 ;;
    *) usage >&2; die "unknown argument: $1" ;;
  esac
done

case "$variant" in all|4a|4b|4c) ;; *) die "--variant must be all, 4a, 4b or 4c" ;; esac
validate_node "$node"
[[ "$rep" =~ ^[1-9][0-9]*$ && "$rows" =~ ^[1-9][0-9]*$ && "$sample" =~ ^[1-9][0-9]*$ \
   && "$hints_wait" =~ ^[0-9]+$ ]] || die "rep, rows, sample and hints-wait must be integers"
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python
command -v "$PY" >/dev/null 2>&1 || die "Python 3 (standard library only) is required on the host"

peers=""
for n in $CORE_NODES; do [ "$n" = "$node" ] || peers="$peers $n"; done
observer="$(echo $peers | awk '{print $1}')"
VC="recovery.verify_convergence"
client() { docker compose run --rm -T client python -m "$@"; }

bash scripts/wait_for_cluster.sh 3 300
docker compose build client >/dev/null

run_id="exp4-${variant}-${node}-r${rep}-$(stamp)"
dir="results/logs/exp4/$run_id"
mkdir -p "$dir" results/raw/exp4
echo "variant,metric,value,unit" > "$dir/measurements.csv"
log "Exp 4 run $run_id (node $node, $rows rows, sample $sample); evidence: $dir"

measure() { echo "$1,$2,$3,$4" >> "$dir/measurements.csv"; }

handoff_all() {   # enablehandoff | disablehandoff | statushandoff on every running node
  local n
  for n in $CORE_NODES; do
    is_running "$n" || continue
    printf '%s: ' "$n"
    docker exec "$n" nodetool "$1" 2>&1 || true
    [ "$1" = statushandoff ] || echo "$1 done"
  done
}

cleanup() {
  local rc=$?
  if ! is_running "$node"; then
    log "cleanup: restarting $node"
    bash chaos/start_node.sh "$node" 300 || log "WARNING: could not restart $node"
  fi
  handoff_all enablehandoff > "$dir/99_handoff_reenabled.txt" 2>&1 || true
  handoff_all statushandoff >> "$dir/99_handoff_reenabled.txt" 2>&1 || true
  log "hinted handoff re-enabled on all nodes"
  exit "$rc"
}
trap cleanup EXIT INT TERM

# Hint files and bytes on one node. Hints are buffered in memory and flushed to
# <data>/hints/*.hints every hints_flush_period (10 s); delivered files are deleted.
hints_stats() {
  docker exec "$1" sh -c 'd=/var/lib/cassandra/hints; [ -d "$d" ] || d=/opt/cassandra/data/hints
    n=0; b=0
    for f in "$d"/*.hints; do [ -e "$f" ] || continue; n=$((n+1)); b=$((b+$(wc -c < "$f"))); done
    echo "$n $b"' 2>/dev/null || echo "0 0"
}

snapshot_hints() {   # <label>: listpendinghints + hint files on every peer
  local p out="$dir/$1.txt"
  : > "$out"
  for p in $peers; do
    { echo "== $p: nodetool listpendinghints"; docker exec "$p" nodetool listpendinghints 2>&1 || true
      echo "== $p: hint files, bytes = $(hints_stats "$p")"; echo; } >> "$out"
  done
  cat "$out"
}

total_hint_bytes() {
  local p f=0 b=0 s
  for p in $peers; do s="$(hints_stats "$p")"; f=$((f + ${s% *})); b=$((b + ${s#* })); done
  echo "$f $b"
}

new_csv() {   # unique results/raw/exp4 path for <variant-label> <cl>
  local base path n=2
  base="results/raw/exp4/exp4_$1_$2_r${rep}_$(date -u +%Y%m%dT%H%MZ)"
  path="$base.csv"
  while [ -e "$path" ]; do path="$base-$n.csv"; n=$((n + 1)); done
  echo "$path"
}

write_rows() {   # <variant> -> sets WRITES (path of the acknowledged-write CSV)
  WRITES="$(new_csv "$1-write" QUORUM)"
  client "$VC" write --n "$rows" --cl QUORUM --variant "$1" --rep "$rep" --run-id "$run_id" \
    --key-prefix "$run_id-$1" --out "$WRITES" | tee "$dir/$1_write.txt"
}

preview() {   # <label> <in-sync|divergent>
  "$PY" -m "$VC" preview --node "$observer" --label "$1" --expect "$2" --run-id "$run_id" \
    --save "$dir/$1_preview.txt" | tee "$dir/$1_preview_verdict.txt" || true
}

read_sample() {   # <writes.csv> <CL> <set> <step> [expect]
  local extra=""
  [ -n "${5:-}" ] && extra="--expect $5"
  # shellcheck disable=SC2086
  client "$VC" read-sample --writes "$1" --cl "$2" --coordinator "$node" --sample "$sample" \
    --set "$3" --step "$4" --rep "$rep" --run-id "$run_id" $extra | tee "$dir/$4.txt" || true
}

wait_serving() {   # all nodes see all nodes UN (also the restarted node's own view) + it answers CQL
  wait_for_all_un 300 || die "not every node reports 3 x UN within 300 s"
  local _
  for _ in $(seq 1 60); do
    if docker exec "$node" cqlsh -e "SELECT release_version FROM system.local" >/dev/null 2>&1; then
      sleep "${SETTLE:-10}"     # let gossip/connections settle before measuring
      log "$node serves CQL and every node reports 3 x UN"
      return 0
    fi
    sleep 2
  done
  die "$node does not answer CQL"
}

kill_and_wait() {
  bash chaos/kill_node.sh "$node"
  wait_for_peer_state "$node" DN 120 || die "peers did not mark $node DN within 120 s"
  log "peers report $node DN"
  docker exec "$observer" nodetool status > "$dir/$1_status_node_down.txt" 2>&1 || true
}

baseline() {
  log "baseline: settings, full repair to a known converged state, clean hints"
  docker exec "$observer" cqlsh -e "SELECT name, value FROM system_views.settings;" 2>&1 \
    | grep -Ei 'hint|read_repair|repair|paxos|gc_grace' > "$dir/00_settings.txt" || true
  docker exec "$observer" nodetool repair --full "$KEYSPACE" > "$dir/00_baseline_repair.txt" 2>&1 \
    || die "baseline repair failed; see $dir/00_baseline_repair.txt"
  preview 00-baseline in-sync
  for n in $CORE_NODES; do docker exec "$n" nodetool truncatehints >/dev/null 2>&1 || true; done
  handoff_all enablehandoff > "$dir/00_handoff_status.txt" 2>&1
  handoff_all statushandoff >> "$dir/00_handoff_status.txt" 2>&1
}

# --------------------------------------------------------------------------- 4a
run_4a() {
  log "4a: hinted handoff (handoff enabled everywhere)"
  handoff_all statushandoff > "$dir/4a_01_handoff_status.txt" 2>&1
  kill_and_wait 4a_02
  write_rows 4a
  W4A="$WRITES"
  log "waiting ${hints_wait}s so buffered hints are flushed to hint files"
  sleep "$hints_wait"
  snapshot_hints 4a_03_pending_hints_before_restart
  local hb
  hb="$(total_hint_bytes)"
  measure 4a hint_files_before_restart "${hb% *}" files
  measure 4a hint_bytes_before_restart "${hb#* }" bytes

  log_event start "$node" "docker start (Exp 4a; measure hint drain)"
  local start_ts="$LAST_EVENT_TS" t0 now el un un_at="" drained_at="" header row p s f tf
  t0="$(date +%s)"
  docker start "$node" >/dev/null
  header="t_s,ts_utc,peer_view_un"
  for p in $peers; do header="$header,${p}_files,${p}_bytes"; done
  echo "$header" > "$dir/4a_hints_timeline.csv"
  while :; do
    now="$(date +%s)"; el=$((now - t0))
    un=0; status_has_node_state "$observer" "$node" UN && un=1
    row="$el,$(ts_utc),$un"; tf=0
    for p in $peers; do s="$(hints_stats "$p")"; f="${s% *}"; tf=$((tf + f)); row="$row,$f,${s#* }"; done
    echo "$row" >> "$dir/4a_hints_timeline.csv"
    if [ -z "$un_at" ] && [ "$un" = 1 ]; then un_at="$el"; log "4a: $node UN after ${el}s"; fi
    if [ -n "$un_at" ] && [ "$tf" -eq 0 ]; then drained_at="$el"; break; fi
    [ "$el" -lt 300 ] || { log "WARNING: hints not drained within 300 s"; break; }
    sleep 1
  done
  measure 4a seconds_start_to_un "${un_at:-}" s
  measure 4a seconds_start_to_hints_drained "${drained_at:-}" s
  [ -n "$un_at" ] && [ -n "$drained_at" ] && measure 4a seconds_un_to_hints_drained "$((drained_at - un_at))" s
  log "4a: hint files drained ${drained_at:-?}s after start (UN at ${un_at:-?}s)"
  wait_for_peer_state "$node" UN 300 || die "$node did not become UN"
  wait_serving
  for p in $peers; do
    echo "== $p"; docker logs --since "$start_ts" "$p" 2>&1 | grep -i 'hint' || echo "(no hint log lines)"
  done > "$dir/4a_04_hint_dispatch_log.txt"
  snapshot_hints 4a_05_pending_hints_after_drain >/dev/null
  preview 4a-after-hints in-sync
  read_sample "$W4A" ONE A 4a-one-after-hints fresh
  "$PY" -m "$VC" full --node "$observer" --label 4a-final --writes "$W4A" --save-dir "$dir" \
    --rep "$rep" --run-id "$run_id" | tee "$dir/4a_99_verdict.txt" || true
}

# --------------------------------------------------------------------------- 4b
run_4b() {
  log "4b: read repair (hinted handoff disabled on${peers})"
  for n in $CORE_NODES; do docker exec "$n" nodetool truncatehints >/dev/null 2>&1 || true; done
  for p in $peers; do docker exec "$p" nodetool disablehandoff; done
  handoff_all statushandoff > "$dir/4b_01_handoff_status.txt" 2>&1
  kill_and_wait 4b_02
  write_rows 4b
  W4B="$WRITES"
  sleep "$hints_wait"
  snapshot_hints 4b_03_pending_hints_no_handoff
  bash chaos/start_node.sh "$node" 300
  wait_serving
  preview 4b-after-restart divergent
  read_sample "$W4B" ONE A 4b-one-before stale        # cass3 serves its own (stale) copy
  read_sample "$W4B" ALL A 4b-all-readrepair          # digest mismatch -> blocking read repair
  read_sample "$W4B" ONE A 4b-one-after-readrepair fresh
  read_sample "$W4B" ONE B 4b-one-control stale       # never read at ALL: still stale
  preview 4b-after-readrepair divergent
}

# --------------------------------------------------------------------------- 4c
run_4c() {
  if [ -z "${W4B:-}" ]; then
    W4B="$(ls -t results/raw/exp4/exp4_4b-write_QUORUM_*.csv 2>/dev/null | head -1 || true)"
    [ -n "$W4B" ] && log "4c: verifying the most recent 4b writes: $W4B"
  fi
  log "4c: anti-entropy repair (nodetool repair --full $KEYSPACE on $node)"
  local t0 t1
  t0="$("$PY" -c 'import time; print(time.time())')"
  docker exec "$node" nodetool repair --full "$KEYSPACE" > "$dir/4c_01_repair.txt" 2>&1 \
    || die "repair failed; see $dir/4c_01_repair.txt"
  t1="$("$PY" -c 'import time; print(time.time())')"
  measure 4c repair_seconds "$("$PY" -c "print(round($t1 - $t0, 2))")" s
  preview 4c-after-repair in-sync
  [ -n "${W4B:-}" ] && read_sample "$W4B" ONE B 4c-one-control fresh
  handoff_all enablehandoff > "$dir/4c_02_handoff_reenabled.txt" 2>&1
  local writes=""
  for w in ${W4A:-} ${W4B:-}; do writes="$writes $w"; done
  # shellcheck disable=SC2086
  if "$PY" -m "$VC" full --node "$observer" --label 4c-final ${writes:+--writes $writes} \
      --save-dir "$dir" --rep "$rep" --run-id "$run_id" | tee "$dir/4c_99_verdict.txt"; then
    FINAL=PASS
  else
    FINAL=FAIL
  fi
}

case "$variant" in
  all) baseline; run_4a; run_4b; run_4c ;;
  4a) baseline; run_4a ;;
  4b) baseline; run_4b ;;
  4c) run_4c ;;
esac

docker exec "$observer" nodetool status > "$dir/zz_final_status.txt" 2>&1 || true
log "Exp 4 ($variant) finished; evidence in $dir"
grep -h -E '^(PREVIEW|READ-SAMPLE|ACKED-CHECK|CONVERGENCE)' "$dir"/*_preview_verdict.txt \
  "$dir"/4*.txt 2>/dev/null | awk '!seen[$0]++' || true
if [ "${FINAL:-}" = FAIL ]; then
  die "convergence verdict FAIL - see $dir/4c_99_verdict.txt"
fi
