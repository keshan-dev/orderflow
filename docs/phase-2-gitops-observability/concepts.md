# Phase 2 Concepts

Every new idea in this phase, in simple words. Each one has **what it is**, **how OrderFlow uses it**, and **what breaks without it**. For short definitions, see the [glossary](../common/04-glossary.md).

## Part A: Kubernetes basics

### Pod
- **What:** the smallest thing Kubernetes runs. Usually 1 container (sometimes a helper container next to it). Pods are temporary: they can die and be replaced at any time, with a new IP address.
- **In OrderFlow:** every copy of `order-service` is 1 pod.
- **Without it:** there is no way to run containers on Kubernetes at all. Pods are the base unit.

### Deployment
- **What:** tells Kubernetes "keep 3 copies of this pod running, with this image". If a pod dies, the Deployment makes a new one. When you change the image, it replaces pods a few at a time (rolling update).
- **In OrderFlow:** each service is a Deployment (or an Argo Rollout, which works the same way but adds canary steps).
- **Without it:** a crashed pod stays dead, and you replace it by hand.

### StatefulSet
- **What:** like a Deployment, but each pod has a fixed name and its own disk that stays when the pod restarts. Used for databases.
- **In OrderFlow:** Redis. The operators also use StatefulSets or similar for Kafka, PostgreSQL and OpenSearch.
- **Without it:** a database pod restarts with an empty disk and the data is gone.

### Service
- **What:** a fixed name and address for a group of pods. Pods come and go, but `order-service` always points to the healthy ones.
- **In OrderFlow:** `inventory-service` calls `http://inventory-service:8002`, not a pod IP.
- **Without it:** every caller must track pod IPs that keep changing.

### Gateway and HTTPRoute (Gateway API)
- **What:** the way traffic from outside gets into the cluster. A `Gateway` is the door. An `HTTPRoute` says "requests to `/api/orders` go to `order-service`". Envoy Gateway is the program that makes this real.
- **In OrderFlow:** this replaces the nginx load balancer from Phase 1. ingress-nginx, the older way, is retired.
- **Without it:** nothing outside the cluster can reach your API, or each service needs its own exposed port.

### ConfigMap and Secret
- **What:** a ConfigMap holds settings (like `KAFKA_BOOTSTRAP_SERVERS`). A Secret holds sensitive values (like database passwords). Both are given to pods as environment variables or files.
- **In OrderFlow:** `DATABASE_URL` is built from the Secret that CloudNativePG creates. Other settings, like `KAFKA_BOOTSTRAP_SERVERS` and `OPENSEARCH_URL`, come from ConfigMaps in the Helm chart.
- **Without it:** settings are baked into the image, so you need a new image for each environment, or passwords end up in Git.
- **Note:** a Kubernetes Secret is only base64 encoded, not encrypted. Never commit real Secret values to Git.

### Probes (liveness and readiness)
- **What:** Kubernetes asks your pod 2 questions. **Liveness** (`/healthz`): "are you alive?" If not, the pod is restarted. **Readiness** (`/readyz`): "can you take traffic now?" If not, the Service stops sending requests to it.
- **In OrderFlow:** `/readyz` returns not ready until the database and Kafka connections work.
- **Without it:** traffic is sent to pods that are still starting or are stuck, and users get errors.

### Requests and limits
- **What:** a **request** is the CPU and memory a pod is guaranteed. The scheduler uses it to pick a node. A **limit** is the most it may use. Too much memory and the pod is killed (OOMKilled).
- **In OrderFlow:** every chart sets both. They are also needed for HPA, which measures CPU as a percentage of the request.
- **Without it:** 1 hungry pod can starve the others on the node, and HPA cannot work.

### HPA (Horizontal Pod Autoscaler)
- **What:** adds or removes pods based on a metric, usually CPU.
- **In OrderFlow:** `order-service` goes from 2 to more pods under load, and back down after.
- **Without it:** you pick a fixed number of pods. Too few and you fail under load; too many and you waste resources.

### PDB (PodDisruptionBudget)
- **What:** a rule like "at least 1 pod of `order-service` must always be running". Kubernetes respects it during planned work like draining a node.
- **In OrderFlow:** each HTTP service has a PDB.
- **Without it:** a node drain can stop all copies of a service at once.

### Operator and CRD
- **What:** a **CRD** (Custom Resource Definition) adds a new kind of object to Kubernetes, like `Kafka` or `Cluster` (PostgreSQL). An **operator** is a program that watches those objects and does the expert work: create pods, set up replication, handle failover.
- **In OrderFlow:** CloudNativePG, Strimzi, RabbitMQ Cluster Operator, KEDA, Argo Rollouts and Chaos Mesh are all operators. In Phase 3 you write your own.
- **Without it:** running a database on Kubernetes means writing and fixing all the setup and recovery steps yourself.

## Part B: Packaging and delivery

### Helm chart and values
- **What:** a **chart** is a package of Kubernetes YAML templates. **Values** fill in the blanks: image tag, replica count, memory. 1 chart + `values-dev.yaml` = dev; same chart + `values-prod.yaml` = prod.
- **In OrderFlow:** each service has a chart with 3 values files.
- **Without it:** you copy YAML for each environment. The copies drift apart and prod breaks in ways dev never showed.

### Library chart
- **What:** a Helm chart that only holds shared templates and installs nothing by itself. Other charts include it.
- **In OrderFlow:** `orderflow-lib` holds the Deployment, Service, HTTPRoute, HPA, ServiceMonitor and PDB templates for all 5 services.
- **Without it:** 5 charts each have their own copy of the same templates, and a fix must be made 5 times.

### GitOps and drift
- **What:** **GitOps** means Git holds the desired state of the cluster, and a tool makes the cluster match Git. **Drift** is when the cluster is different from Git, usually because someone changed it by hand.
- **In OrderFlow:** every change to the cluster is a commit. Argo CD applies it.
- **Without it:** nobody knows exactly what runs in prod, changes are not reviewed, and rollback means guessing.

### Argo CD: sync and self heal
- **What:** **sync** means "apply what is in Git to the cluster". **Self heal** means "if someone changes the cluster by hand, put it back to what Git says". **Rollback** means going back to an earlier Git version.
- **In OrderFlow:** auto sync and self heal are on for `dev`. For `prod` you can use manual sync, so a person clicks sync after checking.
- **Without it:** someone runs `kubectl apply` from their laptop, and the cluster slowly stops matching any record.

### App of apps and ApplicationSet
- **What:** **app of apps** is 1 Argo CD Application whose job is to create other Applications. An **ApplicationSet** generates many Applications from a template and a list, for example 5 services x 3 environments.
- **In OrderFlow:** `root-app.yaml` creates the rest. The ApplicationSet creates `order-service-dev`, `order-service-staging`, and so on.
- **Without it:** you write 15 nearly identical Application files by hand.

### Sync waves
- **What:** an annotation (`argocd.argoproj.io/sync-wave`) that sets the order Argo CD applies things in. Lower numbers first.
- **In OrderFlow:** operators (wave 0), then data layer (wave 1), then services (wave 2).
- **Without it:** Argo CD may create a `Kafka` object before Strimzi is installed, and the sync fails.

### Canary vs blue green
- **What:** both release a new version safely.
  - **Canary:** send a small part of traffic to the new version, check the numbers, then increase step by step.
  - **Blue green:** run the full new version next to the old one, test it, then switch all traffic at once.
- **In OrderFlow:** canary with Argo Rollouts, because it limits the damage of a bad release to a small share of users.
- **Without it:** every release goes to 100% of users at once. A bug hits everyone.

### Analysis and automatic rollback
- **What:** during a canary, an **AnalysisTemplate** runs a Prometheus query (for example "5xx error rate of the canary"). If the result is bad, Argo Rollouts aborts and goes back to the old version.
- **In OrderFlow:** this is the "bad release rolls itself back" demo.
- **Without it:** a person must watch dashboards during every release and react fast enough.

### Image scanning and signing
- **What:** **scanning** (Trivy) looks inside the image for packages with known vulnerabilities (CVEs). **Signing** (cosign) adds a signature that proves the image was built by your CI and not changed later.
- **In OrderFlow:** CI fails on CRITICAL vulnerabilities, then signs every pushed image.
- **Without it:** you may ship known security holes, and you cannot prove an image in the cluster is the one CI built.

## Part C: Observability

### Metrics, logs and traces
- **Metrics:** numbers over time. "Requests per second", "error rate", "p95 latency". Cheap to store, great for dashboards and alerts. They tell you **that** something is wrong.
- **Logs:** text events. "Payment failed for order 123: card declined". They tell you **what** happened in 1 place.
- **Traces:** the path of 1 request through all services, with timing for each step. They tell you **where** time was spent or where it failed.
- **Without them:** you learn about problems from users, and you guess which service is the cause.

### Prometheus and PromQL basics
- **What:** Prometheus visits each `/metrics` endpoint every few seconds (scraping) and stores the numbers. PromQL is its query language.
- **3 queries to know:**
  - `rate(http_requests_total[5m])`: requests per second over the last 5 minutes.
  - `sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))`: error ratio.
  - `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))`: p95 latency.
- **Metric types:** counter (only goes up, like total requests), gauge (goes up and down, like queue length), histogram (counts values in buckets, used for latency).

### Labels and cardinality
- **What:** labels add detail to a metric, like `service="order-service"` or `status="500"`. **Cardinality** is the number of different label combinations. Each combination is a separate time series.
- **Rule:** never use a label with unbounded values, like `order_id` or `user_id`. That creates millions of series and Prometheus runs out of memory.
- **In OrderFlow:** use labels like `service`, `route`, `method`, `status`. Put `order_id` in logs and traces, not in metric labels.

### Spans and context propagation
- **What:** a trace is made of **spans**. Each span is 1 piece of work (1 HTTP call, 1 database query, 1 Kafka message). Spans have parent and child links. **Context propagation** passes the trace id from 1 service to the next, usually in a `traceparent` header.
- **In OrderFlow:** the context must travel through HTTP headers, Kafka headers (through the outbox and Debezium) and RabbitMQ headers. See [architecture.md](architecture.md#trace-context-across-async-hops).
- **Without it:** you get many small unconnected traces instead of 1 trace for 1 order.

### Sampling
- **What:** keeping only some traces to save storage. **Head sampling** decides at the start ("keep 10%"). **Tail sampling** decides at the end, so it can keep all slow or failed traces. Tail sampling runs in the OpenTelemetry Collector.
- **In OrderFlow:** locally you can keep 100%. Learn tail sampling in the Collector so you can explain it.
- **Without it:** at high traffic, trace storage becomes very large and expensive.

### Exemplars
- **What:** a trace id attached to a single metric sample. In Grafana, a dot on a latency graph links straight to the trace of that slow request.
- **In OrderFlow:** the latency histogram of `order-service` carries exemplars. In Prometheus, exemplar storage is a feature you must turn on.
- **Without it:** you see "p99 latency is high" but must search for a matching trace by hand.

## Part D: Reliability (SRE)

### SLI, SLO and error budget
- **SLI** (indicator): a measured number about user experience. Example: "share of `POST /api/orders` requests that did not return 5xx".
- **SLO** (objective): the target for the SLI. Example: "99% of order requests succeed, measured over 28 days". You choose the number.
- **Error budget:** what is left. With a 99% SLO, 1% of requests may fail. If the budget is used up, you slow down releases and fix reliability first.
- **In OrderFlow:** 2 SLOs for `POST /api/orders`: availability and latency (for example, "95% faster than a threshold you choose after measuring").
- **Without it:** "is the system OK?" has no clear answer, and alerts fire on every small blip.

### Burn rate and multi window alerts
- **What:** **burn rate** is how fast you are using the error budget. Burn rate 1 means you would use exactly the whole budget by the end of the window. Burn rate 10 means 10 times faster. **Multi window** alerts check a long window and a short window together, so they fire fast on big problems and stop quickly after the fix.
- **In OrderFlow:** follow the "Alerting on SLOs" chapter of the SRE Workbook. For local demos, shorten the windows so you can see alerts fire during a chaos test, and note that real windows are longer.
- **Without it:** you either alert on every short spike (people ignore alerts) or alert too late.

### KEDA
- **What:** KEDA scales a workload on events outside the pod, like Kafka lag or queue length. It can scale to 0.
- **In OrderFlow:** `search-indexer` scales on the lag of consumer group `search-indexer` on `orders.events`. `notification-worker` scales on the length of `notifications.email` and `invoices.generate`.
- **Important:** a Kafka consumer group can use at most 1 consumer per partition. More pods than partitions just sit idle.
- **Without it:** a worker scaled on CPU may stay small while thousands of messages wait, because waiting does not use CPU.

### Chaos engineering
- **What:** breaking things on purpose in a controlled way, to check the system behaves as you expect. Each experiment has a **hypothesis** ("if 1 order-service pod dies, the error rate stays under the SLO"), the action, and a check.
- **In OrderFlow:** Chaos Mesh kills pods, adds network delay between services, and kills a Kafka broker. k6 creates load at the same time. You write an incident write-up after each.
- **Without it:** you find out how the system fails only when it fails for real, at the worst time.

### Load testing
- **What:** sending many requests on purpose to see how the system behaves: latency, errors, where it saturates.
- **In OrderFlow:** k6 scripts in `loadtest/` call `POST /api/orders` with a new `Idempotency-Key` each time.
- **Without it:** you do not know your limits, and your SLO numbers are guesses.
