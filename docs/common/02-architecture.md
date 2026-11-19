# OrderFlow Architecture

This is the main reference for the whole system. Every phase doc uses the names, ports, topics and tables defined here. If you need to change one of them, change it here first and write the reason in the decision log in [`PLAN.md`](../../PLAN.md).

## 1. What the system does

A customer places an order for some products. The system must:

1. Save the order.
2. Hold (reserve) the stock so nobody else can buy the same items.
3. Take the payment.
4. Confirm the order, or undo everything if any step fails.
5. Send an email receipt and create a PDF invoice.
6. Make the order searchable.

It must do this correctly even when services crash, messages arrive twice, or the payment provider is slow.

## 2. The full picture

```
                         +-------------------+
   Customer  ---------->  |  Load Balancer    |   nginx (Phase 1), Gateway API (Phase 2), ALB (Phase 5)
                         +---------+---------+
                                   |
             +---------------------+----------------------+
             |                     |                      |
     +-------v-------+    +--------v--------+    +--------v--------+
     | order-service |    |inventory-service|    | payment-service |
     |   (Python)    |    |    (Python)     |    |      (Go)       |
     +---+---+---+---+    +----+-------+----+    +----+-------+----+
         |   |   |             |       |              |       |
         |   |   |        Redis (stock holds)         |       |
         |   |   |             |       |              |       |
     orders_db    |       inventory_db  |         payments_db  |
     (+ outbox)   |       (+ outbox)    |         (+ outbox)   |
         |        |            |        |              |       |
         +--------+------------+--------+--------------+-------+
                  |   Debezium reads each outbox table
                  v
          +---------------+        +--------------------+
          |     Kafka     | -----> |  search-indexer    | ---> OpenSearch
          |  (events)     |        |    (Python)        |
          +-------+-------+        +--------------------+
                  |
                  | order-service-jobs consumer turns OrderConfirmed into jobs
                  v
          +---------------+        +--------------------+
          |   RabbitMQ    | -----> | notification-worker| ---> Mailpit (fake email)
          |   (jobs)      |        |    (Python)        | ---> S3 / MinIO (PDF invoices)
          +---------------+        +--------------------+

  Watching everything (Phase 2): OpenTelemetry Collector -> Prometheus, Loki, Jaeger -> Grafana
  Guarding everything (Phase 4): runtime-sentinel (eBPF) on every node -> Kafka -> OpenSearch
```

## 3. Services

| Service | Language | Port | Owns | Job |
|---|---|---|---|---|
| `order-service` | Python (FastAPI) | 8001 | `orders_db` | Public API for orders. Runs the saga (the step by step order flow). |
| `inventory-service` | Python (FastAPI) | 8002 | `inventory_db`, Redis keys `stock:*` | Products and stock. Reserves and releases stock. |
| `payment-service` | Go | 8003 | `payments_db` | Charges and refunds through a fake payment provider that can be told to fail or be slow. |
| `notification-worker` | Python | none (worker) | nothing | Sends receipt emails to Mailpit and writes PDF invoices to S3. |
| `search-indexer` | Python | none (worker) | OpenSearch index `orders` | Reads order events from Kafka and keeps the search index up to date. |

Rule: **each service owns its own database.** No service reads another service's tables. They talk only through HTTP calls and events.

## 4. Public API (through the load balancer on port 8080)

| Method and path | Service | What it does |
|---|---|---|
| `POST /api/orders` | order-service | Place an order. Needs an `Idempotency-Key` header so a retried request never creates 2 orders. Returns `202 Accepted` with the order id. |
| `GET /api/orders/{id}` | order-service | Order details and status |
| `GET /api/orders/search?q=` | order-service | Searches OpenSearch |
| `GET /api/products` | inventory-service | Product list with stock. Cached in Redis. |
| `GET /healthz`, `GET /readyz` | every HTTP service | Liveness and readiness checks |
| `GET /metrics` | every service | Prometheus metrics (Phase 2) |

## 5. The order flow (saga)

The order-service is the **orchestrator**: it keeps a small state machine for each order in `orders_db` and decides the next step.

```
PENDING
  | order-service emits OrderCreated
  v
inventory-service reserves stock ----- fails ----> StockRejected ----> order CANCELLED
  | StockReserved
  v
payment-service charges -------------- fails ----> PaymentFailed
  | PaymentSucceeded                                   |
  v                                                    v
order CONFIRMED                 order-service emits ReleaseStockRequested
  |                                      inventory-service emits StockReleased
  | RabbitMQ jobs: send email,            order CANCELLED
  | generate invoice
  v
done
```

Order statuses: `PENDING`, `STOCK_RESERVED`, `CONFIRMED`, `CANCELLED`.

## 6. Events (Kafka)

All events are written to an **outbox table** in the same database transaction as the data change. Debezium reads the outbox tables and publishes the events to Kafka. This means "data saved" and "event sent" can never disagree.

| Topic | Producer | Events | Main consumers |
|---|---|---|---|
| `orders.events` | order-service | `OrderCreated`, `OrderConfirmed`, `OrderCancelled`, `ReleaseStockRequested`, `ChargePaymentRequested`, `RefundPaymentRequested` | inventory-service, payment-service, search-indexer |
| `inventory.events` | inventory-service | `StockReserved`, `StockRejected`, `StockReleased` | order-service |
| `payments.events` | payment-service | `PaymentSucceeded`, `PaymentFailed`, `PaymentRefunded` | order-service |
| `<topic>.retry` | consumers | failed messages waiting for another try | the same consumer |
| `<topic>.dlq` | consumers | messages that failed too many times | a person, through Kafka UI |
| `security.events` | runtime-sentinel (Phase 4) | process, file and network events | detection-service |

Message key: the `order_id`, so all events for 1 order go to the same partition and stay in order.

Consumer group ids are the service names: `order-service`, `inventory-service`, `payment-service`, `search-indexer`. There is 1 extra group, `order-service-jobs`, which reads `OrderConfirmed` and creates the RabbitMQ jobs. Phase 2 (KEDA lag scaling) uses the same ids.

Each group (except search-indexer) also has a retry group, `<group>.retry`, that reads `<topic>.retry`. Retry and dead letter messages carry the failing group in the `x-consumer-group` header, so groups that share a topic never handle each other's retries.

Every event has the same envelope:

```json
{
  "event_id": "uuid",
  "event_type": "StockReserved",
  "order_id": "uuid",
  "occurred_at": "2026-11-18T10:00:00Z",
  "version": 1,
  "payload": { }
}
```

## 7. Jobs (RabbitMQ)

| Queue | Producer | Consumer | Dead letter queue |
|---|---|---|---|
| `notifications.email` | order-service (`order-service-jobs` consumer) | notification-worker | `notifications.email.dlq` |
| `invoices.generate` | order-service (`order-service-jobs` consumer) | notification-worker | `invoices.generate.dlq` |

Jobs are created from the `OrderConfirmed` event, not directly inside the saga code. If the saga saved the order and then published to RabbitMQ in a separate step, a crash between the 2 steps would lose the job (this is called a **dual write**). Reading the event from Kafka makes the job creation safe to retry.

Kafka is for **facts** ("this happened"), which many services may want to read. RabbitMQ is for **work** ("please do this"), which 1 worker should do once.

order-service publishes jobs through a small interface chosen by the env var `JOB_BACKEND=rabbitmq|sqs`. Phases 1 to 4 use `rabbitmq`. Phase 5 adds `sqs`, where the queues are named `orderflow-dev-notifications-email` and `orderflow-dev-invoices-generate` (SQS names cannot contain dots), each with a `-dlq` queue, and Lambda does the work.

## 8. Databases (PostgreSQL)

1 PostgreSQL server, 3 separate databases:

| Database | Main tables |
|---|---|
| `orders_db` | `orders`, `order_items`, `outbox`, `processed_events` |
| `inventory_db` | `products`, `stock`, `reservations`, `outbox`, `processed_events` |
| `payments_db` | `payments`, `outbox`, `processed_events` |

- `outbox`: events waiting to be published (read by Debezium).
- The `outbox` table has a `traceparent` column. It is empty in Phase 1 and carries the trace id into Kafka from Phase 2.
- `processed_events`: ids of events already handled. A consumer checks this table first, so a duplicate event is ignored. This is what makes consumers **idempotent**.

## 9. Redis

| Key pattern | Used by | What it holds | Expires |
|---|---|---|---|
| `stock:{product_id}` | inventory-service | Available stock count, changed only through a Lua script | no |
| `hold:{order_id}` | inventory-service | Reserved items for an order | 15 minutes |
| `cache:products` | inventory-service | Cached product list | 60 seconds |
| `idem:{key}` | order-service | Response for an `Idempotency-Key` | 24 hours |
| `ratelimit:{client}` | order-service | Request counter for rate limiting | 60 seconds |
| `notified:{order_id}` | notification-worker | `sending` while 1 worker sends the receipt (claim, 2 minutes), then `sent`, so a repeated job does not send it twice | 2 minutes while sending, then 24 hours |

PostgreSQL is the source of truth. Redis is fast but can be rebuilt from PostgreSQL if it is lost.

## 10. Search (OpenSearch)

- Index `orders-v1`, reached through the alias `orders`. The app always uses the alias, so you can reindex into `orders-v2` and switch the alias with zero downtime (`deploy/compose/opensearch/reindex.sh`).
- search-indexer writes each document with the event time as an `external_gte` version, so a late or repeated event never overwrites newer data.
- The whole index can be rebuilt from Kafka alone (`python -m search_indexer.rebuild <new-index>`), because `orders.events`, `inventory.events` and `payments.events` keep every event (`retention.ms=-1`).
- Phase 4 adds 1 index per day named `security-events-YYYY.MM.DD`. An ISM policy deletes each index after 7 days.

## 11. Files (S3, MinIO locally)

| Bucket | Content |
|---|---|
| `orderflow-invoices` | PDF invoices, key `invoices/{yyyy}/{mm}/{order_id}.pdf` |

MinIO changed how its community edition is distributed in 2025, so a prebuilt image may not exist for the version you want. Check before you pin a version. Any S3-compatible store works, because the app only uses the S3 API.

On AWS (Phase 5) the bucket is `orderflow-dev-invoices-<account-id>`, because S3 bucket names must be unique across all AWS accounts. The app reads the bucket name from the env var `S3_BUCKET`, so nothing else changes.

## 11b. Configuration (env vars)

Every service reads the same generic names, so the Phase 3 operator, Helm and Terraform can inject them the same way:

| Env var | Meaning |
|---|---|
| `DATABASE_URL` | This service's own database (each service gets a different value) |
| `REDIS_URL` | Redis connection |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka brokers |
| `RABBITMQ_URL` | RabbitMQ connection (when `JOB_BACKEND=rabbitmq`) |
| `JOB_BACKEND` | `rabbitmq` or `sqs` |
| `S3_BUCKET` | Invoice bucket name |
| `OPENSEARCH_URL` | OpenSearch endpoint |
| `FAULT_ERROR_RATE` | order-service only, dev only: share of requests (0 to 1) that return 500 on purpose, for SLO and canary demos. Default 0. |

## 11c. Kubernetes namespaces (Phase 2 onwards)

| Namespace | What runs there |
|---|---|
| `dev`, `staging`, `prod` | The OrderFlow services, 1 copy per environment |
| `data` | CloudNativePG Postgres, Redis, RabbitMQ, OpenSearch, MinIO (shared by all environments to save RAM) |
| `kafka` | Strimzi Kafka and Kafka Connect with Debezium |
| `monitoring` | Prometheus, Alertmanager, Grafana, Loki, Jaeger, OpenTelemetry Collector |
| `cert-manager` | cert-manager |
| `argocd` | Argo CD |
| `envoy-gateway-system` | Envoy Gateway (the load balancer inside the cluster) |
| `keda`, `chaos-mesh`, `cnpg-system`, `rabbitmq-system` | Operators and tools, each in its default namespace |

Because `data` and `kafka` are shared, all environments use the same topics, consumer groups and databases. **Run only 1 environment's apps at a time** (scale the others to 0). Otherwise `dev` and `prod` would read each other's events.

## 12. Local ports (Phase 1, Docker Compose)

| Port | What |
|---|---|
| 8080 | nginx load balancer (the only entry for the API) |
| 8001, 8002, 8003 | order, inventory, payment services (for debugging only) |
| 15432 | PostgreSQL (from your machine; containers use `postgres:5432`) |
| 6379 | Redis |
| 29092 | Kafka (from your machine; containers use `kafka:19092`) |
| 8083 | Kafka Connect (Debezium) |
| 8085 | Kafka UI |
| 5672, 15672 | RabbitMQ, RabbitMQ management UI |
| 9200, 5601 | OpenSearch, OpenSearch Dashboards |
| 7333, 7888 | S3 API, S3 file browser (SeaweedFS) |
| 1025, 8025 | Mailpit SMTP, Mailpit web UI (fake inbox, no real email leaves your machine) |

## 13. How the system grows phase by phase

| Phase | What is added | Where it runs |
|---|---|---|
| 1 | The 5 services and all data stores | Docker Compose on your machine |
| 2 | Helm chart, Argo CD, GitHub Actions, Prometheus, Grafana, Loki, OpenTelemetry, Jaeger, KEDA, chaos tests | kind (local Kubernetes) |
| 3 | `appstack-operator`: 1 YAML file creates a full app environment | kind |
| 4 | `runtime-sentinel` eBPF agent and `detection-service` | kind on a Linux kernel with BTF |
| 5 | The same services on AWS: ECS Fargate, ALB, CloudFront, WAF, RDS, ElastiCache, S3, SQS, Lambda | AWS, built with Terraform (1 module also in CDK) |

Phase 5 limits, chosen to control cost: jobs run on SQS + Lambda instead of RabbitMQ, Kafka is a single demo broker on ECS (Amazon MSK is the production answer), and OpenSearch is off by default in dev, so search-indexer runs with 0 tasks.

## 14. Repository layout

1 repository for the whole product:

```
orderflow/
  PLAN.md                      plan and decision log
  docs/                        these docs
  libs/
    orderflow-common/          shared Python code: settings, JSON logs, event envelope, Kafka consumer
  services/
    order-service/             Python
    inventory-service/         Python
    payment-service/           Go
    notification-worker/       Python
    search-indexer/            Python
    detection-service/         Phase 4
  deploy/
    compose/                   Phase 1: docker-compose.yml, nginx, Debezium connector configs
    kind/                      Phase 2: kind cluster config
    helm/                      Phase 2: charts
    argocd/                    Phase 2: Argo CD applications
    observability/             Phase 2: dashboards, alert rules, Collector config
  platform/
    appstack-operator/         Phase 3: Go operator
  security/
    runtime-sentinel/          Phase 4: eBPF C + Go agent
  infra/
    terraform/                 Phase 5
    cdk/                       Phase 5: 1 module rebuilt in CDK
  loadtest/                    k6 scripts
  chaos/                       chaos experiments
  .github/workflows/           CI
```

## 15. Key decisions

| Decision | Why | What we gave up |
|---|---|---|
| Orchestrated saga in order-service | The whole flow is in 1 place, easy to follow and debug | order-service knows about every step |
| Transactional outbox + Debezium | A data change and its event can never disagree | 1 more moving part (Kafka Connect) |
| Kafka for events, RabbitMQ for jobs | Each is used for what it does best, and you learn the difference | 2 brokers to run |
| 1 database per service | Services can change their tables without breaking others | No SQL joins across services |
| PostgreSQL is the truth, Redis is a helper | Redis can lose data on restart; Postgres does not | Need code to rebuild Redis state |
| payment-service in Go | Practice Go before the operator (Phase 3) and the eBPF agent (Phase 4) | 2 languages in 1 project |
| Fake payment provider and Mailpit | No real money, no real emails, safe to break | Not a real integration |
