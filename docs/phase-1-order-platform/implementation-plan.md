# Phase 1 Implementation Plan

9 milestones, M0 to M8. Finish each one, including its tests, before starting the next. Each milestone has:

- **Goal**: what it adds.
- **Tasks**: tick them off as you go.
- **How to test**: commands to prove it works.
- **Done when**: the exact condition for moving on.

For the exact build order, 1 Conventional Commit at a time, follow [commit-plan.md](commit-plan.md).

Read the matching part of [references.md](references.md) before each milestone. Write any decision you make into the decision log in [`PLAN.md`](../../PLAN.md) the same day.

Commands below assume a Bash shell (Git Bash or WSL) from the repository root. `dc` is short for `docker compose -f deploy/compose/docker-compose.yml`:

```bash
alias dc='docker compose -f deploy/compose/docker-compose.yml'
```

---

## M0: Repository skeleton and infrastructure up

**Goal.** The repo layout exists, and all infrastructure containers start and report healthy. No services yet.

**Tasks**

- [ ] Create the folders from [the common architecture, section 14](../common/02-architecture.md#14-repository-layout): `services/`, `deploy/compose/`, `loadtest/`, `chaos/`.
- [ ] Add `.gitignore` (ignore `.env`), `.env.example` with fake values, and a short root `README.md` that links to `docs/`.
- [ ] Use only the generic env var names (`DATABASE_URL`, `REDIS_URL`, `KAFKA_BOOTSTRAP_SERVERS`, `RABBITMQ_URL`, `JOB_BACKEND`, `S3_BUCKET`, `OPENSEARCH_URL`) from [architecture.md, section 13](architecture.md#13-configuration). In compose, give each service its own `DATABASE_URL` value.
- [ ] Write `deploy/compose/docker-compose.yml` with: `postgres`, `redis`, `kafka` (KRaft, single node), `kafka-connect` (Debezium), `kafka-ui`, `rabbitmq`, `opensearch`, `opensearch-dashboards`, `minio` (or your chosen S3 store), `mailpit`. Pin every image version.
- [ ] Add a `healthcheck` to each container.
- [ ] Postgres init script that creates `orders_db`, `inventory_db`, `payments_db`, 1 user per database, and turns on `wal_level=logical`.
- [ ] Bucket init: create `orderflow-invoices` on startup.
- [ ] Kafka topic init: create `orders.events`, `inventory.events`, `payments.events` (several partitions each), plus their `.retry` and `.dlq` topics.

**How to test**

```bash
dc up -d
dc ps                                   # every container shows "healthy"
dc exec postgres psql -U postgres -c '\l'          # 3 databases listed
dc exec postgres psql -U postgres -c 'SHOW wal_level;'   # logical
```

Open Kafka UI (http://localhost:8085), RabbitMQ (http://localhost:15672), the S3 file browser (http://localhost:7888/buckets/) and Mailpit (http://localhost:8025) in a browser.

**Done when.** `dc down -v && dc up -d` gives a fully healthy stack every time, with no manual steps.

---

## M1: inventory-service with Postgres and Redis reservation

**Goal.** Products and stock exist. Stock can be reserved and released safely, even with many requests at once.

**Tasks**

- [ ] FastAPI project in `services/inventory-service/` with `uv`, `ruff`, `pytest`.
- [ ] Alembic migrations for `products`, `stock`, `reservations`, `outbox`, `processed_events`.
- [ ] Seed script with a few products and stock counts.
- [ ] `GET /api/products`, cached in `cache:products` for 60 seconds.
- [ ] On startup, load `stock:{product_id}` keys from Postgres into Redis.
- [ ] Reserve and release Lua scripts (see [architecture.md, section 5](architecture.md#5-stock-reservation-with-redis-and-lua)).
- [ ] A `reserve(order_id, items)` function: Lua first, then the Postgres transaction with `SELECT ... FOR UPDATE`, with the Redis undo if Postgres fails.
- [ ] A `release(order_id)` function, safe to call 2 times.
- [ ] The expired-hold sweeper with `FOR UPDATE SKIP LOCKED`.
- [ ] `/healthz` and `/readyz`.
- [ ] Multi-stage `Dockerfile`, added to compose.
- [ ] Temporary internal endpoints `POST /internal/reserve` and `POST /internal/release` for testing only. M3 replaces them with Kafka events.

**How to test**

```bash
cd services/inventory-service
uv run pytest            # uses Testcontainers for real Postgres and Redis
```

Write these tests:

- [ ] Reserving more than the stock fails and changes nothing.
- [ ] A multi-item reservation where 1 item is short takes nothing.
- [ ] Reserving the same `order_id` 2 times only takes stock once.
- [ ] **Concurrency test:** 50 parallel reservations of 1 unit against a stock of 10. Exactly 10 succeed, and stock ends at 0 in both Redis and Postgres.
- [ ] The sweeper releases an expired hold, and 2 sweepers running together never release the same hold twice.

**Done when.** All tests pass, and the concurrency test passes 10 runs in a row.

---

## M2: order-service API, Idempotency-Key and outbox

**Goal.** Customers can place orders. Each order and its `OrderCreated` event are saved together.

**Tasks**

- [ ] FastAPI project in `services/order-service/`.
- [ ] Migrations for `orders` (with a unique `idempotency_key` column), `order_items`, `outbox`, `processed_events`.
- [ ] `POST /api/orders`: validate input, require `Idempotency-Key`, save the order as `PENDING` and the `OrderCreated` outbox row in 1 transaction, return `202` with the order id.
- [ ] The Redis `idem:{key}` flow (see [architecture.md, section 4](architecture.md#4-idempotency)).
- [ ] `GET /api/orders/{id}`.
- [ ] A shared helper that builds the event envelope (`event_id`, `event_type`, `order_id`, `occurred_at`, `version`, `payload`).
- [ ] Structured JSON logs with `order_id` on every line.
- [ ] Dockerfile, added to compose as `order-service-1` (the second copy comes in M7).

**How to test**

```bash
uv run pytest
KEY=$(uuidgen)
curl -s -X POST localhost:8001/api/orders -H "Idempotency-Key: $KEY" \
  -H 'Content-Type: application/json' -d '{"items":[{"product_id":"<id>","quantity":1}]}'
# send the same request again with the same KEY: same order id back
dc exec postgres psql -U postgres -d orders_db -c 'select count(*) from orders;'
dc exec postgres psql -U postgres -d orders_db -c 'select type, aggregateid from outbox;'
```

Tests to write:

- [ ] Same key 2 times returns the same response and creates 1 order.
- [ ] Missing key returns `400`.
- [ ] If the transaction fails, neither the order nor the outbox row exists.

**Done when.** Every order has exactly 1 `OrderCreated` outbox row, and duplicate requests never create duplicate orders.

---

## M3: Debezium, Kafka and the saga happy path

**Goal.** Outbox rows flow to Kafka, and an order with enough stock moves `PENDING` to `STOCK_RESERVED`. Payment is still a stub.

**Tasks**

- [ ] `deploy/compose/debezium/` with 1 connector JSON file per database and `register-connectors.sh` (reads credentials from env vars, uses `curl` with `--max-time` and a retry limit). The payments connector is added in M4.
- [ ] Confirm `OrderCreated` appears in `orders.events` with `order_id` as the key.
- [ ] A small shared Kafka consumer helper for the Python services: manual offset commit, `processed_events` check, limited retries.
- [ ] inventory-service consumes `OrderCreated`, reserves stock, writes `StockReserved` or `StockRejected`. Remove the temporary internal endpoints.
- [ ] order-service consumes `inventory.events` and moves the order state with conditional updates.
- [ ] `StockRejected` leads to `CANCELLED` and `OrderCancelled`.
- [ ] `StockReserved` leads to `STOCK_RESERVED` and `ChargePaymentRequested`.

**How to test**

```bash
dc up -d debezium-init                               # registers the connectors
curl -s localhost:8083/connectors?expand=status     # every connector RUNNING
# place an order, then:
curl -s localhost:8001/api/orders/<id>               # status STOCK_RESERVED
# place an order for more than the stock:
curl -s localhost:8001/api/orders/<id>               # status CANCELLED
```

In Kafka UI, open `orders.events` and `inventory.events` and follow the events for 1 order.

- [ ] **Duplicate test** and **restart test**: automated in `tests/e2e/test_saga_m3.py`. Run `uv run --all-packages pytest tests/e2e` with the stack running.

**Done when.** The happy path and the "not enough stock" path both work, and duplicates and restarts cause no wrong data.

---

## M4: payment-service in Go, failures and compensation

**Goal.** Payments happen. Failed payments release the stock and cancel the order.

**Tasks**

- [ ] Go module in `services/payment-service/` with `net/http`, `log/slog`, a Kafka client (record the choice in `PLAN.md`), `database/sql` or `pgx`.
- [ ] Migrations for `payments` (unique `order_id` for successful charges), `outbox`, `processed_events`.
- [ ] A fake provider inside the service. `PAYMENT_FAILURE_RATE` (0 to 1) and `PAYMENT_DELAY_MS` env vars control how often it fails and how slow it is. It accepts an idempotency key (the `order_id`).
- [ ] Every call to the fake provider has a `context` with a deadline, and a limited number of retries.
- [ ] Consume `ChargePaymentRequested`, write `PaymentSucceeded` or `PaymentFailed` to the outbox.
- [ ] HTTP server with read, write and idle timeouts, plus `/healthz` and `/readyz`.
- [ ] Multi-stage Dockerfile: build in a Go image, run from a small base image.
- [ ] order-service: `PaymentSucceeded` leads to `CONFIRMED` and `OrderConfirmed`. `PaymentFailed` leads to `ReleaseStockRequested`.
- [ ] inventory-service: `ReleaseStockRequested` releases the stock and writes `StockReleased`.
- [ ] order-service: `StockReleased` leads to `CANCELLED` and `OrderCancelled`.
- [ ] The saga timeout task in order-service for orders stuck in `STOCK_RESERVED`.

**How to test**

```bash
cd services/payment-service && go test ./...
# happy path
PAYMENT_FAILURE_RATE=0 dc up -d payment-service      # place order -> CONFIRMED
# always fail
PAYMENT_FAILURE_RATE=1 dc up -d payment-service      # place order -> CANCELLED, stock back to before
# slow provider
PAYMENT_DELAY_MS=<more than the timeout> dc up -d payment-service   # timeout path works
```

- [ ] After a failed payment, the stock in both Postgres and Redis is the same as before the order.
- [ ] Publishing `ChargePaymentRequested` 2 times creates 1 payment.
- [ ] A payment that arrives after the order timed out is refunded.

All of these are automated in `tests/e2e/test_saga_m4.py`.

**Done when.** Both outcomes work end to end, and no order ever stays in `STOCK_RESERVED` forever.

---

## M5: RabbitMQ jobs, notification-worker, email and invoices

**Goal.** Every confirmed order produces 1 receipt email and 1 PDF invoice.

**Tasks**

- [ ] Declare the exchanges and queues on startup: `notifications.email`, `invoices.generate`, the DLX, and the 2 `.dlq` queues.
- [ ] A `JobPublisher` interface in order-service, chosen by the `JOB_BACKEND` env var. Build only the `rabbitmq` implementation now; any other value fails at startup with a clear error. Phase 5 adds `sqs` (see [architecture.md, section 9](architecture.md#9-from-order-confirmed-to-jobs)).
- [ ] The `order-service-jobs` consumer: read `OrderConfirmed`, publish both jobs through `JobPublisher` (RabbitMQ with publisher confirms), then commit the offset.
- [ ] A unit test with a fake `JobPublisher` that fails, proving the offset is not committed when publishing fails.
- [ ] Add the email dedupe Redis key to the Redis table in [the common architecture](../common/02-architecture.md#9-redis) before you use it.
- [ ] notification-worker in `services/notification-worker/`: manual ack, `prefetch`, limited retries with tenacity, `nack(requeue=False)` when it gives up.
- [ ] Email to Mailpit through SMTP (`SMTP_HOST`, port 1025), with a timeout.
- [ ] PDF invoice (any simple Python PDF library) uploaded to the bucket named in `S3_BUCKET` (`orderflow-invoices` locally) at `invoices/{yyyy}/{mm}/{order_id}.pdf`, with `boto3` timeouts and retry settings.
- [ ] Idempotency: check the S3 object and the email key before doing the work again.

**How to test**

```bash
# place an order that confirms, then:
# Mailpit http://localhost:8025 -> 1 email
# S3 file browser http://localhost:7888/buckets/orderflow-invoices/ -> 1 PDF at the right key
```

- [ ] **DLQ test:** stop Mailpit, place an order. After the retries, the message is in `notifications.email.dlq`. Start Mailpit and replay it with `dc exec notification-worker python -m notification_worker.replay_dlq notifications.email`. The email arrives once.
- [ ] **Duplicate test:** publish the same job 2 times. Still 1 email and 1 PDF.

Both are automated in `tests/e2e/test_jobs_m5.py`.

**Done when.** 1 confirmed order means exactly 1 email and 1 PDF, even with duplicates and a broken email server.

---

## M6: search-indexer and OpenSearch

**Goal.** Orders are searchable, and the index can be changed with no downtime.

**Tasks**

- [ ] Create `orders-v1` with an explicit mapping and the alias `orders` (script in `deploy/compose/opensearch/`).
- [ ] search-indexer in `services/search-indexer/`: consume `orders.events`, upsert 1 document per order (id = `order_id`), using the Bulk API for batches.
- [ ] `GET /api/orders/search?q=` in order-service, querying the alias with a timeout and retry limit.
- [ ] A reindex script: create `orders-v2` with a changed mapping, reindex, switch the alias atomically.
- [ ] A rebuild script: reset the `search-indexer` consumer group to the start of `orders.events` and rebuild the index from all events.

**How to test**

```bash
curl -s 'localhost:8080/api/orders/search?q=<product name>'
sh deploy/compose/opensearch/reindex.sh orders-v1 orders-v2 deploy/compose/opensearch/orders-mapping-v2.json
curl -s localhost:9200/_alias/orders   # points to orders-v2
dc exec search-indexer python -m search_indexer.rebuild orders-v3   # rebuild from Kafka alone
```

- [ ] Run k6 search requests during the reindex (`loadtest/phase1-search.js`). No request fails. Measured result: [results/phase-1](../../results/phase-1/README.md).
- [ ] Delete the index, run the rebuild script, and get the same search results as before.

**Done when.** Search works, a reindex causes 0 failed requests, and the index can be rebuilt from Kafka alone.

---

## M7: nginx load balancer, 2 order-service copies and rate limiting

**Goal.** The API has 1 entry point, survives losing 1 order-service container, and limits abusive clients.

**Tasks**

- [ ] Add `order-service-2` to compose, from the same image as `order-service-1`.
- [ ] nginx on port 8080: an `upstream` with both order-service containers, `max_fails` and `fail_timeout`, proxy timeouts, `X-Forwarded-For`. Route `/api/products` to inventory-service.
- [ ] Token bucket rate limit in order-service with Redis (see [architecture.md, section 6](architecture.md#6-rate-limiting)), returning `429` with `Retry-After`.
- [ ] Check both containers share the Kafka consumer group: in Kafka UI, partitions are split between them.

**How to test**

```bash
for i in $(seq 1 20); do curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/api/orders/<id>; done
dc kill order-service-1
# the same loop still returns 200
dc start order-service-1
# send a burst of POST requests with 1 client id: some return 429
```

**Done when.** Killing either order-service container causes no failed requests after nginx notices, and the rate limit works across both containers.

Automated in `tests/e2e/test_lb_m7.py`; measured numbers are in [results/phase-1](../../results/phase-1/README.md).

---

## M8: Reliability, chaos and load test

**Goal.** Prove with evidence that the system loses nothing and doubles nothing under load and failure.

**Tasks**

- [ ] Retry topic consumers and DLQ handling for every Kafka consumer (see [architecture.md, section 7](architecture.md#7-kafka-retries-and-dead-letters)). Temporary errors go to `.retry`, permanent errors go to `.dlq`.
- [ ] A DLQ replay script: move a chosen message from `.dlq` back to the main topic.
- [ ] `chaos/phase1-kill-random.sh`: in a loop, pick a random container from a list (order-service copies, inventory-service, payment-service, kafka-connect, notification-worker), then `docker kill` or `docker pause` it, wait a short random time, and start it again. Log every action with a timestamp.
- [ ] `reconcile` job (a small Python script run as a compose service) that checks:
  - [ ] Every `CONFIRMED` order has exactly 1 successful payment.
  - [ ] No order has more than 1 successful payment.
  - [ ] Every `CANCELLED` order has 0 successful payments, or 1 refunded payment.
  - [ ] No order is stuck in `PENDING` or `STOCK_RESERVED` after the timeouts have passed.
  - [ ] Stock in Postgres equals starting stock minus confirmed items.
  - [ ] Redis `stock:*` matches Postgres.
  - [ ] Every `CONFIRMED` order has 1 invoice in S3.
  - [ ] It prints counts, and exits with an error if any check fails.
- [ ] `loadtest/phase1-orders.js` (k6): many virtual users placing orders through nginx with unique `Idempotency-Key`s, plus some users who repeat a key on purpose. Start small and increase until you find where it slows down. Do not guess numbers; measure them.
- [ ] Set `PAYMENT_FAILURE_RATE` above 0 during the test, so the compensation path runs too.

**How to test**

```bash
# 1 round by hand:
bash chaos/phase1-kill-random.sh 180 chaos.log &       # chaos in the background
k6 run -e VUS=8 -e DURATION=180s loadtest/phase1-orders.js
wait                                                    # chaos stops by itself
dc --profile tools run --rm reconcile                   # when no order is in progress

# Or the whole "done when" (3 rounds, results saved in results/phase-1/):
bash chaos/phase1-verify.sh 3 180

# Replay Kafka dead letters of 1 group after fixing the cause:
dc exec order-service-1 python -m orderflow_common.replay_kafka_dlq orders.events --group inventory-service
```

**Done when.** The reconcile job passes after a load test with chaos running, at least 3 times in a row. Any failure is investigated and its cause written down, not hidden.

---

## Showcase demo script

A 3 to 5 minute demo to record and to show in the interview:

1. `dc ps`: show every container healthy. Show the architecture diagram.
2. Place 1 order through nginx. Follow it in Kafka UI through `orders.events`, `inventory.events` and `payments.events`. Show the email in Mailpit and the PDF in the S3 file browser. Search for it.
3. Send the same request again with the same `Idempotency-Key`: same order id, still 1 order.
4. Set `PAYMENT_FAILURE_RATE=1`, place an order, show it end `CANCELLED` and the stock back where it was.
5. Start the chaos script and the k6 test together. Show containers being killed.
6. Stop both, run `reconcile`, show 0 lost and 0 duplicate payments.
7. Show 1 message in a DLQ and replay it after a fix.

## Evidence to collect for your CV

Write down only numbers you measured, with the date and the machine you measured on:

| Evidence | Where it comes from |
|---|---|
| Number of orders in the chaos + load run | k6 summary |
| Peak virtual users and requests per second reached | k6 summary |
| p95 and p99 latency of `POST /api/orders` | k6 summary |
| Lost and duplicate payments (target 0 and 0) | reconcile output |
| Number of container kills during the run | chaos script log |
| Failed requests during the reindex (target 0) | k6 during M6 |
| Number of automated tests | `pytest` and `go test` output |

Save the k6 summary, the chaos log and the reconcile output in a `results/phase-1/` folder with the date in the file name. These files are your proof when someone asks "how do you know?".

Next: [Phase 2: GitOps and observability](../phase-2-gitops-observability/README.md).
