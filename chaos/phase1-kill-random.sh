#!/usr/bin/env bash
# Chaos for Phase 1: repeatedly kill or pause a random service container, then bring it back.
#
# Usage:  bash chaos/phase1-kill-random.sh [duration_seconds] [log_file]
# Every action is logged with a timestamp. On exit (also Ctrl+C) every target is running again.
set -euo pipefail

DURATION="${1:-120}"
LOG="${2:-chaos-$(date +%Y%m%d-%H%M%S).log}"

# Only the services. Postgres, Kafka, Redis and RabbitMQ stay up: losing them is a different test.
TARGETS=(
  orderflow-order-service-1-1
  orderflow-order-service-2-1
  orderflow-inventory-service-1
  orderflow-payment-service-1
  orderflow-kafka-connect-1
  orderflow-notification-worker-1
  orderflow-search-indexer-1
)

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }

restore_all() {
  for target in "${TARGETS[@]}"; do
    state=$(docker inspect -f '{{.State.Status}}' "$target" 2>/dev/null || echo missing)
    case "$state" in
      paused) docker unpause "$target" >/dev/null && log "restore unpause $target" ;;
      exited|created) docker start "$target" >/dev/null && log "restore start $target" ;;
    esac
  done
}
trap restore_all EXIT

log "chaos start duration=${DURATION}s targets=${#TARGETS[@]}"
end=$((SECONDS + DURATION))
actions=0
while (( SECONDS < end )); do
  target="${TARGETS[RANDOM % ${#TARGETS[@]}]}"
  down=$((3 + RANDOM % 8))
  if (( RANDOM % 2 == 0 )); then
    docker kill "$target" >/dev/null && log "kill $target for ${down}s"
    sleep "$down"
    docker start "$target" >/dev/null && log "start $target"
  else
    docker pause "$target" >/dev/null && log "pause $target for ${down}s"
    sleep "$down"
    docker unpause "$target" >/dev/null && log "unpause $target"
  fi
  actions=$((actions + 1))
  sleep $((5 + RANDOM % 10))
done
log "chaos end actions=$actions"
