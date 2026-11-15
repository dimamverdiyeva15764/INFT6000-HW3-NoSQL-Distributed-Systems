#!/usr/bin/env bash
# Usage: status.sh [label] [output_dir=results/logs]
# Prints cluster state and saves a timestamped copy for the report.
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

label="${1:-status}"
dir="${2:-results/logs}"
mkdir -p "$dir"
out="$dir/$(stamp)_${label}.txt"

{
  echo "# $label  $(ts_utc)"
  echo; echo "## docker compose ps"
  docker compose --profile scale ps --format 'table {{.Name}}\t{{.State}}\t{{.Status}}'
  echo; echo "## nodetool status"
  status_cmd
  echo; echo "## nodetool describecluster"
  nt describecluster
  echo; echo "## nodetool ring (token ownership)"
  nt ring
} 2>&1 | tee "$out"

log "saved $out"
