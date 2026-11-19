# Phase 1 References

The official docs to read for Phase 1, which sections matter, and when to read them. Do not read everything first. Read each group just before the milestone that needs it (milestones are in [implementation-plan.md](implementation-plan.md)).

Always read the docs for the **exact version you pin**. Section names and settings change between versions.

## Concepts first (before M0)

| Doc | Read these parts | Why |
|---|---|---|
| **microservices.io** (Chris Richardson) | Pattern pages: Saga, Transactional outbox, Transaction log tailing, Idempotent consumer, Database per service | Short pages that explain the exact patterns you build in Phase 1 |
| **Designing Data-Intensive Applications** (book, Martin Kleppmann) | The chapters on Transactions and on Stream Processing. Chapter numbers differ between editions, so go by title. | Why transactions, isolation and event logs work the way they do |

## Docker and Compose (M0)

| Doc | Read these parts | Why |
|---|---|---|
| **Docker Docs** | Get started; Dockerfile reference; Multi-stage builds; Build cache | Writing small, fast-building images |
| **Docker Compose Docs** | Compose file reference (`services`, `depends_on`, `healthcheck`, `volumes`, `networks`); Networking in Compose; Control startup order | Running the whole stack with 1 command, in the right order |

## Python service basics (M1, M2)

| Doc | Read these parts | Why |
|---|---|---|
| **FastAPI Docs** | Tutorial - User Guide (path operations, request body, dependencies, handling errors); Lifespan Events; Testing; FastAPI in Containers - Docker | The API layer of order-service and inventory-service |
| **SQLAlchemy 2.x Docs** | Unified Tutorial; ORM Quick Start; Session Basics (transactions with `session.begin()`) | Database access with correct transaction handling |
| **Alembic Docs** | Tutorial (create migrations, autogenerate, upgrade) | Versioned database schema changes |
| **Pydantic Docs** | Models; Validators | Request and event validation |
| **HTTPX Docs** | Timeouts; Clients | Every HTTP call needs a timeout |
| **Tenacity Docs** | Stop, wait and retry conditions | Limited retries with backoff |
| **Testcontainers for Python Docs** | PostgreSQL, Redis and Kafka modules | Tests against real Postgres, Redis and Kafka, not mocks |

## PostgreSQL (M1)

| Doc | Read these parts | Why |
|---|---|---|
| **PostgreSQL Docs: Concurrency Control chapter** | Introduction (MVCC); Transaction Isolation; Explicit Locking (row-level locks) | Avoid overselling stock |
| **PostgreSQL Docs: SELECT command reference** | The Locking Clause (`FOR UPDATE`, `SKIP LOCKED`) | The expired-hold sweeper |
| **PostgreSQL Docs: INSERT command reference** | `ON CONFLICT` | The `processed_events` duplicate check |
| **PostgreSQL Docs: Logical Decoding chapter** | Concepts; `wal_level` setting in Server Configuration | What Debezium needs from Postgres (read before M3) |

## Redis (M1, M2, M7)

| Doc | Read these parts | Why |
|---|---|---|
| **Redis Docs** | Data types (strings, hashes); Key expiration (`EXPIRE`, `SET ... EX NX`); Scripting with Lua (`EVAL`, `EVALSHA`); Transactions | Stock reservation, idempotency keys, rate limiting |
| **redis-py Docs** | Connection pools; timeouts; `register_script` | Calling Redis and Lua scripts from Python |

## Kafka (M3)

| Doc | Read these parts | Why |
|---|---|---|
| **Apache Kafka Docs** | Introduction; Quickstart; Design (Persistence, Producer, Consumer, Message Delivery Semantics); Configuration (producer and consumer configs: `acks`, `enable.idempotence`, `enable.auto.commit`, `auto.offset.reset`); KRaft in the Operations section | How topics, partitions, offsets and delivery guarantees really work |
| **confluent-kafka-python Docs** | Producer; Consumer; manual commit; error handling | The Python Kafka client |
| **Kafka UI (kafbat) README** | Docker setup, connecting to a cluster | Seeing topics, messages and lag in a browser |

## Debezium (M3)

| Doc | Read these parts | Why |
|---|---|---|
| **Debezium Docs: Tutorial** | The whole tutorial | See CDC working end to end before writing your own config |
| **Debezium Docs: PostgreSQL connector** | Overview; Setting up PostgreSQL (`pgoutput`, permissions); Connector properties (`table.include.list`) | Reading the outbox tables |
| **Debezium Docs: Outbox Event Router** | Whole page (table columns, `route.by.field`, `route.topic.replacement`, header placement) | Turning outbox rows into clean Kafka events |
| **Kafka Connect section of the Kafka Docs** | REST API | Registering and checking connectors |

## Go (M4)

| Doc | Read these parts | Why |
|---|---|---|
| **A Tour of Go** | All of it | Go basics |
| **Effective Go** | Errors, concurrency, interfaces | Writing Go the way Go developers expect |
| **Go standard library: `net/http`, `context`, `database/sql`, `log/slog`** | Package docs on pkg.go.dev | HTTP server with timeouts, cancellation, database access, structured logs |
| **Go Docs: "Tutorial: Accessing a relational database"** | Whole tutorial | First steps with SQL in Go |
| **confluent-kafka-go or franz-go Docs** | Producer and consumer examples | Kafka from Go. Pick 1 and note the choice in `PLAN.md`. |

## RabbitMQ (M5)

| Doc | Read these parts | Why |
|---|---|---|
| **RabbitMQ Tutorials (Python)** | Tutorials 1 to 4 (hello world, work queues, publish/subscribe, routing) | The basic model: exchanges, queues, bindings |
| **RabbitMQ Docs: Consumer Acknowledgements and Publisher Confirms** | Whole page | Not losing jobs on either side |
| **RabbitMQ Docs: Dead Letter Exchanges** | Whole page | The `.dlq` queues |
| **RabbitMQ Docs: Reliability Guide** | Whole page | How failures happen and how to survive them |
| **pika Docs** (or aio-pika) | Blocking connection, channel, `basic_qos` | The Python client |

## S3 and email (M5)

| Doc | Read these parts | Why |
|---|---|---|
| **boto3 Docs: S3 client** | `put_object`, `head_object`, `get_object`; Configuration (`endpoint_url`, timeouts, retries) | Writing invoices |
| **SeaweedFS Wiki** (on GitHub) | Running `weed server` with S3, S3 credentials, creating buckets | Local S3. See the note on MinIO in [architecture.md](architecture.md). |
| **Mailpit Docs** | Docker setup; SMTP settings | A fake inbox so no real email is sent |

## OpenSearch (M6)

| Doc | Read these parts | Why |
|---|---|---|
| **OpenSearch Docs** | Getting started; Mappings and field types; Query DSL (match, term, bool); Bulk API; Index aliases; Reindex API | Building and changing the search index |
| **OpenSearch Docs: Docker install** | Docker Compose example; initial admin password | Running it locally |
| **opensearch-py Docs** | Client setup with timeouts; bulk helpers | Python client |

## nginx (M7)

| Doc | Read these parts | Why |
|---|---|---|
| **nginx Docs: HTTP Load Balancing** (admin guide) | Upstream groups; load balancing methods; passive health checks (`max_fails`, `fail_timeout`) | Spreading traffic over the 2 order-service containers |
| **nginx Docs: `ngx_http_proxy_module`** | `proxy_pass`, timeouts, `proxy_set_header` | Passing the client IP and setting timeouts |

## Reliability and testing (M8)

| Doc | Read these parts | Why |
|---|---|---|
| **k6 Docs** | Get started; Scenarios; Thresholds; Checks | The concurrent order load test |
| **Docker CLI reference** | `docker kill`, `docker stop`, `docker pause` | The chaos script |
| **Kafka Docs** | `kafka-consumer-groups.sh` tool (in the Operations section) | Checking consumer lag and resetting offsets for replay |
