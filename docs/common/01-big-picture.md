# The Big Picture

This page explains OrderFlow in simple words. Read it first. You do not need to know any of the tools yet.

## 1. What is OrderFlow?

OrderFlow is a small online shop backend. It does not have a nice website. It has an API (a set of web addresses that programs call) where a customer can:

- see the products and how many are in stock,
- place an order,
- check the status of the order,
- search old orders.

That sounds easy. The hard part is doing it **correctly when things go wrong**:

- What if the payment service crashes in the middle of a payment?
- What if the same message arrives 2 times?
- What if 500 people try to buy the last 10 items at the same moment?
- What if a new version of the code has a bug?
- What if someone breaks into a container?

Real companies solve these problems with the tools in our stack. OrderFlow is small on purpose, so you can focus on the tools and the problems they solve, not on business features.

## 2. The parts, in 1 sentence each

| Part | What it does |
|---|---|
| Load balancer | The front door. Sends each request to a healthy copy of a service. |
| `order-service` | Takes orders and decides the next step for each order. |
| `inventory-service` | Knows the products and the stock. Holds stock for an order. |
| `payment-service` | Takes the money (from a fake payment provider, so no real money). |
| `notification-worker` | Sends the receipt email and makes the PDF invoice. |
| `search-indexer` | Keeps the search engine up to date with the latest orders. |
| PostgreSQL | The main database. The final truth about orders, stock and payments. |
| Redis | Very fast memory storage. Used for stock holds, caching and rate limits. |
| Kafka | A shared, ordered log of "things that happened" (events). |
| Debezium | Copies new events from the database into Kafka. |
| RabbitMQ | A to-do list of jobs for workers ("send this email"). |
| OpenSearch | The search engine for orders. |
| S3 (MinIO on your machine) | File storage for the PDF invoices. |
| Mailpit | A fake email inbox. Emails go here, not to real people. |

The full technical details (ports, topics, tables) are in [Architecture](02-architecture.md). Every tool is explained in [Tools explained](03-tools-explained.md).

## 3. The story of 1 order

Let us follow Nimal, a customer, who buys 2 notebooks.

### Step 1: Nimal looks at the products

1. Nimal's app calls `GET /api/products`.
2. The request reaches the **load balancer** on port 8080. There may be 3 copies of `inventory-service` running. The load balancer picks a healthy one.
3. `inventory-service` first checks **Redis** for the key `cache:products`. If the list is there (it was saved less than 60 seconds ago), it answers immediately.
4. If not, it reads the products from **PostgreSQL** (`inventory_db`), saves the list in Redis for next time, and answers.

Why: product lists are read many times and change rarely. Redis saves the database from repeating the same work.

### Step 2: Nimal places the order

1. Nimal's app calls `POST /api/orders` with an `Idempotency-Key` header (a unique id for this attempt).
2. `order-service` checks Redis for `idem:{key}`. If this key was already used, it returns the first answer again. So if Nimal's phone sends the request twice because of a bad network, only 1 order is created.
3. `order-service` writes 2 things in **1 database transaction** in `orders_db`:
   - the new order with status `PENDING`,
   - an `OrderCreated` event in the `outbox` table.
4. It answers Nimal straight away: `202 Accepted` and the order id. Nimal does not wait for the payment.

Why the outbox: the order and the event are saved together. Either both are saved or neither is. There is never an order without its event.

### Step 3: The event travels through Kafka

1. **Debezium** watches the `outbox` table. It sees the new row and publishes `OrderCreated` to the Kafka topic `orders.events`.
2. The message key is the `order_id`. All events for Nimal's order go to the same partition, so they stay in order.

### Step 4: Stock is held

1. `inventory-service` reads `OrderCreated` from Kafka.
2. It checks `processed_events`: "did I already handle this event?" If yes, it skips it. This makes it safe if the same event arrives twice.
3. It runs a small **Lua script** inside Redis that checks `stock:{product_id}` and takes 2 notebooks in 1 step. Nobody else can take the same 2 notebooks in between.
4. It saves the hold in Redis (`hold:{order_id}`, expires in 15 minutes) and in PostgreSQL (`reservations`), plus a `StockReserved` event in its own outbox.
5. Debezium publishes `StockReserved` to `inventory.events`.

If there are not enough notebooks, it publishes `StockRejected` instead, and the order becomes `CANCELLED`.

### Step 5: Payment is taken

1. `order-service` reads `StockReserved`, updates the order to `STOCK_RESERVED`, and writes `ChargePaymentRequested` to its outbox.
2. `payment-service` (written in Go) reads it and calls the fake payment provider with a timeout and a retry limit.
3. It saves the payment in `payments_db` and writes `PaymentSucceeded` (or `PaymentFailed`) to its outbox.

### Step 6: The order is confirmed, or undone

- **Success:** `order-service` reads `PaymentSucceeded` and sets the order to `CONFIRMED`. It writes `OrderConfirmed` to its outbox.
- **Failure:** `order-service` reads `PaymentFailed` and asks `inventory-service` to give the notebooks back (`ReleaseStockRequested`). When it sees `StockReleased`, the order becomes `CANCELLED`.

This step by step flow, where each failure has an "undo" step, is called a **saga**.

### Step 7: Background jobs

1. When the order is confirmed, `order-service` puts 2 jobs on **RabbitMQ**: 1 on `notifications.email` and 1 on `invoices.generate`.
2. `notification-worker` takes each job:
   - It sends the receipt email to **Mailpit** (a fake inbox you open at port 8025).
   - It creates a PDF invoice and saves it in **S3** (MinIO on your machine) at `invoices/{yyyy}/{mm}/{order_id}.pdf`.
3. If a job fails too many times, it goes to a **dead letter queue** (for example `invoices.generate.dlq`) so a person can look at it. It is not lost.

### Step 8: The order becomes searchable

1. `search-indexer` reads `orders.events` from Kafka.
2. It writes the order into **OpenSearch** through the alias `orders`.
3. Later, Nimal calls `GET /api/orders/search?q=notebook` and finds the order.

### Step 9: Behind the scenes (Phase 2 onwards)

- Every service sends **metrics** (numbers like "orders per second") to **Prometheus**, **logs** to **Loki**, and **traces** (the path of 1 request) to **Jaeger**, through the **OpenTelemetry Collector**.
- **Grafana** shows all of it on dashboards. You can click from an alert to the slow trace to the exact log line.
- If something breaks, **Alertmanager** sends an alert.

### Step 10: How the code got there (Phase 2 onwards)

1. You push code to GitHub.
2. **GitHub Actions** runs the tests, builds a **Docker** image, scans it with **Trivy**, signs it with **cosign**, and updates the image tag in the **Helm** values.
3. **Argo CD** sees the change in Git and updates **Kubernetes**.
4. **Argo Rollouts** sends a small part of the traffic to the new version first. If the error rate goes up, it rolls back by itself.

## 4. The 5 phases add 1 layer each

Think of OrderFlow like a building:

| Phase | Layer | In simple words |
|---|---|---|
| 1 | **The app** | Build the shop: the 5 services and all the data stores, running with Docker Compose on your machine. |
| 2 | **Ship it and watch it** | Move it to Kubernetes, deploy it automatically from Git, and see everything on dashboards. Break it on purpose and watch it recover. |
| 3 | **Extend Kubernetes** | Teach Kubernetes a new word, `AppStack`. 1 short YAML file creates a full environment for an app. Written in Go. |
| 4 | **Guard it from the kernel** | Watch every program start, file open and network connection inside the cluster using eBPF, and raise an alert on suspicious behaviour. |
| 5 | **Run it in the cloud** | Build the same system on real AWS with Terraform, with a private network, a firewall at the edge and managed databases. |

Each phase uses the result of the phase before it. See the [Roadmap](05-roadmap.md) for the order and the reasons.

## 5. What you will be able to explain at the end

When all 5 phases are done, you should be able to explain, without notes:

- Why each box in the architecture diagram exists, and what breaks without it.
- How 1 order moves through the whole system, and what happens when any step fails.
- The difference between Kafka (events, many readers, replay) and RabbitMQ (jobs, 1 worker, then gone).
- How the outbox pattern, idempotent consumers and the saga keep money and stock correct.
- Why PostgreSQL is the truth and Redis is only a helper.
- How code goes from a `git push` to running in Kubernetes with no manual steps, and how a bad release rolls back.
- How to go from an alert to the slow request to the log line that explains it.
- How Kubernetes works inside: controllers, the reconcile loop, CRDs and admission webhooks.
- What eBPF is, why it is safe to run in the kernel, and how you link a kernel event to a pod.
- How a secure AWS network is built: public, private and isolated subnets, security groups, WAF, and VPC endpoints.
- What it costs to run, and how you keep costs under control.

The [interview readiness guide](../interview-readiness.html) has realistic questions on all of this.
