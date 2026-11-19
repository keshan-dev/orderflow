# Phase 2 Architecture

This page shows how OrderFlow runs on Kubernetes, how a code change reaches the cluster, and how telemetry (metrics, logs, traces) flows. The service names, topics, queues and databases are the same as in [the main architecture](../common/02-architecture.md). Nothing in the order flow changes.

## 1. The cluster

```
 Your machine (Docker Desktop)
 +----------------------------------------------------------------------------+
 |  kind cluster "orderflow"                                                  |
 |                                                                            |
 |  +----------------+   +----------------+   +----------------+              |
 |  | control-plane  |   |   worker 1     |   |   worker 2     |              |
 |  | (API server,   |   | (your pods)    |   | (your pods)    |              |
 |  |  scheduler)    |   |                |   |                |              |
 |  +----------------+   +----------------+   +----------------+              |
 |                                                                            |
 |  Namespaces:                                                               |
 |    dev                    the 5 OrderFlow services                         |
 |    staging                the 5 services (off by default)                  |
 |    prod                   the 5 services (off by default)                  |
 |    data                   PostgreSQL (CloudNativePG), Redis, RabbitMQ,     |
 |                           OpenSearch, MinIO: shared by all environments    |
 |    kafka                  Strimzi Kafka, Kafka Connect with Debezium       |
 |    monitoring             Prometheus, Alertmanager, Grafana, Loki, Alloy,  |
 |                           OpenTelemetry Collector, Jaeger                  |
 |    cert-manager           cert-manager (TLS certificates, needed Phase 3)  |
 |    argocd                 Argo CD, Argo Rollouts                           |
 |    envoy-gateway-system   Envoy Gateway (traffic entry)                    |
 |    chaos-mesh             Chaos Mesh                                       |
 |    (operator namespaces)  CloudNativePG, RabbitMQ operator, KEDA, each in  |
 |                           its own default namespace                        |
 +----------------------------------------------------------------------------+
```

The namespace names match the [main architecture](../common/02-architecture.md#11c-kubernetes-namespaces-phase-2-onwards).

- **kind** runs each Kubernetes node as a Docker container. 2 workers let you see pods spread across nodes, and let you test what happens when a node goes away.
- **3 environments as 3 namespaces.** In real companies these are often separate clusters. Namespaces are enough to learn promotion (dev, then staging, then prod) and they save RAM.
- **1 shared data layer.** The data stores run once, in `data` and `kafka`, not once per environment. This saves a lot of RAM. The cost: environments are not isolated from each other at the data level. Because the topics and consumer groups are the same for every environment, **run the apps of only 1 environment at a time**. `dev` is on by default. For the promotion demo, scale `dev` down and turn `staging` on.

## 2. Traffic entry: Gateway API with Envoy Gateway

```
 curl / k6
    |
    |  kubectl port-forward (simple path on Windows)
    v
 Envoy proxy (created by Envoy Gateway)
    |
    |  Gateway "orderflow" + HTTPRoutes
    v
 /api/orders*   -> order-service      (Service, port 8001)
 /api/products  -> inventory-service  (Service, port 8002)
```

- In Phase 1 the load balancer was nginx. In Kubernetes the entry is defined with the **Gateway API**: a `Gateway` (the entry point) and `HTTPRoute` objects (the path rules).
- **Envoy Gateway** is the controller that reads those objects and runs an Envoy proxy.
- Why not ingress-nginx: the Kubernetes project has **retired ingress-nginx**, so new work should use the Gateway API.
- On kind, a `LoadBalancer` Service does not get a reachable IP by itself. The simplest way on Windows is `kubectl port-forward` to the Envoy Service on local port 8080, so the public API stays on port 8080 like in Phase 1. `cloud-provider-kind` is an option if you want real LoadBalancer IPs.

## 3. Data layer

Each data store is run by an **operator** or an official chart. An operator is a program inside the cluster that knows how to install, configure and repair 1 kind of software.

| Store | Namespace | Tool | Notes |
|---|---|---|---|
| PostgreSQL | `data` | CloudNativePG (`Cluster` resource) | 1 instance is enough locally. Creates `orders_db`, `inventory_db`, `payments_db`. Debezium needs logical replication, so check how CloudNativePG sets `wal_level` to `logical`. |
| Kafka | `kafka` | Strimzi (`Kafka` + `KafkaNodePool`, KRaft mode, no ZooKeeper) | 1 broker locally, 3 if you want to test broker failure. **Every topic is a Strimzi `KafkaTopic` resource**, so topics live in Git too. Apps do not auto create topics. |
| Debezium | `kafka` | Strimzi `KafkaConnect` + `KafkaConnector` | Strimzi builds a Connect image with the Debezium PostgreSQL plugin and pushes it to a registry. Use a local registry next to kind. |
| RabbitMQ | `data` | RabbitMQ Cluster Operator (`RabbitmqCluster`) | Queues can be declared by the app on startup, as in Phase 1, or with the Messaging Topology Operator. |
| OpenSearch | `data` | Official OpenSearch Helm chart | Single node locally. OpenSearch needs the `vm.max_map_count` kernel setting raised on the host. See the OpenSearch docs. |
| Redis | `data` | Official `redis` image as a `StatefulSet` | Simple on purpose. Redis is a helper and can be rebuilt from PostgreSQL. |
| S3 | `data` | MinIO, or another S3 compatible store | MinIO community edition changed how it is distributed in 2025, so a prebuilt image may not exist for the version you want. Check before you pin a tag. If none fits, use another S3 compatible store such as SeaweedFS or Garage, and read its own docs for setup. The app only needs the S3 API and `S3_BUCKET`. |

Apps in `dev`, `staging` and `prod` reach these stores across namespaces with full DNS names, for example `redis.data.svc.cluster.local`. They get the addresses through the generic env vars from the [main architecture](../common/02-architecture.md#11b-configuration-env-vars): `DATABASE_URL`, `REDIS_URL`, `KAFKA_BOOTSTRAP_SERVERS`, `RABBITMQ_URL`, `S3_BUCKET`, `OPENSEARCH_URL`. Passwords come from Secrets, never from values files in Git.

**cert-manager** is installed in this phase, in the `cert-manager` namespace. Phase 2 does not need it much, but the Phase 3 operator uses it for its webhook TLS certificates.

**Why not Bitnami charts:** Bitnami changed its free image catalog and most free images are no longer available as before. Operators and official images avoid that problem and are closer to what production teams use.

## 4. Helm charts

```
deploy/helm/
  orderflow-lib/            library chart: shared templates only, installs nothing alone
    templates/
      _deployment.tpl       Deployment, or Argo Rollout when rollout.enabled is true
      _service.tpl
      _httproute.tpl
      _hpa.tpl
      _servicemonitor.tpl   tells Prometheus to scrape /metrics
      _pdb.tpl              PodDisruptionBudget
  order-service/
    Chart.yaml              depends on orderflow-lib
    templates/all.yaml      1 line per object: {{ include "orderflow-lib.service" . }}
    values.yaml             defaults
    values-dev.yaml
    values-staging.yaml
    values-prod.yaml
  inventory-service/        same shape
  payment-service/          same shape
  notification-worker/      same shape, no Service or HTTPRoute, has KEDA ScaledObject
  search-indexer/           same shape, no Service or HTTPRoute, has KEDA ScaledObject
  platform/                 values files for the operators and data layer
```

The library chart keeps the 5 service charts small and consistent. A fix in 1 template fixes all services.

What the library chart always sets:

- Standard labels on every object: `app.kubernetes.io/name`, `app.kubernetes.io/part-of: orderflow`, and `app.kubernetes.io/component`, which is **`api`** for `order-service`, `inventory-service` and `payment-service`, and **`worker`** for `notification-worker` and `search-indexer`. Phase 4 detection rules and the dashboards depend on this label.
- The generic env vars (`DATABASE_URL`, `REDIS_URL`, `KAFKA_BOOTSTRAP_SERVERS`, `RABBITMQ_URL`, `S3_BUCKET`, `OPENSEARCH_URL`), filled from values and Secrets. `DATABASE_URL` is different for each service.

## 5. GitOps flow: from git push to running pod

```
 1. You push code to a branch and open a pull request
        |
 2. GitHub Actions (CI)
        |  ruff + pytest + go test
        |  docker build
        |  Trivy scan  -> fails the build on CRITICAL vulnerabilities
        |  push image to GHCR (ghcr.io/<owner>/order-service:<git-sha>)
        |  cosign sign the image
        |  open a pull request that changes the image tag in values-dev.yaml
        v
 3. You review and merge the tag bump pull request into main
        |
 4. Argo CD sees main changed
        |  renders the Helm chart with values-dev.yaml
        |  compares it with what runs in the cluster
        |  applies the difference
        v
 5. Argo Rollouts starts a canary
        |  20% of pods on the new version, then pause
        |  AnalysisTemplate asks Prometheus: is the error rate OK?
        |    yes -> 50% -> 100%
        |    no  -> automatic rollback to the old version
        v
 6. New version runs. Promotion to staging and prod is another tag bump PR
    on values-staging.yaml and values-prod.yaml.
```

Rules:

- **Nobody runs `kubectl apply` for app resources.** Git is the only way in. If someone changes the cluster by hand, Argo CD shows it as drift and puts it back (self heal).
- The image tag is the **git commit SHA**, never `latest`, so you always know exactly which code runs.

### Argo CD layout

```
deploy/argocd/
  root-app.yaml           the "app of apps": 1 Application that points at this folder
  apps/
    operators.yaml        sync wave 0: operators, CRDs and cert-manager first
    platform.yaml         sync wave 1: data layer in data and kafka (Postgres, Kafka, topics, RabbitMQ, ...)
    monitoring.yaml       sync wave 1: observability stack
    services-appset.yaml  sync wave 2: ApplicationSet for the services
```

Kafka consumer group ids are the service names: `order-service`, `inventory-service`, `payment-service`, `search-indexer`, plus `order-service-jobs` (the part of order-service that turns `OrderConfirmed` into RabbitMQ jobs). Dashboards, lag alerts and KEDA triggers use these exact ids.

The `ApplicationSet` uses a **matrix generator**: list of services x list of environments. That gives 1 Argo CD Application per service per environment, for example `order-service-dev`. Turning an environment on or off is a 1 line change in Git.

**Sync waves** make order matter: operators and CRDs first (wave 0), then the data layer (wave 1), then services (wave 2). Without waves, Argo CD may try to create a `Kafka` resource before the Strimzi CRD exists.

## 6. Telemetry flow

```
                  +-------------------------------+
                  |  order-service, inventory,    |
                  |  payment, workers             |
                  +--+-------------+-----------+--+
                     |             |           |
      /metrics       |  traces     |   logs    |  JSON to stdout,
      (scraped)      |  (OTLP)     |           |  with trace_id
                     v             v           v
               Prometheus   OTel Collector   Grafana Alloy
                     |             |           |
                     |             v           v
                     |          Jaeger        Loki
                     |             |           |
                     +------+------+-----+-----+
                            |            |
                            v            v
                         Grafana    Alertmanager -> Mailpit / local webhook
```

- **Metrics:** each service exposes `/metrics` (already in the [public API table](../common/02-architecture.md#4-public-api-through-the-load-balancer-on-port-8080)). Prometheus finds them through `ServiceMonitor` objects from the library chart.
- **Traces:** the OpenTelemetry SDK in each service sends spans to the OpenTelemetry Collector with OTLP. The Collector sends them to Jaeger. Jaeger v2 accepts OTLP.
- **Logs:** services write JSON logs to stdout. Grafana Alloy collects pod logs and sends them to Loki. Promtail is deprecated, so this phase uses Alloy.
- **Linking the 3 signals:**
  - metric to trace: **exemplars** (a trace id attached to a metric sample),
  - trace to logs: every log line has `trace_id`, and Grafana links a Jaeger span to a Loki query,
  - logs to trace: Grafana turns `trace_id` in a log line into a link to Jaeger.
- **Grafana data sources:** Prometheus, Loki, Jaeger, and also **OpenSearch** (in `data`). Phase 4 security dashboards read from OpenSearch through this data source.
- **Alertmanager** runs as a Service in `monitoring`, so other in-cluster components (including the Phase 4 detection-service) can send alerts to it by its in-cluster address. Find the exact Service name with `kubectl get svc -n monitoring`.

### Trace context across async hops

1 order crosses HTTP, Kafka and RabbitMQ. To keep it as 1 trace, the trace context (the W3C `traceparent` value) must travel with every message.

| Hop | How the context travels |
|---|---|
| HTTP | OpenTelemetry instrumentation for FastAPI, httpx and Go `net/http` adds and reads the `traceparent` header for you |
| Kafka (through the outbox) | Add a `traceparent` column to each `outbox` table and fill it when you write the event. Configure the Debezium Outbox Event Router to place that column as a **Kafka header**. Consumers read the header and continue the trace. |
| RabbitMQ | When order-service publishes a job, put `traceparent` in the message headers. notification-worker reads it before it starts work. |

The Kafka hop is the tricky one. The service does not send to Kafka directly; Debezium does. So the trace context must be stored in the database row.

## 7. Scaling

| Workload | Scaler | Signal | Note |
|---|---|---|---|
| `order-service` | HPA | CPU usage | Needs metrics-server in the cluster |
| `inventory-service`, `payment-service` | HPA | CPU usage | Optional |
| `search-indexer` | KEDA `ScaledObject` | Lag of consumer group `search-indexer` on `orders.events` | More pods than partitions do nothing. Max replicas = number of partitions. |
| `notification-worker` | KEDA `ScaledObject` | RabbitMQ queue length of `notifications.email` and `invoices.generate` | Can scale to 0 when the queues are empty |

## 8. Saving RAM

This phase runs many heavy programs at once. Measure with `docker stats` and `kubectl top pods -A`. Tips:

1. **1 shared data layer.** The data stores run once, in `data` and `kafka`, for all environments. This is already the design.
2. **Run the apps of only 1 environment at a time.** `dev` is on by default; `staging` and `prod` are switched off in the ApplicationSet. This is also needed for correctness, because all environments share the same topics and consumer groups.
3. **1 replica for every data store.** Kafka with 1 broker, PostgreSQL with 1 instance, OpenSearch single node.
4. **Set memory limits**, especially the JVM heap for Kafka and OpenSearch.
5. **Short retention.** Prometheus, Loki and Jaeger keep a few hours or 1 day of data, not weeks.
6. **Turn off what you do not use right now.** Chaos Mesh and k6 only during tests. OpenSearch Dashboards only when you need it.
7. **Give Docker Desktop a memory limit** in `.wslconfig` so Windows stays usable.

## 9. Decisions

| Decision | Why | What we gave up |
|---|---|---|
| kind with 1 control plane + 2 workers | Free, local, close to a real multi node cluster | Not a real cloud cluster; LoadBalancer needs a workaround |
| Gateway API with Envoy Gateway | ingress-nginx is retired; Gateway API is the current Kubernetes standard | Fewer old tutorials to copy from |
| 3 namespaces for 3 environments | Learn promotion without 3 clusters | Weaker isolation than real separate clusters |
| 1 shared data layer in `data` and `kafka` | Saves a lot of RAM on 1 laptop | Environments share data, so only 1 environment's apps run at a time |
| Operators for the data layer, no Bitnami | Bitnami free images are restricted; operators are how teams run stateful software on Kubernetes | More CRDs to learn |
| Helm library chart | 1 place for shared templates; service charts stay tiny | Library charts are harder to debug at first |
| Argo CD app of apps + ApplicationSet | The whole cluster is described in Git; adding an environment is 1 line | More Argo CD concepts to learn |
| Image tag bump through a pull request | Every deploy is reviewed and recorded in Git history | 1 extra merge step per deploy |
| Argo Rollouts canary with Prometheus analysis | Bad releases roll back on their own, based on real numbers | Canary by pod count is rough unless you add traffic routing |
| Metrics by Prometheus scraping, traces by OTLP, logs by Alloy | Each signal uses its most common path, easy to find docs for | 3 pipelines instead of 1 |
| Alerts to Mailpit or a local webhook only | No real notifications reach real people | Not a real on-call setup |
| KEDA for workers, HPA for APIs | Workers should scale on backlog, not CPU | 1 more component |
