# Phase 1 Architecture

This is the design for Phase 1. Names, ports, topics, tables and Redis keys come from [the common architecture](../common/02-architecture.md). This file adds the details you need to build Phase 1.

## 1. Compose topology

Everything runs in 1 Docker Compose project from `deploy/compose/`. All containers share 1 Docker network, so they find each other by service name (for example `postgres:5432`).

```
                     your browser / curl / k6
                              |
                              v
                     +-----------------+
                     |  nginx :8080    |  load balancer
                     +--+-----------+--+
                        |           |
          /api/orders   |           |   /api/products
                        v           v
        +-----------------+   +-----------------+   +-------------------+
        | order-service-1 |   |inventory-service|   |  payment-service  |
        | order-service-2 |   |      :8002      |   |   (Go) :8003      |
        |   :8001 each    |   +---+---------+---+   +----+---------+----+
        +--+-----+-----+--+       |         |            |         |
           |     |     |          |         |            |         |
           |     |     +----------+---> redis :6379      |         |
           |     |                |                      |         |
           |     +--------------> postgres :5432 <-------+         |
           |     orders_db        inventory_db      payments_db    |
           |                      |                                |
           |       +--------------+---------------+                |
           |       | kafka-connect :8083 (Debezium) reads outbox   |
           |       +--------------+---------------+                |
           |                      v                                |
           +-------------> kafka :19092 <--------------------------+
           |                 |        \
           |                 v         \--> search-indexer --> opensearch :9200
           |           kafka-ui :8085                          dashboards :5601
           v
     rabbitmq :5672 ---> notification-worker ---> mailpit :1025 (web :8025)
     (UI :15672)                           \----> s3 :7333 (files :7888)
```

Notes:

- There are **2 order-service containers** (`order-service-1` and `order-service-2`) built from the same image. They are written out as 2 services in the compose file, not with `deploy.replicas`, so nginx has 2 fixed names to balance across and you can kill 1 by name in the chaos test.
- Only nginx (8080) is the real entry point. Ports 8001, 8002 and 8003 are published for debugging only.
- Use `depends_on` with `condition: service_healthy`, so a service starts only after its database, Kafka or RabbitMQ is ready.
- Use the official images where they exist: `postgres`, `redis`, `apache/kafka` (KRaft mode, no ZooKeeper), `quay.io/debezium/connect`, `rabbitmq:<version>-management`, `opensearchproject/opensearch`, `opensearchproject/opensearch-dashboards`, `axllent/mailpit`, `nginx`, and Kafka UI (`kafbat/kafka-ui`). Pin exact versions. Pick a Debezium version whose docs say it supports your Kafka version.
- Avoid Bitnami images and charts. Bitnami changed its free image catalog in 2025.
- MinIO changed how it distributes the community edition in 2025 and no longer publishes images, so the local stack uses **SeaweedFS** for the S3 API (see the decision log in `PLAN.md`). Your code does not change because it talks the S3 API through `boto3`.

### PostgreSQL setup

- 1 container, 3 databases: `orders_db`, `inventory_db`, `payments_db`. Create them with an init SQL script mounted into `/docker-entrypoint-initdb.d/`.
- Each service gets its own database user that can only access its own database.
- Start Postgres with `wal_level=logical`. Debezium needs this to read changes from the write-ahead log (WAL).

### Consumer groups

Each Kafka consumer uses its service name as the consumer group id:

| Consumer group | Reads | Why |
|---|---|---|
| `inventory-service` | `orders.events` | Reacts to `OrderCreated`, `OrderConfirmed` and `ReleaseStockRequested` |
| `payment-service` | `orders.events` | Reacts to `ChargePaymentRequested` and `RefundPaymentRequested` |
| `order-service` | `inventory.events`, `payments.events` | Moves the saga forward |
| `order-service-jobs` | `orders.events` | Turns `OrderConfirmed` into RabbitMQ jobs (see section 9) |
| `search-indexer` | `orders.events` | Keeps OpenSearch up to date |

Both order-service containers join the same group, so Kafka splits the partitions between them. If 1 container dies, the other takes over its partitions.

## 2. The saga in detail

order-service is the **orchestrator**. It stores the order and its status in `orders_db` and decides the next step each time an event arrives. The other services only do their own step and report back.

### States

| Status | Meaning |
|---|---|
| `PENDING` | Order saved, waiting for stock |
| `STOCK_RESERVED` | Stock is held, waiting for payment |
| `CONFIRMED` | Paid. Final state. |
| `CANCELLED` | Stock was not available, or payment failed and stock was released. Final state. |

### Steps

| # | Trigger | Who acts | What happens in 1 database transaction | Event written to outbox |
|---|---|---|---|---|
| 1 | `POST /api/orders` | order-service | Insert `orders` and `order_items` with status `PENDING` | `OrderCreated` |
| 2 | `OrderCreated` | inventory-service | Reserve stock (Redis Lua first, then Postgres, see section 5). Insert `reservations`. | `StockReserved` or `StockRejected` |
| 3a | `StockRejected` | order-service | Status `PENDING` to `CANCELLED` | `OrderCancelled` |
| 3b | `StockReserved` | order-service | Status `PENDING` to `STOCK_RESERVED` | `ChargePaymentRequested` |
| 4 | `ChargePaymentRequested` | payment-service | Call the fake provider. Insert `payments` row. | `PaymentSucceeded` or `PaymentFailed` |
| 5a | `PaymentSucceeded` | order-service | Status `STOCK_RESERVED` to `CONFIRMED` | `OrderConfirmed` |
| 5a+ | `OrderConfirmed` | inventory-service | Reservation `HELD` to `COMMITTED`, so the sweeper never gives sold stock back | none |
| 5b | `PaymentFailed` | order-service | Status stays `STOCK_RESERVED`, mark `cancel_reason` | `ReleaseStockRequested` |
| 6 | `ReleaseStockRequested` | inventory-service | Give the stock back. Mark the reservation released. | `StockReleased` |
| 7 | `StockReleased` | order-service | Status `STOCK_RESERVED` to `CANCELLED` | `OrderCancelled` |
| 8 | `PaymentSucceeded` for an order that is already `CANCELLED` or cancelling (for example after a timeout) | order-service | Nothing changes on the order | `RefundPaymentRequested` |
| 9 | `RefundPaymentRequested` | payment-service | Refund through the fake provider, mark the payment `REFUNDED` | `PaymentRefunded` |

The **compensation** (the undo step) is step 5b to 7: payment failed, so the stock reservation from step 2 is undone.

### Rules that keep the saga safe

- **Only move forward from the expected state.** order-service changes status with a conditional update, for example `UPDATE orders SET status='CONFIRMED' WHERE id=:id AND status='STOCK_RESERVED'`. If 0 rows change, the event is old or a duplicate, so it is ignored and logged.
- **Every handler is idempotent.** See section 4.
- **Timeouts.** If an order stays `STOCK_RESERVED` too long (no payment answer), a small background task in order-service treats it as a payment failure and starts the compensation. The Redis `hold:{order_id}` key also expires after 15 minutes, and inventory-service runs a sweeper that releases expired reservations (section 5). Keep the order timeout shorter than the hold expiry.
- **Payment is never charged twice.** `payments` has a unique constraint on `order_id` for successful charges, and the fake provider is called with `order_id` as its idempotency key.

## 3. Outbox table and Debezium

### The table

Each service database has the same `outbox` table. The column names match what the Debezium Outbox Event Router expects by default:

```sql
CREATE TABLE outbox (
    id            uuid PRIMARY KEY,          -- same value as event_id
    aggregatetype text NOT NULL,             -- 'orders', 'inventory' or 'payments'
    aggregateid   text NOT NULL,             -- the order_id; becomes the Kafka message key
    type          text NOT NULL,             -- event type, e.g. 'StockReserved'
    payload       jsonb NOT NULL,            -- the full event envelope
    traceparent   text,                      -- empty in Phase 1; filled in Phase 2 for tracing
    created_at    timestamptz NOT NULL DEFAULT now()
);
```

The `traceparent` column stays empty in Phase 1. Adding it now means Phase 2 does not need a migration. In Phase 2 it carries the trace id into a Kafka header, so 1 order shows up as 1 trace.

The service writes its data change and the outbox row **in the same transaction**:

```python
with session.begin():                      # 1 transaction
    order.status = "CONFIRMED"
    session.add(OutboxEvent.build("orders", order.id, "OrderConfirmed", payload))
# commit: both are saved, or neither is
```

### Debezium connectors

- 1 connector per database (3 in total), registered through the Kafka Connect REST API on port 8083 by `deploy/compose/debezium/register-connectors.sh`.
- Each connector only watches `public.outbox` (`table.include.list`).
- Each connector uses the Outbox Event Router transform. The idea of the config:

```json
{
  "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
  "plugin.name": "pgoutput",
  "database.hostname": "postgres",
  "database.dbname": "orders_db",
  "database.user": "${env:CDC_ORDERS_DB_USER}",
  "database.password": "${env:CDC_ORDERS_DB_PASSWORD}",
  "table.include.list": "public.outbox",
  "transforms": "outbox",
  "transforms.outbox.type": "io.debezium.transforms.outbox.EventRouter",
  "transforms.outbox.route.by.field": "aggregatetype",
  "transforms.outbox.route.topic.replacement": "${routedByValue}.events"
}
```

With `aggregatetype = 'orders'` the event goes to `orders.events`. The `aggregateid` (order_id) becomes the message key, so all events for 1 order land on the same partition in order. Check every property name against the Debezium docs for the version you pin. Credentials come from environment variables, never from a file in Git.

### Cleaning the outbox

Debezium reads changes from the WAL, not from the table, so old outbox rows are not needed after they are published. A daily cleanup deletes rows older than 7 days. Keeping them for a while helps debugging.

## 4. Idempotency

Messages can arrive more than once (see "at-least-once delivery" in [concepts.md](concepts.md)). Requests can be sent more than once (the customer clicks twice, or the client retries after a timeout). Both must be harmless.

### Consumer side: `processed_events`

```sql
CREATE TABLE processed_events (
    event_id     uuid PRIMARY KEY,
    processed_at timestamptz NOT NULL DEFAULT now()
);
```

Every consumer does this in **1 transaction**:

1. `INSERT INTO processed_events (event_id) VALUES (:id) ON CONFLICT DO NOTHING`.
2. If 0 rows were inserted, this event was already handled: skip it.
3. Otherwise do the work and write any new outbox event.
4. Commit. Then commit the Kafka offset.

If the service crashes after step 4's database commit but before the offset commit, Kafka sends the event again. Step 1 sees it and skips it. Nothing is done twice.

### API side: `Idempotency-Key`

```
client sends POST /api/orders with Idempotency-Key: K
   |
   v
order-service: SET idem:K "IN_PROGRESS" NX EX 86400 in Redis
   |
   +-- key was new --> create the order, store the response under idem:K, return 202
   |
   +-- key existed, value is a stored response --> return the same response again
   |
   +-- key existed, value is IN_PROGRESS --> return 409 (the first request is still running)
```

- Also store the key on the `orders` row with a unique constraint. If Redis is lost, Postgres still blocks a duplicate order.
- A missing `Idempotency-Key` header returns `400`.

## 5. Stock reservation with Redis and Lua

### In plain words

Many customers may try to buy the last item at the same moment. The check "is there enough stock?" and the change "take it" must happen as **1 step** that nobody can interrupt. A Lua script in Redis runs as 1 step: while it runs, no other command touches Redis.

The flow in inventory-service when `OrderCreated` arrives:

1. Run the reserve script in Redis. It checks every item. If all are available, it takes them all and writes `hold:{order_id}` with a 15 minute expiry. If any item is short, it takes nothing.
2. If Redis said no: write `StockRejected` to the outbox. Done.
3. If Redis said yes: in 1 Postgres transaction, lock the stock rows (`SELECT ... FOR UPDATE`), decrease them, insert `reservations`, and write `StockReserved` to the outbox.
4. If the Postgres step fails: run the release script to give the stock back in Redis, then let the message be retried.

Postgres stays the source of truth. Redis is the fast gate in front of it. A reconciliation task can rebuild every `stock:{product_id}` key from Postgres.

### Lua sketch (illustrative)

```lua
-- KEYS: stock:{p1}, stock:{p2}, ..., hold:{order_id}
-- ARGV: qty1, qty2, ..., hold_json, hold_ttl_seconds
local n = #KEYS - 1
if redis.call('EXISTS', KEYS[#KEYS]) == 1 then
  return 1                                   -- already reserved: idempotent
end
for i = 1, n do
  local have = tonumber(redis.call('GET', KEYS[i]) or '0')
  if have < tonumber(ARGV[i]) then
    return 0                                 -- not enough: take nothing
  end
end
for i = 1, n do
  redis.call('DECRBY', KEYS[i], ARGV[i])
end
redis.call('SET', KEYS[#KEYS], ARGV[n + 1], 'EX', ARGV[n + 2])
return 1
```

### Expired holds: the sweeper

A background task in inventory-service releases reservations whose time is up. If you run more than 1 inventory-service later, each copy must take different rows. Use:

```sql
SELECT id FROM reservations
WHERE status = 'HELD' AND expires_at < now()
ORDER BY expires_at
LIMIT 50
FOR UPDATE SKIP LOCKED;
```

`SKIP LOCKED` means "skip rows another worker already locked", so 2 workers never release the same reservation.

## 6. Rate limiting

- Done in order-service, using Redis, because the limit must be shared by both order-service containers. A limit inside nginx or inside 1 container would count each copy separately.
- Algorithm: **token bucket**, implemented as a small Lua script on the key `ratelimit:{client}` (a Redis hash with `tokens` and `updated_at`, expiry 60 seconds).
- The client is identified by the `X-Client-Id` header, or by IP address if it is missing. nginx passes the real IP in `X-Forwarded-For`.
- When the bucket is empty, return `429 Too Many Requests` with a `Retry-After` header.
- Apply it to `POST /api/orders`. Reads can have a looser limit.

## 7. Kafka retries and dead letters

When a consumer cannot process a message (for example the database is down), it must not block the whole partition forever, and it must not lose the message.

```
orders.events --> consumer
                    |  fails
                    v
          retry a few times in memory (short waits, tenacity, limited attempts)
                    |  still fails
                    v
          publish to orders.events.retry  (header: attempt=1, error=..., next_try_at=...)
                    |
          retry consumer waits until next_try_at, tries again
                    |  fails again, attempt < max
                    +--> back to orders.events.retry with attempt+1
                    |  attempt == max
                    v
          publish to orders.events.dlq  (kept for a person to look at)
```

- Only send a message to the retry topic for **temporary** errors (timeouts, connection refused). A **permanent** error (bad JSON, unknown event type) goes straight to `.dlq`. Retrying it would never work.
- The original offset is committed only after the message is either processed, or safely written to `.retry` or `.dlq`.
- Note: moving a message to the retry topic means it can be processed after newer events for the same order. The saga rule "only move forward from the expected state" (section 2) protects against this.
- Look at `.dlq` messages in Kafka UI. A small script can replay a fixed message back to the main topic after you fix the bug.

## 8. Jobs and dead letters in RabbitMQ

| Queue | Settings |
|---|---|
| `notifications.email` | durable, `x-dead-letter-exchange` pointing to the DLX |
| `invoices.generate` | durable, `x-dead-letter-exchange` pointing to the DLX |
| `notifications.email.dlq`, `invoices.generate.dlq` | durable, bound to the DLX |

The worker:

- Uses manual acknowledgements and a small `prefetch` (for example 10), so it does not grab more work than it can finish.
- On success: `ack`.
- On a temporary error: retries in process a few times with tenacity (limited attempts, timeouts on every call).
- When it gives up, or on a permanent error: `nack` with `requeue=False`. RabbitMQ moves the message to the DLX, which routes it to the `.dlq` queue.

The publisher (order-service) uses **publisher confirms**, so it knows RabbitMQ really stored each job.

## 9. From "order confirmed" to jobs

Writing `CONFIRMED` to Postgres and then publishing to RabbitMQ in the same code would be 2 separate writes. If the process crashes between them, the email is never sent. So jobs are created from the event instead:

1. order-service writes `OrderConfirmed` to the outbox (step 5a of the saga).
2. Debezium publishes it to `orders.events`.
3. A small consumer inside order-service (group `order-service-jobs`) reads `OrderConfirmed` and publishes 2 jobs: `notifications.email` and `invoices.generate`.
4. It commits the Kafka offset only after RabbitMQ confirms both jobs.

### Job publishing behind a small interface

In Phase 5 on AWS, these jobs move from RabbitMQ to SQS + Lambda. To make that a small change, order-service never calls RabbitMQ directly. It calls a tiny interface, and an environment variable picks the implementation:

```python
class JobPublisher(Protocol):
    def publish(self, queue: str, job: dict, job_id: str) -> None: ...
    # raises on failure; the caller does not commit the Kafka offset

def make_job_publisher() -> JobPublisher:
    backend = os.environ["JOB_BACKEND"]          # "rabbitmq" or "sqs"
    if backend == "rabbitmq":
        return RabbitMQJobPublisher.from_env()    # Phase 1
    raise ValueError(f"unsupported JOB_BACKEND: {backend}")   # "sqs" is added in Phase 5
```

- Phase 1 only implements `rabbitmq`. Phase 5 adds `sqs` without touching the saga or the consumer code.
- Queue names stay the same logical names (`notifications.email`, `invoices.generate`). Each implementation maps them to its own real queue.
- `job_id` is set from the `event_id`, so any backend can use it for deduplication.

### Duplicates

A crash can cause a job to be published twice. The worker must therefore be idempotent:

- **Invoice:** the S3 key is fixed (`invoices/{yyyy}/{mm}/{order_id}.pdf`). Writing the same PDF again is harmless. The worker can check if the object exists first.
- **Email:** before sending, the worker sets a Redis key for the order's email with `SET ... NX` and a 24 hour expiry. If the key already exists, it skips sending. (This key is not yet in the common Redis table. Add it there before building M5.)

## 10. Search

- search-indexer reads `orders.events` and writes 1 document per order to OpenSearch, using `order_id` as the document id. Writing the same event twice just overwrites the same document.
- Documents are written to the **alias** `orders`, which points to `orders-v1`.
- The mapping is defined up front: `order_id` and `status` as `keyword`, `customer_email` as `keyword`, product names as `text`, `total` as `scaled_float`, `created_at` as `date`.
- Use the Bulk API to write many documents in 1 request.
- **Zero downtime reindex:** create `orders-v2` with the new mapping, copy the data with the Reindex API, then switch the alias in 1 atomic `_aliases` call (remove from v1, add to v2). The app never notices.
- `GET /api/orders/search?q=` in order-service queries the alias with a timeout and a retry limit.

## 11. Invoices in S3 (SeaweedFS locally)

- Bucket: `orderflow-invoices`, created at startup by an init container or a small script. The worker reads the name from `S3_BUCKET`, never from code, because the AWS bucket name is different (Phase 5).
- Key: `invoices/{yyyy}/{mm}/{order_id}.pdf`.
- The worker uses `boto3` with `endpoint_url` set to the local S3 address. The same code works on real S3 in Phase 5 by removing the endpoint.
- Locally, the S3 access keys come from the standard `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` env vars, and `S3_ENDPOINT_URL` points at the local S3 store. On AWS both are left out and an IAM role is used.

## 12. Health checks

| Endpoint | Means | Checks |
|---|---|---|
| `/healthz` | "I am alive" | Only that the process answers. Never checks other services. |
| `/readyz` | "I can serve traffic now" | Its own database, Redis, and Kafka producer are reachable, each with a short timeout |

- Workers without HTTP ports (notification-worker, search-indexer) use a compose `healthcheck` command instead, for example a small script that checks the last successful poll time.
- nginx checks the upstreams passively: if a container stops answering, nginx stops sending it traffic for a while (`max_fails`, `fail_timeout`).

## 13. Configuration

All settings come from environment variables. Compose loads them from a local `.env` file that is **not** committed. A `.env.example` with fake values is committed.

Every service reads the **same generic names** from [the common architecture, section 11b](../common/02-architecture.md#11b-configuration-env-vars). This lets Helm (Phase 2), the operator (Phase 3) and Terraform (Phase 5) inject them the same way. Never use per-service names like `ORDERS_DB_URL`.

| Env var | Phase 1 value (example) | Used by |
|---|---|---|
| `DATABASE_URL` | Each service gets its own: order-service points to `orders_db`, inventory-service to `inventory_db`, payment-service to `payments_db` | order, inventory, payment |
| `REDIS_URL` | `redis://redis:6379/0` | order, inventory, notification-worker |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:19092` | all except notification-worker |
| `RABBITMQ_URL` | from `.env` (contains the password) | order-service, notification-worker |
| `JOB_BACKEND` | `rabbitmq` | order-service (on AWS, Lambda replaces notification-worker) |
| `S3_BUCKET` | `orderflow-invoices` | notification-worker |
| `OPENSEARCH_URL` | `http://opensearch:9200` (no TLS locally) | order-service, search-indexer |

Local-only extras (not needed on AWS, or provided by the platform there):

| Env var | Why |
|---|---|
| `S3_ENDPOINT_URL` | Points `boto3` at the local S3 store (`http://s3:8333` inside Compose). Left empty on AWS, so real S3 is used. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Local S3 credentials, read by `boto3` automatically. On AWS an IAM role replaces them. |
| `SMTP_HOST`, `SMTP_PORT` | Mailpit |
| `PAYMENT_FAILURE_RATE`, `PAYMENT_DELAY_MS` | Fake payment provider controls |
| `HTTP_TIMEOUT_SECONDS`, `MAX_RETRIES` | Timeouts and retry limits |

The Debezium connector credentials (section 3) belong to the Kafka Connect container, not to any service, so they have their own names.

OpenSearch needs an initial admin password from version 2.12 onwards when security is on. The local stack turns the security plugin off (plain HTTP, no login) to keep 1 local node simple. Never do this outside your machine; Phase 2 turns security back on.

## 14. Decisions

| Decision | Why | Trade-off |
|---|---|---|
| Orchestrated saga in order-service | The whole order flow is in 1 place, easy to read and debug | order-service must know every step |
| Outbox + Debezium instead of the service publishing to Kafka directly | A data change and its event can never disagree | Kafka Connect is 1 more thing to run and learn |
| Outbox column names match Debezium defaults | Less config, fewer mistakes | Column names look a bit unusual (`aggregatetype`) |
| `processed_events` table in each database | Duplicate check happens in the same transaction as the work | The table grows; needs a cleanup job |
| Redis Lua as a gate, Postgres row lock as the truth | Fast rejection under heavy load, correct data in Postgres | 2 places to keep in sync, plus a reconciliation task |
| Jobs created from `OrderConfirmed` events, not directly in the saga code | No lost emails or invoices if the service crashes | Small extra delay, and the worker must be idempotent |
| Job publishing behind a `JobPublisher` interface chosen by `JOB_BACKEND=rabbitmq\|sqs` (Phase 1 builds only `rabbitmq`) | Phase 5 can switch to SQS + Lambda by adding 1 class, not rewriting order-service | 1 small extra layer of code |
| Retry topic plus DLQ instead of retrying forever | 1 bad message cannot block a partition | Retried messages can arrive out of order; the saga state checks cover this |
| Rate limit in Redis, not nginx | Shared limit across both order-service containers | 1 Redis call per request |
| 2 named order-service containers instead of `deploy.replicas` | Simple nginx config, easy to kill 1 by name | Slightly longer compose file |
| Fake payment provider with env-controlled failure rate and delay | Safe to break, easy to test the compensation path | Not a real integration |
| Mailpit for email | No real email can leave your machine | Not a real email provider |
