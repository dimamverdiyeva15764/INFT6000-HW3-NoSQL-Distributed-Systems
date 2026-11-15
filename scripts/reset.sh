#!/usr/bin/env bash
# Removes all containers and data volumes; results/ is kept.
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

docker compose --profile scale --profile tools down -v --remove-orphans
log "cluster and data volumes removed"
