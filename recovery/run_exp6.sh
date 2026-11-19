#!/usr/bin/env bash
# Experiment 6 - Paxos lightweight transactions. Owner: Habib Hasanov.
# Full sequence: LWT race, plain-INSERT race, LWT vs plain latency, traced LWT,
# then the LWT race with one node down and with two nodes down; nodes are restarted.
source "$(dirname "$0")/../chaos/common.sh"

usage() {
  cat <<'EOF'
Usage: recovery/run_exp6.sh [--rep 1] [--clients 10] [--handles 20] [--n 200] [--skip-faults]

Runs Experiment 6 against the running cluster (make up && make schema first; schema/03_lwt.cql
creates chat.usernames). Steps:
  1 race (LWT)   2 race (plain INSERT)   3 latency LWT vs plain   4 traced LWT
  5 kill cass3 -> race-1down   6 kill cass2 -> race-2down   7 restart cass2, cass3
Raw CSVs: results/raw/exp6/; detail, traces and summaries: results/logs/exp6/.
EOF
}

rep=1
clients=10
handles=20
n=200
faults=true
while [ "$#" -gt 0 ]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --rep) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; rep="$2"; shift 2 ;;
    --clients) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; clients="$2"; shift 2 ;;
    --handles) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; handles="$2"; shift 2 ;;
    --n) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; n="$2"; shift 2 ;;
    --skip-faults) faults=false; shift ;;
    *) usage >&2; die "unknown argument: $1" ;;
  esac
done
[[ "$rep" =~ ^[1-9][0-9]*$ && "$clients" =~ ^[0-9]+$ && "$handles" =~ ^[1-9][0-9]*$ \
   && "$n" =~ ^[1-9][0-9]*$ ]] || die "numeric arguments must be positive integers"

bash scripts/wait_for_cluster.sh 3 300
docker compose build client >/dev/null
if ! docker exec cass1 cqlsh -e "DESCRIBE TABLE chat.usernames" >/dev/null 2>&1; then
  log "chat.usernames missing - applying schema"
  bash scripts/load_schema.sh
fi

run_id="exp6-r${rep}-$(stamp)"
dir="results/logs/exp6/$run_id"
mkdir -p "$dir"
lwt() { docker compose run --rm -T client python -m recovery.lwt_demo "$@"; }
log "Exp 6 run $run_id; evidence: $dir"

restore() {
  local rc=$? n
  for n in cass2 cass3; do
    if ! is_running "$n"; then bash chaos/start_node.sh "$n" 300 || log "WARNING: could not restart $n"; fi
  done
  exit "$rc"
}
trap restore EXIT INT TERM

step() {   # <file> <description> <lwt_demo args...>; a non-zero exit is recorded, not fatal
  local file="$1" what="$2"; shift 2
  log "$what"
  if lwt "$@" 2>&1 | tee "$dir/$file"; then :; else
    log "NOTE: '$what' exited non-zero (see $dir/$file)"
    if grep -q "SAFETY VIOLATIONS: [1-9]" "$dir/$file"; then die "LWT safety violation in '$what'"; fi
  fi
}

step 01_race_lwt.txt   "1/7 LWT race ($clients clients x $handles handles)" \
  race --clients "$clients" --handles "$handles" --variant race --rep "$rep" --run-id "$run_id-race"
step 02_race_plain.txt "2/7 plain-INSERT race" \
  race --clients "$clients" --handles "$handles" --plain --variant plain --rep "$rep" --run-id "$run_id-plain"
step 03_latency.txt    "3/7 LWT vs plain latency (n=$n)" \
  latency --n "$n" --rep "$rep" --run-id "$run_id-latency"
step 04_trace.txt      "4/7 traced LWT (Paxos phases)" \
  trace --run-id "$run_id-trace" --save "$dir/04_paxos_trace.txt"

if [ "$faults" = true ]; then
  bash chaos/kill_node.sh cass3
  wait_for_peer_state cass3 DN 120 || die "peers did not mark cass3 DN"
  docker exec cass1 nodetool status > "$dir/05_status_1down.txt" 2>&1 || true
  step 05_race_1down.txt "5/7 LWT race with cass3 down (2 of 3 replicas = Paxos quorum)" \
    race --clients "$clients" --handles "$handles" --variant race-1down --rep "$rep" --run-id "$run_id-1down"

  bash chaos/kill_node.sh cass2
  wait_for_peer_state cass2 DN 120 || die "cass1 did not mark cass2 DN"
  docker exec cass1 nodetool status > "$dir/06_status_2down.txt" 2>&1 || true
  step 06_race_2down.txt "6/7 LWT race with cass2 and cass3 down (no Paxos quorum)" \
    race --clients "$clients" --handles "$handles" --variant race-2down --rep "$rep" --run-id "$run_id-2down"

  log "7/7 restarting cass2 and cass3"
  bash chaos/start_node.sh cass2 300
  bash chaos/start_node.sh cass3 300
  bash scripts/wait_for_cluster.sh 3 300
fi

log "Exp 6 finished; evidence in $dir"
grep -h -E '^(verdict|handles with|every successful|median ratio|paxos_variant)' "$dir"/*.txt || true
