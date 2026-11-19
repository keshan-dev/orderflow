# Phase 1: Order Platform

In this phase you build the OrderFlow application itself. Everything runs on your own machine with Docker Compose. No Kubernetes and no cloud yet.

## What you build

A small online ordering system made of 5 services that work together:

| Service | Language | What it does |
|---|---|---|
| `order-service` | Python (FastAPI) | Takes orders from customers and runs the order flow (the saga) |
| `inventory-service` | Python (FastAPI) | Keeps products and stock, and holds stock for orders |
| `payment-service` | Go | Charges and refunds through a fake payment provider that you can make slow or failing |
| `notification-worker` | Python | Sends receipt emails (to a fake inbox) and creates PDF invoices |
| `search-indexer` | Python | Keeps the order search index up to date |

Around them you run the real infrastructure: PostgreSQL, Redis, Kafka, Debezium, RabbitMQ, OpenSearch, SeaweedFS (S3), Mailpit (fake email) and nginx (load balancer).

The full design is in [architecture.md](architecture.md). The names used everywhere come from [the common architecture](../common/02-architecture.md).

## Why this phase matters

This is the system that every later phase uses:

- Phase 2 ships it to Kubernetes and watches it.
- Phase 3 creates its environments with 1 YAML file.
- Phase 4 guards it from the Linux kernel.
- Phase 5 runs it on AWS.

If Phase 1 is solid, the later phases are about tools. If Phase 1 is weak, every later phase inherits its bugs.

## What you will learn

- How to keep data correct across several services without 1 big shared database.
- Why "save to the database, then send a message" is a bug, and how the **outbox pattern** fixes it.
- How a **saga** runs a multi-step business flow and undoes steps when something fails.
- How to make APIs and consumers **idempotent**, so a repeated request or message does no harm.
- When to use Kafka (events) and when to use RabbitMQ (jobs).
- How Redis, OpenSearch and S3 each solve a different problem than PostgreSQL.
- How to prove all of this works by breaking it on purpose.

New words are explained in [concepts.md](concepts.md) and the [glossary](../common/04-glossary.md).

## Before you start

You should be comfortable with:

- Python and FastAPI basics (you used them in HeadRef).
- SQL and PostgreSQL basics.
- Docker basics: build an image, run a container.
- Git basics.

You do not need to know Go well yet. payment-service is small and is a good place to start learning it. See [references.md](references.md) for what to read.

Set up your machine first: [dev environment](../common/06-dev-environment.md).

## How to run (target commands)

These are the commands you will have working by the end of the phase:

```bash
# start everything
docker compose -f deploy/compose/docker-compose.yml up -d --build

# check every container is healthy
docker compose -f deploy/compose/docker-compose.yml ps

# register the Debezium connectors (1 per database)
./deploy/compose/debezium/register-connectors.sh

# place an order through the load balancer
curl -X POST http://localhost:8080/api/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"items":[{"product_id":"<id>","quantity":1}]}'

# run the chaos test and the load test
./chaos/phase1-kill-random.sh
k6 run loadtest/phase1-orders.js

# check that no payment was lost or doubled
docker compose -f deploy/compose/docker-compose.yml run --rm reconcile
```

Useful web UIs while you work:

| URL | What |
|---|---|
| http://localhost:8085 | Kafka UI: topics, messages, consumer lag |
| http://localhost:15672 | RabbitMQ management |
| http://localhost:5601 | OpenSearch Dashboards |
| http://localhost:7888/buckets/ | S3 file browser (see the invoice PDFs) |
| http://localhost:8025 | Mailpit inbox (see the receipt emails) |

## Done checklist

Phase 1 is done when every line is true and you have shown it working, not just written the code:

- [ ] `docker compose up` starts every container and all report healthy.
- [ ] A normal order goes `PENDING` to `STOCK_RESERVED` to `CONFIRMED`.
- [ ] An order for more stock than exists ends `CANCELLED` with no payment.
- [ ] A failed payment releases the stock and ends `CANCELLED`.
- [ ] Sending the same `POST /api/orders` twice with the same `Idempotency-Key` creates only 1 order.
- [ ] Sending the same Kafka event twice changes nothing the second time.
- [ ] A confirmed order produces 1 email in Mailpit and 1 PDF in the S3 bucket.
- [ ] `GET /api/orders/search?q=` finds orders, and a reindex to `orders-v2` works with no downtime.
- [ ] Killing 1 of the 2 order-service containers does not stop the API.
- [ ] The rate limit returns `429` when a client sends too many requests.
- [ ] A message that always fails ends up in a DLQ, not in an endless loop.
- [ ] The chaos script plus the k6 load test finish with the reconcile job reporting 0 lost and 0 duplicate payments.
- [ ] You wrote down the measured numbers (see the end of [implementation-plan.md](implementation-plan.md)).
- [ ] Decisions made during the phase are in the decision log in [`PLAN.md`](../../PLAN.md).

## Files in this folder

| File | What it gives you |
|---|---|
| [architecture.md](architecture.md) | The design: diagram, saga, outbox, idempotency, Redis, retries, decisions |
| [concepts.md](concepts.md) | Every new idea, in simple words, with what breaks without it |
| [references.md](references.md) | Official docs to read, which sections, and when |
| [implementation-plan.md](implementation-plan.md) | Milestones M0 to M8 with tasks, tests and "done when" |

## Next phase

When this checklist is complete, go to [Phase 2: GitOps and observability](../phase-2-gitops-observability/README.md).
