# Glossary

Simple meanings for the words used in the OrderFlow docs, in alphabetical order. For the tools themselves, see [Tools explained](03-tools-explained.md).

## A

**ACK (acknowledgement)**: A message from a consumer that says "I finished this message". RabbitMQ deletes a job only after it gets the ack. If the worker crashes before the ack, the job goes back to the queue.

**Admission webhook**: An HTTP endpoint that Kubernetes calls before it saves an object. A **validating** webhook can reject the object. A **mutating** webhook can change it. Example: reject any pod with no memory limit.

**Alias (OpenSearch)**: A second name that points to 1 or more indices. The app always uses `orders`, which points to `orders-v1`. You can build `orders-v2` and move the alias with no downtime.

**API**: A set of addresses and rules that programs use to talk to each other. Example: `POST /api/orders`.

**App of apps**: An Argo CD pattern where 1 Argo CD application creates all the other applications. You install 1 thing and the rest follows.

**ApplicationSet**: An Argo CD feature that creates many applications from 1 template. Example: 1 template creates dev, staging and prod.

**Availability zone (AZ)**: A separate data center inside an AWS region. Spreading resources over 2 or more AZs keeps you running if 1 fails.

## B

**Backoff**: Waiting longer between each retry. Example: wait 1 second, then 2, then 4. Stops a failing service from being flooded with retries.

**Blue-green deployment**: Run the old version (blue) and the new version (green) side by side, then switch all traffic at once. Easy to switch back.

**BPF map**: A storage area shared between an eBPF program in the kernel and a program in user space. Used to pass settings or counters.

**BTF (BPF Type Format)**: Information that describes the kernel's data structures. It lets 1 compiled eBPF program work on many kernel versions. Check for it with `ls /sys/kernel/btf/vmlinux`.

**Bucket**: A top-level folder in S3 or MinIO. Example: `orderflow-invoices`.

**Burn rate**: How fast you are using up your error budget. A burn rate of 1 uses the budget exactly over the SLO period. A high burn rate means "we will run out soon", so you alert.

## C

**Cache**: A fast copy of data that is slow to get. Example: the product list in Redis under `cache:products`.

**Cache stampede**: When a popular cache entry expires and hundreds of requests hit the database at the same moment to rebuild it.

**Canary release**: Send a small share of traffic (for example 10%) to a new version first. If it looks healthy, increase the share. If not, roll back.

**CDC (change data capture)**: Reading a database's change log to find new or changed rows. Debezium uses CDC to read the outbox tables.

**cgroup (control group)**: A Linux feature that groups processes and limits their resources. Every container has its own cgroup. In Phase 4, the cgroup id links a kernel event to a pod.

**Chart (Helm)**: A package of Kubernetes YAML templates plus default values.

**CI/CD**: Continuous integration (test and build on every change) and continuous delivery or deployment (release the change automatically).

**Cluster**: A group of machines (nodes) that work together. A Kubernetes cluster runs your containers. A Kafka cluster is a group of Kafka brokers.

**Compensation (compensating action)**: An "undo" step in a saga. Example: if payment fails, release the reserved stock.

**Consumer**: A program that reads messages from Kafka or RabbitMQ.

**Consumer group**: A set of consumers that share the work of reading 1 Kafka topic. Each partition is read by only 1 consumer in the group. Different groups each get all the messages.

**Consumer lag**: How many messages are waiting in Kafka that a consumer group has not read yet. Growing lag means the consumers are too slow.

**Container**: A running instance of a Docker image. It is isolated from other containers but shares the host's kernel.

**Controller**: A program in Kubernetes that watches objects and makes the real world match what they describe. Deployments, for example, are handled by a controller.

**CO-RE (Compile Once, Run Everywhere)**: An eBPF method that uses BTF so a program compiled once can run on different kernel versions.

**CRD (Custom Resource Definition)**: A way to add a new type of object to Kubernetes. In Phase 3 we add `AppStack`.

**Custom resource**: 1 object of a type defined by a CRD. Example: an `AppStack` named `demo`.

## D

**DaemonSet**: A Kubernetes object that runs 1 copy of a pod on every node. The eBPF agent runs as a DaemonSet.

**Dead letter queue (DLQ)**: A place for messages that failed too many times. They are kept for a person to inspect, not lost. Example: `invoices.generate.dlq`, `orders.events.dlq`.

**Deployment (Kubernetes)**: An object that says "run N copies of this pod" and handles rolling updates.

**Distributed lock**: A lock that many services on different machines can respect, often built on Redis. Only 1 holder at a time.

**Distributed tracing**: Following 1 request as it moves through many services. Each step is a span. Together they form a trace.

## E

**eBPF**: A technology to run small, verified programs inside the Linux kernel. See [Tools explained](03-tools-explained.md#ebpf).

**Envelope (event)**: The standard outer shape of every OrderFlow event: `event_id`, `event_type`, `order_id`, `occurred_at`, `version`, `payload`.

**envtest**: A test helper that starts a real Kubernetes API server (without nodes) so you can test an operator.

**Error budget**: How much failure your SLO allows. If the SLO is 99.9% success, the budget is 0.1% failed requests. When it is used up, you stop risky releases.

**Event**: A message that says something has happened, in the past tense. Example: `StockReserved`.

**Eventual consistency**: Different parts of the system may disagree for a short time, but they will agree soon. Example: a new order appears in search a moment after it is saved.

**Exactly once (and why we do not rely on it)**: Processing each message exactly 1 time. In practice messages can arrive more than once, so OrderFlow uses at-least-once delivery plus idempotent consumers.

**Exemplar**: A link from a metric point to an example trace. In Grafana you click a slow latency point and open that trace.

## F

**Failover**: Automatically switching to a standby copy when the main one fails. Example: CloudNativePG promotes a replica when the primary dies.

**Finalizer**: A marker on a Kubernetes object that stops it from being deleted until a controller finishes cleanup. The operator uses it to delete the database and topics of an `AppStack`.

## G

**Gateway API**: The standard Kubernetes API for routing outside traffic into the cluster (`Gateway`, `HTTPRoute`).

**GitOps**: Git is the single source of truth for what runs. A tool (Argo CD) makes the cluster match Git. You change the system by changing Git.

**Golden signals**: The 4 main things to watch for any service: latency, traffic, errors and saturation (how full it is).

## H

**Health check**: An endpoint that says whether a service is OK. `/healthz` means "I am alive". `/readyz` means "I can serve traffic now".

**Hook (eBPF)**: A point in the kernel where an eBPF program can attach. Examples: tracepoints, kprobes.

**HPA (Horizontal Pod Autoscaler)**: Kubernetes object that adds or removes pod copies based on a metric like CPU.

**HTTPRoute**: A Gateway API object that sends requests for a path or host to a service.

## I

**IaC (Infrastructure as Code)**: Describing servers, networks and databases in code files instead of clicking in a console. Terraform and CDK are IaC tools.

**IAM role**: An AWS identity with permissions that a service (like an ECS task) can use, without long-lived passwords.

**Idempotency**: Doing the same thing twice has the same result as doing it once. Example: the same `Idempotency-Key` sent twice creates only 1 order.

**Idempotent consumer**: A consumer that checks `processed_events` first and skips events it already handled.

**Image (container image)**: A read-only package with an app and everything it needs. Containers are started from images.

**Index (OpenSearch)**: A collection of documents, like a table. Example: `orders-v1`.

**Informer**: A client-go helper that watches Kubernetes objects and keeps a local cache, so controllers do not ask the API server again and again.

**Instrumentation**: Code that creates metrics, logs and traces from your app.

**ISM (Index State Management)**: OpenSearch policies that move indices through stages automatically. Example: roll over daily, delete after 7 days.

**Isolation level**: How strictly a database separates transactions that run at the same time. Higher levels prevent more problems but can be slower.

## K

**Kernel**: The core of the operating system. It controls processes, files, memory and the network.

**kprobe**: An eBPF hook that attaches to almost any kernel function. Powerful, but the function names can change between kernel versions.

**KRaft**: Kafka's built-in way to manage its own cluster metadata. Kafka 4 uses only KRaft, with no ZooKeeper.

## L

**Latency**: How long a request takes. **p99 latency** is the time that 99% of requests are faster than.

**Leader election**: When several copies of a controller run, only 1 (the leader) does the work. If it dies, another becomes leader.

**Least privilege**: Give each person or program only the permissions it really needs.

**Liveness and readiness probes**: Kubernetes checks. A failing liveness probe restarts the container. A failing readiness probe stops traffic to it.

**Lua script (Redis)**: A small script that Redis runs as 1 step, with nothing else running in between. Used to check and take stock safely.

## M

**Manifest**: A YAML file that describes a Kubernetes object.

**Message broker**: A server that receives messages from producers and delivers them to consumers. Kafka and RabbitMQ are brokers.

**Metric**: A number measured over time. Example: requests per second.

**Multi-stage build**: A Dockerfile with a "build" stage and a smaller "run" stage. The final image keeps only what it needs to run.

**MVCC (Multi-Version Concurrency Control)**: How PostgreSQL lets readers and writers work at the same time by keeping several versions of rows.

## N

**Namespace (Kubernetes)**: A named group of objects inside a cluster. Used to separate apps or environments.

**NACL (Network Access Control List)**: AWS firewall rules for a whole subnet. They check traffic in both directions separately.

**NAT gateway**: An AWS service that lets resources in private subnets reach the internet, while the internet cannot reach them. It is billed per hour and per amount of data.

**Node**: 1 machine (real or virtual) in a cluster.

## O

**Object storage**: Storage for whole files (objects) addressed by a key, like S3. You do not edit part of a file. You replace it.

**Observability**: Being able to understand what a system is doing from its metrics, logs and traces.

**Offset**: The position of a message in a Kafka partition. Each consumer group remembers its offset, so it knows where to continue.

**Operator**: A controller that manages a specific piece of software in Kubernetes using custom resources. Example: CloudNativePG for PostgreSQL.

**Orchestration (saga)**: 1 service (the orchestrator) tells the others what to do next. In OrderFlow, order-service is the orchestrator.

**Outbox (transactional outbox)**: A table where a service writes events in the same transaction as its data change. Another process (Debezium) publishes them. The data and the event never disagree.

**Owner reference**: A link from a Kubernetes object to its parent. When the parent is deleted, the children are deleted too.

## P

**Partition**: A slice of a Kafka topic. Messages with the same key always go to the same partition and stay in order. More partitions allow more consumers to work in parallel.

**Pod**: The smallest unit in Kubernetes: 1 or more containers that run together.

**Producer**: A program that writes messages to Kafka or RabbitMQ.

**PromQL**: Prometheus's query language. Example: `rate(http_requests_total[5m])`.

**Pull request (PR)**: A request to merge your branch into `main`, where CI runs and others can review.

## R

**Rate limiting**: Allowing only a certain number of requests per client per time window. Uses `ratelimit:{client}` in Redis.

**RBAC (Role-Based Access Control)**: Permissions given through roles. In Kubernetes: Role, ClusterRole, RoleBinding, ServiceAccount.

**Reconcile loop**: The core of a controller. It compares the desired state (the object) with the real state, makes 1 step of change, and repeats until they match.

**Registry**: A server that stores container images. Examples: GitHub Container Registry, Amazon ECR.

**Replay**: Reading old Kafka messages again by moving a consumer group's offset back.

**Replica**: A copy. A pod replica is 1 copy of a pod. A database replica is a copy of the database.

**Retry topic**: A Kafka topic where a failed message waits before another try. Example: `orders.events.retry`.

**Ring buffer (eBPF)**: A fast, shared queue that eBPF programs use to send events from the kernel to user space.

**Rollback**: Going back to the previous working version.

**Rolling update**: Replacing old pods with new ones a few at a time, so the service stays up.

## S

**Saga**: A business flow split into steps across services, where each step has an undo (compensation) if a later step fails. Used instead of 1 big transaction across databases.

**Saturation**: How full a resource is. Example: CPU at 95%, or a queue that keeps growing.

**Schema**: The agreed shape of data. Example: the event envelope, or a table's columns.

**Secret**: Sensitive data like a password or API key. Never stored in Git. Comes from environment variables or a secrets manager.

**Security group**: AWS firewall rules attached to a resource. They allow traffic; anything not allowed is blocked.

**ServiceAccount**: An identity for a pod in Kubernetes, used with RBAC.

**Sidecar**: An extra container in the same pod that helps the main container. Example: an OpenTelemetry agent.

**SKIP LOCKED**: A PostgreSQL option (`SELECT ... FOR UPDATE SKIP LOCKED`) that skips rows another transaction has locked. Useful so workers do not wait on each other.

**SLI (Service Level Indicator)**: The measured number. Example: the share of order requests that succeed in under 500 ms.

**SLO (Service Level Objective)**: The target for an SLI. Example: 99.5% of order requests succeed over 30 days.

**Source of truth**: The 1 place whose data is considered correct when copies disagree. In OrderFlow, PostgreSQL.

**Span**: 1 step inside a trace, with a start time and a duration. Example: "payment-service charge".

**State file (Terraform)**: A file where Terraform records what it created. Stored remotely in S3 so a team can share it, with locking so 2 people do not change it at once.

**StatefulSet**: A Kubernetes object for apps that need stable names and storage, like databases.

**Subnet**: A smaller part of a VPC's IP address range. **Public** subnets can be reached from the internet. **Private** ones cannot, but can go out through a NAT gateway. **Isolated** ones have no internet path at all.

## T

**Tail sampling**: Deciding whether to keep a trace after it is complete. Example: keep all slow or failed traces, but only 10% of normal ones.

**Task (ECS)**: 1 running copy of a container definition in Amazon ECS. Like a pod in Kubernetes.

**TLS**: The encryption behind HTTPS. Uses certificates to prove who a server is.

**Topic**: A named stream of messages in Kafka. Example: `orders.events`.

**Trace**: The full path of 1 request through all services, made of spans.

**Trace context propagation**: Passing the trace id from 1 service to the next, in HTTP headers or message headers, so the trace stays connected.

**Tracepoint**: A stable, named hook in the Linux kernel. Example: `sched_process_exec`. Safer than kprobes because the names do not change often.

**Transaction**: A group of database changes that all succeed or all fail together.

**TTL (Time To Live)**: How long something lives before it expires. Example: `hold:{order_id}` expires after 15 minutes.

## U

**User space**: Where normal programs run, outside the kernel. The Go part of the eBPF agent runs in user space.

## V

**Values file (Helm)**: A YAML file that fills in a chart's settings. Example: `values-prod.yaml` sets 3 replicas.

**Verifier (eBPF)**: The kernel part that checks an eBPF program before it runs, so it cannot crash or hang the kernel.

**VPC (Virtual Private Cloud)**: Your own private network in AWS.

**VPC endpoint**: A private connection from your VPC to an AWS service like S3, without going through the internet.

## W

**WAF (Web Application Firewall)**: A firewall that inspects HTTP requests and blocks attacks like SQL injection or floods.

**Webhook**: An HTTP call that 1 system makes to another when something happens. See admission webhook.

**Worker**: A program that takes jobs from a queue and does them. Example: notification-worker.
