# Phase 1 Commit Plan

This is the step by step build order for Phase 1, written as a list of commits. Every step is 1 small commit. Each one says what goes in it and how to check it before you commit.

It follows the milestones in [implementation-plan.md](implementation-plan.md) (M0 to M8). The implementation plan says **what** to build and how to test a milestone. This file says **in what order** to build it, 1 commit at a time.

---

## 1. Commit message rules (Conventional Commits)

Every commit message follows this format:

```
<type>(<scope>): <summary>

<body: optional, explains why>

<footer: optional, for example BREAKING CHANGE: or Refs:>
```

### Types

| Type | Use it for | Example |
|---|---|---|
| `feat` | New behaviour in a service, script or tool | `feat(inventory): add idempotent stock release` |
| `fix` | A bug fix | `fix(order): ignore events for unknown orders` |
| `test` | Adding or changing tests only | `test(inventory): add concurrency test for reservations` |
| `refactor` | Code change with no behaviour change | `refactor(order): split saga handlers into a module` |
| `perf` | Faster or lighter, same behaviour | `perf(search): index documents in bulk batches` |
| `build` | Dockerfiles, Compose, dependencies, build setup | `build(compose): add redis` |
| `ci` | CI pipelines (Phase 2 onwards) | `ci: run tests on pull requests` |
| `docs` | Docs, README, PLAN.md | `docs(plan): record go kafka client choice` |
| `chore` | Repo housekeeping that fits nothing else | `chore: initialize repository` |

### Scopes

Use 1 scope per commit. If a commit touches many areas, leave the scope out.

| Scope | Area |
|---|---|
| `order`, `inventory`, `payment`, `notification`, `search` | The 5 services |
| `common` | The shared Python library `libs/orderflow-common` |
| `compose` | `deploy/compose/docker-compose.yml` and its init files |
| `debezium`, `kafka`, `opensearch`, `nginx` | Config and scripts for that tool |
| `loadtest`, `chaos`, `reconcile` | k6 scripts, chaos scripts, the reconcile job |
| `plan`, `phase1` | `PLAN.md`, Phase 1 docs and results |
| `repo` | Repo-wide config such as git hooks |

### Writing the summary line

- Use the imperative mood: "add", not "added" or "adds". Test: "If applied, this commit will **add redis**."
- Lowercase, no full stop at the end, 72 characters or less.
- Say **what** changed. Put **why** in the body.

### Breaking changes

Add `!` after the scope and a `BREAKING CHANGE:` footer when a commit removes or changes something other parts depend on:

```
refactor(inventory)!: remove temporary internal endpoints

Stock now moves only through Kafka events.

BREAKING CHANGE: POST /internal/reserve and POST /internal/release are removed.
```

### No AI attribution

Commit messages, pull request descriptions, code comments and docs contain **no AI attribution of any kind**: no `Co-Authored-By` lines for AI tools, no "Generated with" lines, no tool names or badges. The commit author is you, and you are responsible for every line.

---

## 2. Git workflow

- `main` always works: the stack starts and all tests pass.
- 1 branch per milestone: `phase1/m0-infra`, `phase1/m1-inventory`, and so on.
- Before each commit, run that service's tests and `ruff check` (Python) or `go vet` and `go test` (Go).
- At the end of a milestone, open a pull request to `main` titled like a commit, for example `feat(inventory): stock reservation service (M1)`. Merge with **rebase and merge**, so every Conventional Commit stays in the history.
- After merging, add an annotated tag: `git tag -a phase1-m1 -m "Phase 1 M1: inventory-service"`.
- When a test finds a bug in work already committed, fix it in a new `fix:` commit. Do not rewrite commits that are already on `main`.

---

## M0: Repository skeleton and infrastructure (branch `phase1/m0-infra`)

**1. `chore: initialize repository`**
- `.gitignore` (`.env`, `.venv/`, `__pycache__/`, `bin/`, `*.pyc`), `.gitattributes` with `* text=auto eol=lf` (shell scripts break inside Linux containers if they have Windows line endings), `.editorconfig`, a short `README.md` linking to `docs/`.
- Check: create a test `.env`, run `git status`, confirm it is not listed.

**2. `docs: add project plan and phase documentation`**
- `PLAN.md` and `docs/`.
- Check: the links in `docs/README.md` open the right files.

**3. `chore(repo): add commit message check hook`**
- `.pre-commit-config.yaml` with a `commit-msg` hook that rejects messages not in Conventional Commits format (for example the `conventional-pre-commit` hook). Install with `pre-commit install --hook-type commit-msg`.
- Check: `git commit --allow-empty -m "bad message"` is rejected; `git commit --allow-empty -m "chore: test hook"` passes (then `git reset HEAD~1`).

**4. `build(compose): add postgres with 3 service databases`**
- `deploy/compose/docker-compose.yml` with `postgres` (pinned tag, healthcheck), an init script creating `orders_db`, `inventory_db`, `payments_db` with 1 user each, `wal_level=logical`. `.env.example` with fake passwords.
- Check: `dc up -d postgres`, then `\l` shows 3 databases and `SHOW wal_level;` returns `logical`.

**5. `build(compose): add redis`**
- Check: `dc exec redis redis-cli ping` returns `PONG`.

**6. `build(compose): add kafka in kraft mode with topic init`**
- Single-node Kafka (KRaft), a 1-shot init container that creates `orders.events`, `inventory.events`, `payments.events` and their `.retry` and `.dlq` topics.
- Check: `dc exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list` shows all 9 topics.

**7. `build(compose): add kafka connect with debezium and kafka ui`**
- Check: `curl -s localhost:8083/connector-plugins` lists the Debezium Postgres connector; Kafka UI opens on port 8085.

**8. `build(compose): add rabbitmq with management ui`**
- Check: UI opens on port 15672.

**9. `build(compose): add opensearch and dashboards`**
- Check: `curl -s localhost:9200` (with the admin password from `.env`) returns cluster info; Dashboards opens on port 5601.

**10. `build(compose): add s3 store with invoice bucket init`**
- MinIO or your chosen S3-compatible store (check image availability first), plus a 1-shot init that creates `orderflow-invoices`.
- Check: the bucket is visible in the console.

**11. `build(compose): add mailpit`**
- Check: UI opens on port 8025.

**12. `docs: add local stack quick start to readme`**
- How to copy `.env.example` to `.env`, start the stack, and open each UI.
- Check: `dc down -v && dc up -d`, then every container is `healthy` with no manual steps.

Tag: `phase1-m0`.

---

## M1: inventory-service (branch `phase1/m1-inventory`)

**1. `feat(common): add shared settings and json logging library`**
- `libs/orderflow-common/` as a small Python package: reads env vars into settings, sets up JSON logs with `service`, `order_id`, `event_id`, `trace_id` fields. Services add it as a path dependency with `uv`.
- Check: `uv run pytest` in `libs/orderflow-common`.

**2. `feat(inventory): scaffold fastapi service with health checks`**
- `uv` project, `ruff`, `pytest`, `/healthz`, `/readyz` (checks Postgres and Redis).
- Check: `uv run pytest`, `uv run ruff check`.

**3. `feat(inventory): add database models and initial migration`**
- Alembic migration for `products`, `stock`, `reservations`, `outbox` (with the empty `traceparent` column), `processed_events`.
- Check: `uv run alembic upgrade head` then `downgrade base` then `upgrade head` all work.

**4. `feat(inventory): add product seed script`**
- Check: running it 2 times does not create duplicates.

**5. `feat(inventory): add cached product list endpoint`**
- `GET /api/products`, cached in `cache:products` for 60 seconds.
- Check: 2nd call within 60 seconds does not hit Postgres (log line or test).

**6. `feat(inventory): load stock counts into redis on startup`**
- Check: `redis-cli get stock:<id>` matches the `stock` table.

**7. `feat(inventory): add lua scripts for atomic reserve and release`**
- Check: unit tests against a real Redis (Testcontainers): not enough stock means nothing changes.

**8. `feat(inventory): reserve stock in redis and postgres with undo`**
- `reserve(order_id, items)`: Lua first, then the Postgres transaction with `SELECT ... FOR UPDATE`, Redis undo if Postgres fails.
- Check: a test that forces the Postgres step to fail and confirms Redis is back to the start value.

**9. `feat(inventory): add idempotent stock release`**
- Check: calling `release` 2 times returns stock once.

**10. `feat(inventory): add expired hold sweeper with skip locked`**
- Check: a test with 2 sweepers running together never releases the same hold twice.

**11. `test(inventory): add concurrency test for parallel reservations`**
- 50 parallel reservations of 1 unit against a stock of 10.
- Check: exactly 10 succeed, stock is 0 in Redis and Postgres, 10 runs in a row.

**12. `build(inventory): add multi-stage dockerfile and compose service`**
- Build context is the repo root, so the image can include `libs/orderflow-common`.
- Check: `dc up -d inventory-service`, `curl localhost:8002/readyz` returns 200.

**13. `feat(inventory): add temporary internal reserve and release endpoints`**
- `POST /internal/reserve`, `POST /internal/release`, for manual testing until M3.
- Check: reserve through curl and see the `hold:{order_id}` key appear.

Tag: `phase1-m1`.

---

## M2: order-service API (branch `phase1/m2-orders`)

**1. `feat(common): add event envelope builder`**
- Builds `event_id`, `event_type`, `order_id`, `occurred_at`, `version`, `payload`.
- Check: unit tests for the envelope shape.

**2. `feat(order): scaffold fastapi service with health checks`**

**3. `feat(order): add order tables and initial migration`**
- `orders` (unique `idempotency_key`), `order_items`, `outbox`, `processed_events`.

**4. `feat(order): create orders with outbox event in one transaction`**
- `POST /api/orders` saves the `PENDING` order and the `OrderCreated` outbox row together, returns `202`.
- Check: a test that makes the outbox insert fail and confirms no order row exists.

**5. `feat(order): require idempotency key and replay stored responses`**
- `400` without the header; the `idem:{key}` flow in Redis.
- Check: same key 2 times returns the same response and 1 order.

**6. `feat(order): add get order endpoint`**

**7. `build(order): add dockerfile and compose service`**
- Compose service `order-service-1`.
- Check: the curl commands in the implementation plan M2.

Tag: `phase1-m2`.

---

## M3: Debezium, Kafka and the saga happy path (branch `phase1/m3-saga`)

**1. `build(debezium): add outbox connector configs and register script`**
- 3 connector JSON files and `register-connectors.sh` (credentials from env vars, `curl --max-time`, limited retries, logs every attempt).
- Check: `curl -s localhost:8083/connectors?expand=status` shows 3 `RUNNING`; an `OrderCreated` appears in `orders.events` keyed by `order_id`.

**2. `feat(common): add kafka consumer with manual commit and dedupe`**
- Manual offset commit after work is saved; `processed_events` check in the same transaction as the work; limited retries.
- Check: a test that delivers the same event 2 times and confirms the handler ran once.

**3. `feat(inventory): reserve stock from order created events`**
- Writes `StockReserved` or `StockRejected` to the outbox.

**4. `refactor(inventory)!: remove temporary internal endpoints`**
- With the `BREAKING CHANGE:` footer shown in section 1.

**5. `feat(order): add saga state machine with conditional updates`**
- Status changes use `UPDATE ... WHERE status = <expected>`, so an old or repeated event cannot move an order backwards.

**6. `feat(order): handle stock reserved and stock rejected events`**
- `StockReserved` leads to `STOCK_RESERVED` and `ChargePaymentRequested`. `StockRejected` leads to `CANCELLED` and `OrderCancelled`.

**7. `test: cover duplicate events and consumer restart`**
- Check: duplicate `OrderCreated` does not change stock; stop inventory-service, place 5 orders, start it, all 5 processed.

Tag: `phase1-m3`.

---

## M4: payment-service and compensation (branch `phase1/m4-payments`)

**1. `docs(plan): record go kafka client and migration tool choices`**
- Write both choices and the reasons in the `PLAN.md` decision log before writing code.

**2. `feat(payment): scaffold go service with http timeouts and health checks`**
- `net/http` server with read, write and idle timeouts, `log/slog` JSON logs.
- Check: `go vet ./...`, `go test ./...`.

**3. `feat(payment): add payment tables and migrations`**
- `payments` (unique `order_id` for successful charges), `outbox`, `processed_events`.

**4. `feat(payment): add fake provider with failure rate and delay`**
- `PAYMENT_FAILURE_RATE` and `PAYMENT_DELAY_MS`; accepts the `order_id` as its idempotency key.

**5. `feat(payment): charge on payment requests with deadline and retries`**
- Consumes `ChargePaymentRequested`, each provider call has a `context` deadline and a retry limit.
- Check: publishing the same request 2 times creates 1 payment.

**6. `build(payment): add multi-stage dockerfile and compose service`**

**7. `feat(order): confirm or compensate on payment result`**
- `PaymentSucceeded` leads to `CONFIRMED` and `OrderConfirmed`. `PaymentFailed` leads to `ReleaseStockRequested`.

**8. `feat(inventory): release stock on release requested events`**
- Writes `StockReleased`.

**9. `feat(order): cancel orders on stock released`**
- `StockReleased` leads to `CANCELLED` and `OrderCancelled`.

**10. `feat(order): time out orders stuck in stock reserved`**

**11. `test: cover payment failure compensation end to end`**
- Check: with `PAYMENT_FAILURE_RATE=1`, the order ends `CANCELLED` and stock in Postgres and Redis is the same as before.

Tag: `phase1-m4`.

---

## M5: Jobs, email and invoices (branch `phase1/m5-jobs`)

**1. `feat(order): add job publisher interface selected by job backend`**
- `JobPublisher` interface; `JOB_BACKEND=rabbitmq` only, any other value stops startup with a clear error.

**2. `feat(order): add rabbitmq job publisher with publisher confirms`**
- Declares `notifications.email`, `invoices.generate`, the dead letter exchange and the 2 `.dlq` queues on startup.

**3. `feat(order): create jobs from order confirmed events`**
- The `order-service-jobs` consumer group; commits the offset only after both jobs are confirmed.

**4. `test(order): keep offset uncommitted when job publish fails`**
- Uses a fake `JobPublisher` that fails.

**5. `feat(notification): scaffold worker with manual ack and retries`**
- `prefetch`, limited retries with `tenacity`, `nack(requeue=False)` when it gives up.

**6. `feat(notification): send receipt emails through smtp`**
- To Mailpit, with a timeout.

**7. `feat(notification): generate pdf invoices and upload to s3`**
- Key `invoices/{yyyy}/{mm}/{order_id}.pdf`, bucket from `S3_BUCKET`, `boto3` timeouts and retry settings.

**8. `feat(notification): skip jobs that were already done`**
- Checks the S3 object and the `notified:{order_id}` Redis key first.

**9. `build(notification): add dockerfile and compose service`**

**10. `test(notification): cover dead letter and duplicate jobs`**
- Check: with Mailpit stopped, the message lands in `notifications.email.dlq`; after replay, the email arrives once. The same job 2 times gives 1 email and 1 PDF.

Tag: `phase1-m5`.

---

## M6: Search (branch `phase1/m6-search`)

**1. `build(opensearch): add orders index mapping and alias script`**
- Creates `orders-v1` and the alias `orders`.

**2. `feat(search): scaffold indexer consuming order events`**

**3. `feat(search): bulk upsert order documents`**
- 1 document per order, id = `order_id`, Bulk API for batches.

**4. `build(search): add dockerfile and compose service`**

**5. `feat(order): add order search endpoint`**
- `GET /api/orders/search?q=`, queries the alias with a timeout and retry limit.

**6. `feat(opensearch): add zero downtime reindex script`**
- Creates `orders-v2`, reindexes, switches the alias in 1 atomic call.

**7. `feat(search): add index rebuild from kafka`**
- Resets the `search-indexer` consumer group to the start and rebuilds.

**8. `test(loadtest): add search load test for reindex`**
- Check: k6 search traffic during a reindex has 0 failed requests.

Tag: `phase1-m6`.

---

## M7: Load balancer and rate limit (branch `phase1/m7-nginx`)

**1. `build(compose): run 2 order-service replicas`**
- Adds `order-service-2` from the same image.
- Check: in Kafka UI, the `order-service` consumer group shows partitions split between the 2.

**2. `feat(nginx): add load balancer with failover`**
- Port 8080, `upstream` with both copies, `max_fails`, `fail_timeout`, proxy timeouts, `X-Forwarded-For`, `/api/products` to inventory-service.
- Check: kill `order-service-1`, the request loop still returns 200.

**3. `feat(order): add redis token bucket rate limit`**
- Returns `429` with `Retry-After`; the counter is in Redis so it works across both copies.
- Check: a burst from 1 client gets some `429`s, spread across both containers.

Tag: `phase1-m7`.

---

## M8: Reliability, chaos and load test (branch `phase1/m8-reliability`)

**1. `feat(common): add retry and dead letter topics to kafka consumer`**
- Temporary errors go to `<topic>.retry`, permanent errors go to `<topic>.dlq`.

**2. `feat(kafka): add dlq replay script`**

**3. `feat(chaos): add random container kill script`**
- `chaos/phase1-kill-random.sh`, logs every action with a timestamp.

**4. `feat(reconcile): add consistency check job`**
- All checks from the implementation plan M8; exits with an error if any fails.

**5. `test(loadtest): add order load test with repeated keys`**
- `loadtest/phase1-orders.js`.

**6. `docs(phase1): record measured load and chaos results`**
- k6 summary, chaos log and reconcile output in `results/phase-1/`, with the date in the file names. Only measured numbers.

**7. `docs(plan): mark phase 1 complete`**
- Update the status in `PLAN.md` and add any final decisions to the log.

Tag: `phase1-done`.

---

## Example of a full commit message

```
feat(inventory): reserve stock in redis and postgres with undo

Redis gives a fast, atomic check so 2 customers cannot take the
last item. Postgres stays the source of truth. If the Postgres
transaction fails after Redis was changed, the Redis change is
undone so both stores agree.

Refs: phase-1 M1
```
