# OrderFlow Plan

OrderFlow is a personal hands-on project to build real experience with the stack used by modern backend and platform teams. Full docs are in [`docs/`](docs/README.md).

## Goal

Build, deploy, observe, secure and run on AWS a small event-driven ordering system, so every tool in the target stack has been used for a real purpose.

## Phases

| Phase | Name | Status |
|---|---|---|
| 1 | [Order platform](docs/phase-1-order-platform/README.md) | In progress: M0 to M8 built; the M8 verification found 2 open bugs (see decision log) |
| 2 | [GitOps and observability](docs/phase-2-gitops-observability/README.md) | In progress (started before Phase 1 was done, see decision log) |
| 3 | [Kubernetes operator](docs/phase-3-kubernetes-operator/README.md) | Not started |
| 4 | [eBPF security agent](docs/phase-4-ebpf-security-agent/README.md) | Not started |
| 5 | [AWS with Terraform](docs/phase-5-aws-terraform/README.md) | Not started, needs a written AWS budget first |

## Decision log

| Date | Who | Decision | Why |
|---|---|---|---|
| 2026-11-18 | Keshan | Build 5 phases in this order: order platform, GitOps and observability, operator, eBPF agent, AWS | Each phase needs the one before it: the app first, then Kubernetes, then extending Kubernetes, then the kernel, then the cloud |
| 2026-11-18 | Keshan | Working name "OrderFlow", 1 repository for all phases | All phases, docs and history stay in 1 place |
| 2026-11-18 | Keshan | Python for services, Go for payment-service, operator and eBPF agent | Python is the main backend language. Go is needed for the operator and eBPF phases. |
| 2026-11-18 | Keshan | Everything runs locally until Phase 5 | No spend without a written budget (spend rule in docs/common/08-cost-and-safety.md) |
| 2026-11-19 | Keshan | Conventional Commits for every commit, checked by a commit-msg hook | Readable history, and a clear record of what changed and why |
| 2026-11-19 | Keshan | No AI attribution in commits, pull requests, code comments or docs | The author is responsible for every line |
| 2026-11-19 | Keshan | Repository hosted at github.com/keshan-dev/orderflow (personal account) | Personal skills project |
| 2026-11-19 | Keshan | Docker has about 3.9 GB of RAM on the dev machine (7.7 GB host). Every container gets a memory limit and small Java heaps; Kafka UI and OpenSearch Dashboards run only with the `ui` Compose profile | The full stack must fit in the RAM available |
| 2026-11-19 | Keshan | SeaweedFS as the local S3 store instead of MinIO | MinIO no longer publishes community images; the app only uses the S3 API, so any S3-compatible store works |
| 2026-11-19 | Keshan | Shared Python code lives in `libs/orderflow-common` | Settings, logging, the event envelope and the Kafka consumer are needed by 4 services; 1 copy avoids drift |
| 2026-11-19 | Keshan | 1 uv workspace for all Python packages, with 1 `uv.lock` | Shared library and services always use the same dependency versions; each Docker image installs only its own package |
| 2026-11-19 | Keshan | Migrations run in a 1-shot `<service>-migrate` container before the service starts | 2 copies of a service must never run migrations at the same time |
| 2026-11-19 | Keshan | Redis stock is decreased before Postgres and increased after Postgres | Any failure in between leaves Redis showing less stock than Postgres, never more, so the system cannot oversell; a resync fixes the gap |
| 2026-11-19 | Keshan | `reservations` has 1 row per order (items as JSONB) | Reserve, release, commit and the sweeper each change 1 row under 1 lock |
| 2026-11-19 | Keshan | inventory-service also handles `OrderConfirmed`: the hold becomes `COMMITTED` | Without it, the sweeper would give back stock for orders that were already paid |
| 2026-11-19 | Keshan | order-service sends `RefundPaymentRequested` when a payment succeeds for an order that is already cancelled or cancelling | A payment that arrives after the order timed out must be refunded, not kept |
| 2026-11-19 | Keshan | Kafka integration tests reuse the Compose broker (localhost:29092) instead of a Testcontainers broker, and skip when it is not running | A second Kafka broker does not fit in the RAM available |
| 2026-11-19 | Keshan | payment-service uses `franz-go` as its Kafka client | Pure Go: no C compiler or librdkafka needed on Windows, and a small static binary |
| 2026-11-19 | Keshan | payment-service uses `goose` for migrations, with the SQL files embedded in the binary | 1 binary can migrate and serve; plain SQL files are easy to review |
| 2026-11-19 | Keshan | The fake provider is called outside the database transaction, with order_id as its idempotency key | A slow provider never holds a database transaction open; a retry after a crash gets the same answer instead of a second charge |
| 2026-11-19 | Keshan | When every provider call for a charge times out, the charge is recorded as FAILED (`provider_timeout`) | The fake provider never charges after a missed deadline, so this is safe here; a real provider needs a status query before giving up (noted in the code) |
| 2026-11-19 | Keshan | payment-service image is a static binary on distroless with a `healthcheck` subcommand | No shell or package manager in the image; 28 MB and about 4 MB of RAM |
| 2026-11-19 | Keshan | RabbitMQ code uses pika `BlockingConnection`, with pika pinned below 2.0 | It gives synchronous publisher confirms (publish returns only after the broker stored the job). pika 1.5 marks it deprecated in favour of a thread-safe `Connection` with callback-based confirms; moving to it is a known follow-up before pika 2.0 |
| 2026-11-19 | Keshan | search-indexer uses a batch consumer and the Bulk API, with the event time as an `external_gte` document version | 1 bulk request per batch instead of 1 per event; versions make retries, late events and overlapping reindex or rebuild runs safe |
| 2026-11-19 | Keshan | The 3 main event topics keep every event (`retention.ms=-1`) | Read models such as the search index can always be rebuilt from Kafka alone; disk use only grows, acceptable for local learning |
| 2026-11-19 | Keshan | `orders-v2` mapping uses the english analyzer for product names | Shows why a reindex is needed: an analyzer cannot change on an existing index. A search for "lamps" went from 0 to 3 results |
| 2026-11-19 | Keshan | nginx retries a failed request once on the other order-service copy, including POST | POST /api/orders is idempotent through its Idempotency-Key, so a retry cannot create a second order |
| 2026-11-19 | Keshan | nginx re-resolves container names every 2 seconds (`resolve`, `valid=2s`) | A restarted container can get a new IP; nginx must not keep the old one |
| 2026-11-19 | Keshan | The rate limiter fails open when Redis is down | A broken limiter must not take the order API offline; the risk is a short time without limits |
| 2026-11-19 | Keshan | Known issue: on the dev machine (about 3.9 GB for Docker) the full e2e suite sometimes hits a short Docker stall (Kafka session timeouts, DNS errors, slow HTTP). 2 of the last 3 full runs passed; 1 had a single failure that did not repeat | Recorded instead of hidden; more Docker memory or fewer running containers would reduce it |
| 2026-11-19 | Keshan | Retries go through `<topic>.retry`, handled by a second consumer per service in group `<group>.retry`; after 5 attempts (2 to 32 second delays) a message goes to `<topic>.dlq` | 1 bad message never blocks a partition, and waiting for a retry never blocks the main topic |
| 2026-11-19 | Keshan | Every retry and dead letter message carries the failing consumer group in a header; groups skip other groups' retries | Several groups read the same topic; without it, every group would handle every retry |
| 2026-11-19 | Keshan | Kafka DLQ replay goes back through `.retry` for 1 group, with a replay position per group | Only the group that failed handles the message again |
| 2026-11-19 | Keshan | reconcile reads every database as the read-only `cdc` user | A checking tool must never be able to change data |
| 2026-11-19 | Keshan | Lesson from reconcile: a consumer that skips event types it does not handle yet commits them, so a later version with the handler never sees them. 19 orders were charged and then cancelled without a refund because of this during development | When a handler is added for an event type that already flows, the missed events must be replayed on purpose |
| 2026-11-19 | Keshan | The first M8 verification round failed: all 4504 orders stayed PENDING because no Debezium connector was registered. `down -v` had removed the stored connectors and debezium-init found an empty connectors folder, retried a literal `*` 20 times and exited 1 unnoticed. The register script now fails at once on an empty folder, and `phase1-verify.sh` stops before any load unless every outbox connector is RUNNING | A broken setup must fail in seconds, not after a 20 minute run |
| 2026-11-19 | Keshan | The Postgres healthcheck runs `pg_isready` over TCP | On a first start the init scripts run on a socket-only temporary server that restarts afterwards; a socket check called it healthy early and payment-migrate hit the restart |
| 2026-11-19 | Keshan | `phase1-verify.sh` stops when k6 is missing, when k6 fails a threshold, or when a round creates no orders | A run without k6 "passed" 3 rounds while checking an idle system |
| 2026-11-19 | Keshan | Open bug found by M8 round 1: a Kafka broker stall (about 10 s, 19:59 UTC) left inventory-service's consumer blocked in a synchronous offset commit with no timeout. It never recovered: 3892 orders stayed in progress. Planned fix: `store_offsets` with background commits, and a watchdog that exits the process when the consumer is stuck so Docker restarts it | 1 broker hiccup must not stop a service for good, and an unhealthy container must not stay unhealthy |
| 2026-11-19 | Keshan | Open bug found by M8 round 1: the inventory sweeper released 136 holds of orders that were already paid, because the OrderConfirmed events were still waiting in Kafka. `commit()` only accepts a HELD reservation, so that stock stayed for sale. Planned fix: on OrderConfirmed for a released hold, take the stock again; if it is gone, inventory sends an event and order-service cancels and refunds | Any long consumer delay can otherwise sell paid stock twice |
| 2026-11-19 | Keshan | Merge M8 with the 2 bugs open and start Phase 2 before Phase 1 is done. Phase 1 gets its `phase1-done` tag only after both fixes and 3 passing rounds | M8 did not cause the bugs (they are in M1 and M3 code), it is the tooling that found them; Phase 2 should start from the latest code |
