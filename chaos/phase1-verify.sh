#!/usr/bin/env bash
# The Phase 1 "done when": load + chaos, then reconcile, N rounds in a row.
#
# Usage (repo root, stack running):  bash chaos/phase1-verify.sh [rounds] [seconds_per_round]
# Results (k6 summary, chaos log, reconcile output) go to results/phase-1/<date>-m8-round-<n>-*.
# Exits with 1 as soon as a round's reconcile fails.
set -euo pipefail

ROUNDS="${1:-3}"
SECONDS_PER_ROUND="${2:-180}"
VUS="${VUS:-8}"
FAILURE_RATE="${PAYMENT_FAILURE_RATE:-0.2}"
SETTLE_LIMIT_SECONDS=900
OUT="results/phase-1"
DAY="$(date -u +%Y-%m-%d)"
COMPOSE=(docker compose -f deploy/compose/docker-compose.yml)

set -a; . deploy/compose/.env; set +a

log() { echo "$(date -u +%H:%M:%S) $*"; }

# Without the outbox connectors no event leaves the database and every order stays
# PENDING, so the rounds would only measure a broken setup.
check_connectors() {
  for file in deploy/compose/debezium/connectors/*.json; do
    name=$(basename "$file" .json)
    states=$(curl -s --max-time 10 "http://127.0.0.1:8083/connectors/$name/status" \
      | grep -o '"state":"[A-Z_]*"' | sort -u || true)
    if [ "$states" != '"state":"RUNNING"' ]; then
      log "connector $name is not RUNNING (${states:-not registered}); run: docker compose -f deploy/compose/docker-compose.yml up debezium-init"
      exit 1
    fi
  done
  log "all outbox connectors are RUNNING"
}

count_orders() {
  docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" orderflow-postgres-1 psql -U postgres -d orders_db \
    -tAc "SELECT count(*) FROM orders ${1:-}"
}

orders_in_progress() { count_orders "WHERE status IN ('PENDING', 'STOCK_RESERVED')"; }

fail_round() {
  log "round $round: $*"
  "${COMPOSE[@]}" up -d --no-deps --force-recreate payment-service >/dev/null
  exit 1
}

if ! command -v k6 >/dev/null; then
  log "k6 not found on PATH; without load the rounds would check an idle system"
  exit 1
fi
check_connectors

log "payment-service: decline ${FAILURE_RATE} of charges during the rounds"
PAYMENT_FAILURE_RATE="$FAILURE_RATE" "${COMPOSE[@]}" up -d --no-deps --force-recreate payment-service >/dev/null

for round in $(seq 1 "$ROUNDS"); do
  prefix="$OUT/$DAY-m8-round-$round"
  log "round $round: chaos and load for ${SECONDS_PER_ROUND}s"
  orders_before=$(count_orders)
  bash chaos/phase1-kill-random.sh "$SECONDS_PER_ROUND" "$prefix-chaos.log" >/dev/null &
  chaos_pid=$!
  # k6 exits non-zero when a threshold fails (too many failed checks, or a repeated
  # Idempotency-Key that created a second order); both fail the round.
  k6_exit=0
  k6 run --quiet -e BASE_URL=http://127.0.0.1:8080 -e VUS="$VUS" -e DURATION="${SECONDS_PER_ROUND}s" \
    --summary-export "$prefix-k6.json" loadtest/phase1-orders.js >"$prefix-k6.txt" 2>&1 || k6_exit=$?
  wait "$chaos_pid" || true
  [ "$k6_exit" -eq 0 ] || fail_round "k6 FAILED (exit $k6_exit), see $prefix-k6.txt"
  new_orders=$(( $(count_orders) - orders_before ))
  [ "$new_orders" -gt 0 ] || fail_round "no orders were created, the load did not reach the API"
  log "round $round: k6 passed, $new_orders new orders"

  log "round $round: waiting until no order is in progress"
  waited=0
  while [ "$(orders_in_progress)" != "0" ] && [ "$waited" -lt "$SETTLE_LIMIT_SECONDS" ]; do
    sleep 10; waited=$((waited + 10))
  done
  log "round $round: settled after ${waited}s, $(orders_in_progress) still in progress"

  if "${COMPOSE[@]}" --profile tools run --rm reconcile >"$prefix-reconcile.txt" 2>&1; then
    log "round $round: reconcile PASSED"
  else
    fail_round "reconcile FAILED, see $prefix-reconcile.txt"
  fi
done

log "payment-service: back to normal settings"
"${COMPOSE[@]}" up -d --no-deps --force-recreate payment-service >/dev/null
log "all $ROUNDS rounds passed"
