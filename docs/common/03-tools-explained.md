# Tools Explained

Every tool used in OrderFlow, grouped by layer. For each tool you get:

- **What:** what it is, in 1 or 2 simple sentences.
- **Like:** a real-life comparison.
- **In OrderFlow:** its exact job in this project.
- **Without it:** what goes wrong.
- **Alternative:** a common tool that does a similar job.
- **Phase:** where you use it.

Words you do not know are in the [glossary](04-glossary.md). Names, ports and topics come from [Architecture](02-architecture.md).

## Quick map

| Layer | Tools |
|---|---|
| [1. Front door](#1-front-door) | Load balancer, nginx, Gateway API + Envoy Gateway, AWS ALB |
| [2. Writing the services](#2-writing-the-services) | FastAPI (Python), Go |
| [3. Storing data](#3-storing-data) | PostgreSQL, Redis, OpenSearch, S3 / MinIO |
| [4. Messages between services](#4-messages-between-services) | Kafka, Debezium, RabbitMQ |
| [5. Safe local helpers](#5-safe-local-helpers) | Mailpit, Kafka UI, LocalStack |
| [6. Packaging and running](#6-packaging-and-running) | Docker, Docker Compose, Kubernetes, kind |
| [7. Delivery](#7-delivery) | GitHub Actions, Trivy, cosign, Helm, Argo CD, Argo Rollouts |
| [8. Scaling and testing under stress](#8-scaling-and-testing-under-stress) | KEDA, k6, Chaos Mesh |
| [9. Observability](#9-observability) | OpenTelemetry, Prometheus, Alertmanager, Grafana, Loki, Grafana Alloy, Jaeger |
| [10. Running data stores on Kubernetes](#10-running-data-stores-on-kubernetes) | CloudNativePG, Strimzi, RabbitMQ Cluster Operator |
| [11. Extending Kubernetes](#11-extending-kubernetes) | Kubebuilder, controller-runtime, cert-manager |
| [12. The Linux kernel](#12-the-linux-kernel) | eBPF, cilium/ebpf |
| [13. Cloud and infrastructure as code](#13-cloud-and-infrastructure-as-code) | Terraform, AWS CDK, AWS services |

---

## 1. Front door

### Load balancer (general idea)
- **What:** A server that receives all incoming requests and spreads them over several copies of a service. It stops sending traffic to copies that are not healthy.
- **Like:** A supermarket manager who sends each customer to the shortest open checkout line.
- **In OrderFlow:** The only public entry point for the API (port 8080 locally). It routes `/api/orders` to order-service and `/api/products` to inventory-service.
- **Without it:** 1 server takes all traffic. If it crashes or you deploy a new version, the whole API is down. You cannot add more copies.
- **Phase:** All. It changes form in each phase (below).

### nginx
- **What:** A fast web server that is often used as a reverse proxy and load balancer.
- **Like:** A receptionist who forwards each visitor to the right office.
- **In OrderFlow:** The load balancer in Docker Compose. Routes by URL path to the services.
- **Without it:** Clients would call each service on its own port, and you could not run more than 1 copy behind 1 address.
- **Alternative:** HAProxy, Traefik, Caddy.
- **Phase:** 1.

### Gateway API + Envoy Gateway
- **What:** Gateway API is the standard Kubernetes way to describe how outside traffic reaches services (`Gateway` and `HTTPRoute` objects). Envoy Gateway is a program that reads those objects and does the actual routing using the Envoy proxy.
- **Like:** Gateway API is the written rule book for the front door. Envoy Gateway is the guard who follows it.
- **In OrderFlow:** Replaces nginx when OrderFlow moves to Kubernetes. The old ingress-nginx project is retired, so we use Gateway API.
- **Without it:** No clean, standard way to expose services from the cluster with path routing, TLS and traffic splitting.
- **Alternative:** Other Gateway API implementations such as Traefik, Istio or Cilium.
- **Phase:** 2, 3.

### AWS Application Load Balancer (ALB)
- **What:** The managed load balancer in AWS for HTTP and HTTPS traffic.
- **Like:** The same supermarket manager, but AWS employs and replaces them for you.
- **In OrderFlow:** The front door on AWS. Sits in the public subnets and sends traffic to the ECS tasks in the private subnets.
- **Without it:** Your containers would need public IP addresses, which is unsafe and does not scale.
- **Alternative:** AWS Network Load Balancer (for non-HTTP traffic), API Gateway.
- **Phase:** 5.

---

## 2. Writing the services

### FastAPI (Python)
- **What:** A Python framework for building web APIs. It checks request data with Pydantic and creates API docs automatically.
- **Like:** A ready-made kitchen: you bring the recipes (your logic), the kitchen gives you stoves and plates.
- **In OrderFlow:** order-service and inventory-service. The workers (notification-worker, search-indexer, detection-service) are plain Python.
- **Without it:** You would write request parsing, validation and docs by hand.
- **Alternative:** Flask, Django REST Framework, Spring Boot (Java).
- **Phase:** 1 onwards.

### Go
- **What:** A compiled programming language from Google. It makes small, fast programs and is the main language of Kubernetes itself.
- **Like:** A sturdy hand tool: simple, no surprises, does 1 job well.
- **In OrderFlow:** payment-service (Phase 1), the operator (Phase 3) and the user space part of the eBPF agent (Phase 4).
- **Without it:** The Kubernetes and eBPF libraries are best in Go. You would have a much harder time in Phases 3 and 4.
- **Alternative:** Rust, Java.
- **Phase:** 1, 3, 4.

---

## 3. Storing data

### PostgreSQL
- **What:** A relational database. Data is kept in tables, and changes are safe inside transactions.
- **Like:** The official bank ledger. Slow to change, but always correct.
- **In OrderFlow:** 1 server with 3 databases: `orders_db`, `inventory_db`, `payments_db`. Each has an `outbox` table and a `processed_events` table. It is the source of truth.
- **Without it:** An order could be saved without its payment, or data could be lost on a crash.
- **Alternative:** MySQL, MariaDB. On AWS: RDS or Aurora.
- **Phase:** All. Local container in Phase 1, CloudNativePG in Phase 2, RDS in Phase 5.

### Redis
- **What:** A database that keeps data in memory, so reads and writes are very fast. It can run small Lua scripts as 1 step.
- **Like:** A whiteboard next to your desk: very fast to read, but you can lose it, so the real copy lives in the ledger.
- **In OrderFlow:** Stock counts (`stock:*`), stock holds (`hold:*`), product cache (`cache:products`), idempotency keys (`idem:*`) and rate limits (`ratelimit:*`).
- **Without it:** Every product view and every stock check hits PostgreSQL. Under load, the database slows down, and 2 buyers could take the same last item.
- **Alternative:** Valkey (an open source fork of Redis), Memcached (cache only). On AWS: ElastiCache.
- **Phase:** All.

### OpenSearch
- **What:** A search engine. It finds text fast, ranks results by relevance and handles spelling mistakes.
- **Like:** The index at the back of a book, but it also understands "notbook" means "notebook".
- **In OrderFlow:** The `orders` alias for order search. In Phase 4 also `security-events-*` for security events.
- **Without it:** You would use `LIKE '%word%'` in SQL, which scans every row, has no ranking, and gets slow as data grows.
- **Alternative:** Elasticsearch, Meilisearch, PostgreSQL full text search for small cases.
- **Phase:** 1, 2, 4.

### S3 and MinIO
- **What:** S3 is AWS object storage: you store files (objects) in buckets and read them by key. MinIO is a program you run yourself that speaks the same S3 API.
- **Like:** A warehouse with numbered shelves. You hand over a box, you get a shelf number back.
- **In OrderFlow:** Bucket `orderflow-invoices` for PDF invoices. MinIO on your machine and in kind, real S3 in Phase 5.
- **Without it:** Files sit on a container's disk. They disappear when the container restarts, and other copies cannot see them.
- **Alternative:** Google Cloud Storage, Azure Blob Storage. Locally: LocalStack S3.
- **Phase:** 1, 2, 5.

---

## 4. Messages between services

### Kafka
- **What:** A distributed log of events. Producers add events to topics. Many consumer groups can read the same events, each at their own speed, and can read old events again (replay). Kafka 4 runs in KRaft mode, with no ZooKeeper.
- **Like:** A newspaper archive. Every day's paper is kept. Any number of readers can read it, starting from any date.
- **In OrderFlow:** Topics `orders.events`, `inventory.events`, `payments.events`, plus `.retry` and `.dlq` topics. Phase 4 adds `security.events`.
- **Without it:** Services call each other directly. If 1 is down, the call fails and the event is lost. Every new reader means changing the sender.
- **Alternative:** Redpanda, Apache Pulsar. On AWS: Amazon MSK, Kinesis.
- **Phase:** 1, 2, 4. Strimzi runs it in Kubernetes in Phase 2.

### Debezium
- **What:** A change data capture tool. It reads the database's change log and turns new rows into Kafka events. It runs inside Kafka Connect.
- **Like:** A clerk who watches the ledger and announces every new line on the radio.
- **In OrderFlow:** Reads the `outbox` table in each database and publishes the events to the right topic using the Outbox Event Router.
- **Without it:** Your code must write to the database and send to Kafka separately. If it crashes between the 2, they disagree (data saved, no event, or the reverse).
- **Alternative:** A polling publisher (a loop that reads the outbox and sends to Kafka).
- **Phase:** 1, 2.

### RabbitMQ
- **What:** A message broker for jobs. A message waits in a queue until 1 worker takes it and confirms it is done. Failed messages can go to a dead letter queue.
- **Like:** A to-do list on the office wall. Each task is taken by 1 person and crossed out when done.
- **In OrderFlow:** Queues `notifications.email` and `invoices.generate`, each with a `.dlq`.
- **Without it:** The user waits while the email sends and the PDF is made. If the email server fails, the job is lost.
- **Alternative:** Celery with Redis, Amazon SQS (used in Phase 5).
- **Phase:** 1, 2.

---

## 5. Safe local helpers

### Mailpit
- **What:** A fake email server with a web inbox.
- **Like:** A practice mailbox in your own room.
- **In OrderFlow:** notification-worker sends receipts to Mailpit (SMTP port 1025, web UI on port 8025). No real email ever leaves your machine.
- **Without it:** You might send real emails by mistake while testing.
- **Alternative:** MailHog (no longer actively maintained).
- **Phase:** 1, 2.

### Kafka UI
- **What:** A web page that shows Kafka topics, messages, consumer groups and lag.
- **In OrderFlow:** Port 8085. You use it to look at events and at messages in `.dlq` topics.
- **Without it:** You read Kafka only with command line tools, which is slower when learning.
- **Phase:** 1, 2.

### LocalStack
- **What:** A tool that imitates many AWS services on your machine.
- **Like:** A flight simulator for AWS.
- **In OrderFlow:** Test the S3 to SQS to Lambda flow and your Terraform code for free before real AWS.
- **Without it:** Every test costs real AWS time and money.
- **Alternative:** Moto (Python), real AWS in a sandbox account.
- **Phase:** 5.

---

## 6. Packaging and running

### Docker
- **What:** A tool that packages an app and everything it needs into an image, and runs the image as a container.
- **Like:** A shipping container. It looks the same and works the same on any ship or truck.
- **In OrderFlow:** Every service has a multi-stage Dockerfile. Every data store runs as a container.
- **Without it:** "It works on my machine." Each server has different versions of Python, libraries or system packages.
- **Alternative:** Podman.
- **Phase:** All.

### Docker Compose
- **What:** A tool that starts many containers together from 1 file (`docker-compose.yml`).
- **Like:** A recipe card that lists every dish and the order to cook them.
- **In OrderFlow:** Runs the whole Phase 1 system on your machine in `deploy/compose/`.
- **Without it:** You start 15 containers by hand, with the right networks and settings, every time.
- **Alternative:** Kubernetes with kind (Phase 2), Tilt.
- **Phase:** 1.

### Kubernetes
- **What:** A system that runs containers across many machines. You describe what you want (for example "3 copies of order-service"), and it keeps it true: it restarts crashed containers, replaces failed machines and rolls out new versions.
- **Like:** A building manager who keeps every room staffed. If someone leaves, they hire a replacement without being asked.
- **In OrderFlow:** Runs everything from Phase 2 onwards.
- **Without it:** You start, restart, scale and update containers by hand on each server.
- **Alternative:** Amazon ECS (used in Phase 5), HashiCorp Nomad.
- **Phase:** 2, 3, 4.

### kind
- **What:** "Kubernetes in Docker". Runs a real Kubernetes cluster where each node is a Docker container.
- **Like:** A model railway: a real working system, small enough for your desk.
- **In OrderFlow:** Your local cluster for Phases 2, 3 and 4. Free.
- **Without it:** You would need a cloud cluster that costs money per hour.
- **Alternative:** k3d, minikube.
- **Phase:** 2, 3, 4.

---

## 7. Delivery

### GitHub Actions
- **What:** GitHub's built-in automation. It runs jobs (test, build, scan) when you push code or open a pull request.
- **Like:** A quality check line in a factory that every product must pass.
- **In OrderFlow:** Lint, test, build images, scan with Trivy, sign with cosign, push to a registry, and open a pull request that bumps the image tag in the Helm values.
- **Without it:** Someone builds and tests by hand. Untested code reaches the cluster.
- **Alternative:** GitLab CI, Jenkins.
- **Phase:** 2 onwards.

### Trivy
- **What:** A security scanner for container images, files and infrastructure code. It lists known vulnerabilities.
- **Like:** An airport bag scanner.
- **In OrderFlow:** CI fails if an image has a critical vulnerability. Also used to scan Terraform code in Phase 5.
- **Without it:** You ship images with known security holes and do not know it.
- **Alternative:** Grype, Snyk.
- **Phase:** 2, 5.

### cosign
- **What:** A tool from the Sigstore project that signs container images and checks signatures.
- **Like:** A wax seal on a letter. You can tell who sent it and that nobody changed it.
- **In OrderFlow:** CI signs every image it builds. You can later check that only signed images run.
- **Without it:** You cannot prove that the image in the cluster is the one your CI built.
- **Alternative:** Notation (Notary project).
- **Phase:** 2.

### Helm
- **What:** A package manager for Kubernetes. A chart is a set of YAML templates. Values files fill in the differences (image tag, replicas, resources).
- **Like:** A form letter. Same letter, different name and address for each person.
- **In OrderFlow:** 1 shared library chart. Each service only provides a values file. Also used to install tools like Argo CD and Prometheus.
- **Without it:** Copy-pasted YAML for each service and each environment, which slowly drifts apart.
- **Alternative:** Kustomize.
- **Phase:** 2, 3, 4.

### Argo CD
- **What:** A GitOps tool. It watches a Git repository and keeps the cluster equal to what is written there.
- **Like:** A building inspector with the official plans. If a room does not match the plan, they fix it.
- **In OrderFlow:** Deploys everything from `deploy/argocd/` using the app of apps pattern and ApplicationSet for dev, staging and prod.
- **Without it:** People run `kubectl apply` by hand. Nobody knows exactly what is deployed. Rollback is slow and stressful.
- **Alternative:** Flux.
- **Phase:** 2 onwards.

### Argo Rollouts
- **What:** A Kubernetes controller for safer releases: canary and blue-green. It can check metrics during a release and roll back by itself.
- **Like:** Tasting a new dish with 1 table before putting it on the whole menu.
- **In OrderFlow:** New versions get a small share of traffic first. If the Prometheus error rate goes up, the release rolls back automatically.
- **Without it:** A bad version reaches 100% of users at once.
- **Alternative:** Flagger.
- **Phase:** 2.

---

## 8. Scaling and testing under stress

### KEDA
- **What:** Kubernetes Event-driven Autoscaling. It scales pods based on outside signals, such as how many Kafka messages are waiting.
- **Like:** A shop that opens more checkout lines when the queue gets long.
- **In OrderFlow:** Scales the consumers (for example search-indexer) on Kafka consumer lag.
- **Without it:** You scale only on CPU, which does not show that messages are piling up.
- **Alternative:** Kubernetes HPA with custom metrics through Prometheus Adapter.
- **Phase:** 2.

### k6
- **What:** A load testing tool. You write test scripts in JavaScript and it sends many requests at once.
- **Like:** A fire drill with a crowd of practice customers.
- **In OrderFlow:** `loadtest/` scripts that place many orders at the same time, to prove no stock is oversold and to measure latency.
- **Without it:** You find out how the system behaves under load only when real users arrive.
- **Alternative:** Locust (Python), JMeter, Apache Bench.
- **Phase:** 1, 2.

### Chaos Mesh
- **What:** A tool that injects failures into Kubernetes on purpose: kill pods, add network delay, fill disks.
- **Like:** A planned power cut to check that the backup generator works.
- **In OrderFlow:** `chaos/` experiments. Each one has a short write-up of what happened.
- **Without it:** You only learn how the system fails during a real incident.
- **Alternative:** LitmusChaos, simply deleting pods by hand.
- **Phase:** 2.

---

## 9. Observability

Observability means you can understand what the system is doing from the outside. It has 3 kinds of signals: **metrics** (numbers over time), **logs** (text lines about events) and **traces** (the path of 1 request through many services).

### OpenTelemetry
- **What:** An open standard and set of libraries for creating metrics, logs and traces. The OpenTelemetry Collector receives the signals and sends them to the right tools.
- **Like:** A universal power adapter. Your app plugs into 1 thing, and it fits any backend.
- **In OrderFlow:** Every service is instrumented. The trace id is passed through HTTP headers, Kafka headers and RabbitMQ headers, so 1 order is 1 trace.
- **Without it:** Each tool needs its own library, and you cannot follow 1 request across services.
- **Alternative:** Vendor agents (Datadog, New Relic).
- **Phase:** 2 onwards.

### Prometheus
- **What:** A metrics database. It pulls (scrapes) numbers from each service's `/metrics` page every few seconds and lets you query them with PromQL.
- **Like:** A nurse who checks every patient's pulse every few minutes and writes it down.
- **In OrderFlow:** Request rate, errors, latency, Kafka lag, queue depth, saga outcomes.
- **Without it:** You learn that something is broken when users complain.
- **Alternative:** VictoriaMetrics, Amazon CloudWatch metrics.
- **Phase:** 2 onwards.

### Alertmanager
- **What:** Receives alerts from Prometheus, groups them, removes duplicates and sends them to the right place.
- **Like:** A hospital dispatcher who decides which doctor gets paged.
- **In OrderFlow:** Sends alerts for SLO burn rate, high error rates and (Phase 4) security detections.
- **Without it:** Either nobody is told, or everyone gets 100 messages for 1 problem.
- **Alternative:** Grafana Alerting, PagerDuty rules.
- **Phase:** 2, 4.

### Grafana
- **What:** A dashboard tool. It shows data from Prometheus, Loki, Jaeger and OpenSearch in 1 place.
- **Like:** The dashboard of a car.
- **In OrderFlow:** Dashboards for each service and the saga. You click from a metric spike to a trace (exemplars) to its logs.
- **Without it:** The data exists, but nobody can read it quickly.
- **Alternative:** Kibana, OpenSearch Dashboards.
- **Phase:** 2 onwards.

### Loki
- **What:** A log database from Grafana Labs. It stores logs cheaply by indexing only labels, not the full text.
- **Like:** A library that sorts books by shelf labels, and you read the pages when you need them.
- **In OrderFlow:** Stores the JSON logs from every pod. Logs carry `trace_id` so you can jump from a trace to its logs.
- **Without it:** You run `kubectl logs` on each pod, one by one, and logs vanish when pods are deleted.
- **Alternative:** OpenSearch for logs, Amazon CloudWatch Logs.
- **Phase:** 2 onwards.

### Grafana Alloy
- **What:** A collector agent from Grafana Labs. It gathers logs (and can gather metrics and traces) and sends them on. It replaces Promtail, which is deprecated.
- **Like:** A postman who collects letters from every house and takes them to the sorting office.
- **In OrderFlow:** Runs on every node and sends pod logs to Loki.
- **Without it:** Logs stay on each node and are not collected.
- **Alternative:** Fluent Bit, the OpenTelemetry Collector.
- **Phase:** 2 onwards.

### Jaeger
- **What:** A tracing tool. It stores traces and shows each request as a timeline of spans.
- **Like:** A parcel tracking page that shows every stop the parcel made and how long it stayed there.
- **In OrderFlow:** Shows 1 order moving from order-service through Kafka to inventory-service, payment-service and back.
- **Without it:** "Checkout is slow" and you guess which of 5 services is the cause.
- **Alternative:** Grafana Tempo, Zipkin, AWS X-Ray.
- **Phase:** 2 onwards.

---

## 10. Running data stores on Kubernetes

An **operator** is a program that runs inside Kubernetes and knows how to manage 1 kind of software, like a database. You write a short YAML file and the operator does the hard work. We use operators and official charts instead of Bitnami charts, because the free Bitnami images and charts are now restricted.

| Tool | Manages | Phase |
|---|---|---|
| **CloudNativePG** | PostgreSQL clusters: replicas, failover, backups, and databases through its `Database` resource | 2, 3 |
| **Strimzi** | Kafka clusters, topics (`KafkaTopic`), users and Kafka Connect (for Debezium) | 2, 3, 4 |
| **RabbitMQ Cluster Operator** | RabbitMQ clusters | 2 |

- **Without them:** You write and maintain complex StatefulSets, failover and upgrade steps yourself.
- **Alternative:** Official Helm charts, or managed cloud services (Phase 5).

---

## 11. Extending Kubernetes

### Kubebuilder and controller-runtime
- **What:** controller-runtime is a Go library for writing Kubernetes controllers. Kubebuilder is a tool that creates the project skeleton, CRDs, RBAC and webhook code for you, using controller-runtime.
- **Like:** Kubebuilder is the building kit with instructions. controller-runtime is the engine inside.
- **In OrderFlow:** Builds `appstack-operator` and its `AppStack` CRD in `platform/appstack-operator/`.
- **Without it:** You write watch loops, caching, leader election and webhook servers by hand with client-go.
- **Alternative:** Operator SDK (built on the same libraries), Kopf (Python), Metacontroller.
- **Phase:** 3.

### cert-manager
- **What:** A Kubernetes add-on that creates and renews TLS certificates automatically.
- **Like:** An office that renews everyone's ID cards before they expire.
- **In OrderFlow:** Creates the TLS certificate for the operator's webhook server and injects the CA into the webhook configuration.
- **Without it:** You create certificates by hand, and the webhook breaks when they expire.
- **Alternative:** Self-made certificates with a script, the Kubebuilder self-signed option.
- **Phase:** 3.

---

## 12. The Linux kernel

### eBPF
- **What:** A way to run small, safe programs inside the Linux kernel. A verifier checks each program before it runs, so it cannot crash the kernel. Programs attach to hooks like tracepoints and send data to user space.
- **Like:** A security camera that you are allowed to install inside the building's walls, after an inspector checks it is safe.
- **In OrderFlow:** `runtime-sentinel` records process starts, sensitive file opens and network connections on every node.
- **Without it:** You need kernel modules (risky) or slow tools that miss short-lived events.
- **Alternative:** Kernel audit (auditd), Falco (which itself can use eBPF).
- **Phase:** 4.

### cilium/ebpf
- **What:** A Go library for loading eBPF programs, reading eBPF maps and ring buffers. Its `bpf2go` tool compiles C eBPF code and creates Go code to load it.
- **Like:** The remote control for the camera inside the wall.
- **In OrderFlow:** The Go part of runtime-sentinel loads the C programs, reads events and sends them to Kafka.
- **Without it:** You would use libbpf from C, or older tools like BCC that compile on the target machine.
- **Alternative:** libbpf (C), libbpf-rs (Rust), BCC.
- **Phase:** 4.

---

## 13. Cloud and infrastructure as code

### Terraform
- **What:** An infrastructure as code tool. You describe cloud resources in `.tf` files. `terraform plan` shows what will change, `terraform apply` makes it so, `terraform destroy` removes it. It keeps a state file to remember what it created.
- **Like:** An architect's drawing that a robot builder follows exactly, and can also take down.
- **In OrderFlow:** All of Phase 5 in `infra/terraform/`. Remote state in S3 with `use_lockfile` for locking (DynamoDB locking is deprecated).
- **Without it:** You click in the AWS console. You cannot review, repeat or cleanly remove what you made, and forgotten resources keep costing money.
- **Alternative:** OpenTofu, AWS CloudFormation, AWS CDK, Pulumi.
- **Phase:** 5.

### AWS CDK
- **What:** AWS Cloud Development Kit. You describe AWS resources in a programming language (we use TypeScript), and it creates CloudFormation for you.
- **Like:** The same architect's drawing, but written as code with loops and functions.
- **In OrderFlow:** 1 module (the S3, SQS and Lambda flow) is built again in `infra/cdk/` so you can compare it with Terraform.
- **Without it:** You only know 1 way to do infrastructure as code.
- **Alternative:** Terraform, Pulumi.
- **Phase:** 5.

### AWS services used in Phase 5

| Service | What it is | Job in OrderFlow | Without it |
|---|---|---|---|
| **VPC** | Your own private network in AWS | Holds everything, split into public, private and isolated subnets | Resources sit on shared, public addresses |
| **Subnets** | Parts of the VPC | Public for the ALB, private for the apps, isolated for the databases | No layers of protection |
| **NAT gateway** | Lets private resources reach the internet without being reachable | Private tasks can download what they need | Private tasks cannot reach the internet at all |
| **VPC endpoints** | Private links from the VPC to AWS services | S3, SQS, ECR and others are reached without the internet | Traffic goes through the NAT gateway, which costs more and is less private |
| **Security groups** | Firewall rules around each resource | Only the ALB can reach the apps, only the apps can reach the databases | Anything inside the VPC could reach the databases |
| **NACLs** | Firewall rules for whole subnets | A second layer of rules on top of security groups | 1 layer of protection only |
| **ECR** | Container image registry | Stores the OrderFlow images | No private place for your images on AWS |
| **ECS Fargate** | Runs containers without managing servers | Runs order, inventory, payment and worker tasks | You manage EC2 servers yourself |
| **ALB** | Load balancer | Front door to the ECS services | See section 1 |
| **CloudFront** | Content delivery network at the edge | Sits in front of the ALB, handles TLS near the user | Every request travels to your region, no edge protection |
| **AWS WAF** | Web application firewall | Managed rules and rate-based rules block common attacks | Attacks reach your app directly |
| **RDS (PostgreSQL)** | Managed PostgreSQL | The 3 OrderFlow databases | You run backups, patches and failover yourself |
| **ElastiCache** | Managed Redis-compatible cache | Stock holds, cache, rate limits | You run Redis yourself |
| **S3** | Object storage | Invoices bucket, Terraform state, upload trigger | See section 3 |
| **SQS** | Managed queue | Replaces RabbitMQ for the jobs on AWS (`JOB_BACKEND=sqs`), with a `-dlq` queue for each | See RabbitMQ |
| **Lambda** | Runs a function when an event happens | Does the jobs from SQS, such as creating PDF invoices | A container must run all the time waiting for jobs |
| **Secrets Manager** | Stores secrets | Database passwords and keys for the tasks | Secrets end up in code or plain environment files |
| **IAM** | Users, roles and permissions | Each task and function gets only the permissions it needs | Everything can do everything |
| **CloudWatch** | AWS logs, metrics and alarms | Logs from ECS and Lambda, basic alarms | You cannot see what the AWS parts are doing |
| **AWS Budgets** | Spending alerts | Emails you when spend passes a limit | A forgotten resource runs for weeks |

Phase 5 docs explain which parts of OrderFlow run on AWS and which stay local. See [cost and safety](08-cost-and-safety.md) before you create anything.
