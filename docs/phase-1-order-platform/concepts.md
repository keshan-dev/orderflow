# Phase 1 Concepts

Every new idea in Phase 1, in simple words. For each one: what it is, a small example from OrderFlow, and what breaks without it. Short definitions of single words are in the [glossary](../common/04-glossary.md).

---

## 1. Transactions and isolation

**What it is.** A transaction groups several database changes into 1 unit. Either all of them are saved (commit) or none of them are (rollback). **Isolation** decides what 1 transaction can see of another transaction that is running at the same time.

**In OrderFlow.** order-service saves the order, its items and the `OrderCreated` outbox row in 1 transaction.

**Isolation levels in PostgreSQL**, from weakest to strongest:

| Level | What it protects against |
|---|---|
| Read Committed (the default) | You never see changes another transaction has not committed yet |
| Repeatable Read | Rows you read stay the same for your whole transaction |
| Serializable | The result is the same as if transactions ran 1 at a time |

Stronger levels are safer but can fail with "could not serialize" errors that you must retry. In Phase 1, use Read Committed plus explicit row locks where needed.

**Without it.** The order is saved but its items are not. Or the order is saved but the event is lost. Data becomes half-written and wrong.

---

## 2. Row locks and `SKIP LOCKED`

**What it is.** `SELECT ... FOR UPDATE` locks the rows you read. Another transaction that wants the same rows must wait until you commit. `SKIP LOCKED` tells the other transaction "do not wait, just skip rows someone else has locked".

**In OrderFlow.**

- inventory-service locks the stock rows before decreasing them: `FOR UPDATE`.
- The expired-hold sweeper uses `FOR UPDATE SKIP LOCKED`, so 2 copies of the sweeper never release the same reservation and never wait on each other.

**Without it.** 2 requests both read "stock = 1", both subtract 1, and you sell the same item twice (stock becomes -1). This is called a **race condition**.

---

## 3. The outbox pattern

**What it is.** When a service must save data **and** send an event, it does not send the event directly. It writes the event into an `outbox` table in the **same transaction** as the data. A separate process later reads the outbox and publishes the events.

**In OrderFlow.** Every service has an `outbox` table. Debezium publishes it to Kafka.

**Without it (the "dual write" bug).**

```
save order to Postgres   ok
send event to Kafka      crash before this line
```

The order exists but nobody hears about it: stock is never reserved, the customer waits forever. If you send first and save second, the opposite happens: an event for an order that does not exist. You cannot make 2 separate systems commit together, so you put both writes into 1 system (Postgres) and publish afterwards.

---

## 4. CDC (Change Data Capture)

**What it is.** Reading every change a database makes, as it happens, from the database's own change log. In PostgreSQL this log is the **WAL** (write-ahead log). **Debezium** is a CDC tool that reads the WAL and turns changes into Kafka messages.

**In OrderFlow.** Debezium watches only the `outbox` table in each database. Every new outbox row becomes a Kafka message.

**Without it.** You would write a "poller" that runs `SELECT * FROM outbox WHERE published = false` every second. That works, but it adds load, adds delay, and you must handle marking rows as published yourself. CDC is faster and does not query your tables.

---

## 5. Saga and compensation

**What it is.** A **saga** is a business flow made of several steps, where each step is a local transaction in 1 service. There is no single big transaction across services. If a later step fails, the saga runs **compensations**: new steps that undo the earlier ones.

There are 2 styles:

| Style | How | OrderFlow |
|---|---|---|
| Choreography | Each service listens and reacts. No boss. | Not used |
| Orchestration | 1 service (the orchestrator) tells others what to do next | Used: order-service is the orchestrator |

**In OrderFlow.** Reserve stock, then charge payment. If payment fails, the compensation is "release the stock".

**Important.** A compensation is not a rollback. The stock really was reserved for a while. You add a new action that reverses its effect.

**Without it.** You would need a distributed transaction across 3 databases (2-phase commit). It is slow, it locks data across services, and 1 slow service blocks everyone. Without any plan at all, a failed payment would leave stock held forever.

---

## 6. Idempotency

**What it is.** An operation is **idempotent** if doing it 2 times has the same result as doing it 1 time. "Set status to CONFIRMED" is idempotent. "Add 10 to the balance" is not.

**2 places in OrderFlow:**

| Where | How |
|---|---|
| API | The client sends an `Idempotency-Key` header. order-service remembers the key and returns the same answer for a repeat. |
| Consumer | Each event has an `event_id`. The consumer records it in `processed_events` and skips events it has already seen. |

**Without it.** The customer double-clicks "Pay" and gets 2 orders. Kafka redelivers a `ChargePaymentRequested` after a crash and the customer is charged 2 times.

---

## 7. At-least-once delivery

**What it is.** There are 3 possible promises a messaging system can make:

| Promise | Meaning |
|---|---|
| At most once | A message may be lost, never duplicated |
| At least once | A message is never lost, but may arrive more than once |
| Exactly once | Each message has its effect exactly 1 time |

Kafka consumers in OrderFlow work **at least once**: process the message, then commit the offset. If you crash between those 2 steps, the message comes again.

Exactly once between Kafka and an outside database is not something Kafka can promise on its own. The practical answer is: **at-least-once delivery plus idempotent consumers = the effect happens exactly once.**

**Without understanding this.** You either commit the offset first and lose messages on a crash, or you assume no duplicates and charge customers 2 times.

---

## 8. Kafka basics: partitions, keys, consumer groups, offsets

| Word | Meaning | In OrderFlow |
|---|---|---|
| **Topic** | A named stream of messages, like a log file you only add to | `orders.events` |
| **Partition** | A topic is split into partitions. Each partition keeps strict order. | `orders.events` has several partitions so 2 consumers can share the work |
| **Key** | Decides which partition a message goes to. Same key, same partition. | The `order_id`, so all events of 1 order stay in order |
| **Consumer group** | A set of consumers that share 1 topic. Each partition goes to 1 member. | Both order-service containers are in group `order-service` |
| **Offset** | The position of a message in a partition. A group saves the offset it reached. | Committed after the database transaction succeeds |

Different consumer groups read the same topic separately. search-indexer and inventory-service both read `orders.events`, and neither affects the other.

**Without keys.** Events for 1 order land on different partitions and can be processed out of order: `OrderConfirmed` before `OrderCreated`.

---

## 9. Retries, retry topics and the DLQ

**What it is.** When processing fails:

- A **retry** tries again, with a wait between tries that grows each time (**exponential backoff**), and a fixed maximum number of tries.
- A **retry topic** holds failed messages for a later try, so the main topic keeps moving.
- A **DLQ** (dead letter queue) holds messages that failed too many times, for a person to inspect.

**In OrderFlow.** `orders.events.retry` and `orders.events.dlq` in Kafka. `invoices.generate.dlq` and `notifications.email.dlq` in RabbitMQ.

**Temporary vs permanent errors.** A database timeout is temporary: retry it. Broken JSON is permanent: retrying will never work, send it to the DLQ straight away.

**Without it.** 1 bad message is retried forever and blocks every message behind it on that partition (a **poison message**). Or failed messages are dropped and silently lost.

---

## 10. Queue vs event log (RabbitMQ vs Kafka)

| | RabbitMQ (queue) | Kafka (event log) |
|---|---|---|
| Message means | "Please do this work" | "This happened" |
| After it is handled | Removed from the queue | Stays, for a set time |
| Readers | 1 worker takes each job | Many groups each read every event |
| Replay old messages | No | Yes, reset the offset |
| Good for | Emails, PDFs, resizing images | Business events many services care about |

**In OrderFlow.** `OrderConfirmed` is a fact, so it goes to Kafka. "Send the receipt email" is work for 1 worker, so it goes to RabbitMQ.

**Without the difference.** If you put jobs in Kafka, you build your own job tracking, retries and per-message acknowledgement. If you put business events in RabbitMQ, a new service that wants old events cannot get them.

---

## 11. Cache and TTL

**What it is.** A **cache** keeps a copy of data that is slow or expensive to get, in a faster place. **TTL** (time to live) is how long the copy stays before it expires.

**In OrderFlow.** `cache:products` keeps the product list in Redis for 60 seconds.

**The hard part** is that the copy can be out of date. 60 seconds of old product data is acceptable. Old stock numbers for a reservation are not, which is why reservations do not use the cache.

**Without it.** Every page view runs the same database query. Under heavy traffic the database slows down for everyone, including checkout.

---

## 12. Lua scripts and atomic operations in Redis

**What it is.** Redis runs 1 command at a time. A **Lua script** sent to Redis runs as 1 command from start to end, so no other client can change data in the middle. This is called **atomic**.

**In OrderFlow.** The reserve script checks all items and takes all of them, or takes none, in 1 step.

**Without it.** Using separate `GET` then `DECRBY` commands, 2 customers can both read "1 left" before either subtracts, and both get the last item.

---

## 13. Rate limiting (token bucket)

**What it is.** A limit on how many requests 1 client can make in some time. The **token bucket** algorithm:

- Each client has a bucket that holds up to N tokens.
- Tokens are added back at a steady speed.
- Each request takes 1 token. No token left means `429 Too Many Requests`.

It allows short bursts (a full bucket) while keeping the average speed limited.

**In OrderFlow.** A Lua script on `ratelimit:{client}` in Redis, shared by both order-service containers.

**Without it.** 1 buggy client or 1 attacker can send thousands of orders per second and make the service slow for everyone.

---

## 14. Search index, mapping and alias

| Word | Meaning |
|---|---|
| **Index** | Where OpenSearch stores documents, like a table |
| **Document** | 1 JSON record, here 1 order |
| **Mapping** | The type of each field. `text` is split into words for full text search. `keyword` is matched exactly (ids, statuses). |
| **Alias** | A second name that points to an index. The app uses the alias, so you can switch the real index behind it. |

**In OrderFlow.** The app uses `orders`, which points to `orders-v1`.

**Why an alias.** You cannot change the type of an existing field in place. To change the mapping you build a new index (`orders-v2`), copy the data, and switch the alias in 1 step.

**Without OpenSearch.** `WHERE name LIKE '%burger%'` reads every row, cannot rank results by relevance, and does not handle typos. **Without the alias**, changing the mapping means downtime while you delete and rebuild the index.

---

## 15. Object storage (S3)

**What it is.** Storage for files ("objects") reached by a bucket name and a key, through an HTTP API. It is cheap and keeps data safe even when servers come and go.

**In OrderFlow.** PDF invoices in the `orderflow-invoices` bucket. MinIO (or another S3-compatible store) locally, real S3 in Phase 5. The code is the same.

**Without it.** Files are saved on the container's disk. When the container restarts, they are gone. The other container cannot see them. Saving files inside Postgres instead makes the database large and slow to back up.

---

## 16. Load balancing and health checks

**What it is.** A **load balancer** receives all requests and spreads them across several copies of a service. A **health check** tells it which copies are working.

**Liveness vs readiness:**

| Check | Question | If it fails |
|---|---|---|
| Liveness (`/healthz`) | Is the process alive? | Restart it |
| Readiness (`/readyz`) | Can it serve traffic now? | Stop sending it traffic, do not restart |

**In OrderFlow.** nginx spreads requests across `order-service-1` and `order-service-2`.

**Without it.** 1 container serves everything. When it crashes or you deploy a new version, the API is down.

---

## 17. Docker images, multi-stage builds and Compose networking

| Word | Meaning |
|---|---|
| **Image** | A packaged app with everything it needs to run. Built from a `Dockerfile`. |
| **Container** | A running image |
| **Layer** | Each `Dockerfile` step makes a layer. Unchanged layers are reused (cached), so put things that change rarely (dependencies) before things that change often (your code). |
| **Multi-stage build** | Build in 1 stage that has compilers and tools, then copy only the result into a small final stage. The final image is smaller and has fewer security holes. |
| **Compose network** | Compose puts all services in 1 network. A service is reached by its name, for example `postgres:5432`, not `localhost`. |
| **Volume** | Storage that survives when a container is removed, for example Postgres data |

**In OrderFlow.** payment-service is a perfect multi-stage example: build the Go binary in a Go image, then copy only the binary into a tiny final image.

**Without it.** "It works on my machine." Different Python or library versions on each machine cause bugs nobody else can reproduce.
