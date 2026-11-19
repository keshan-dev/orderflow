# Phase 2 References

The official docs for this phase. Do not read everything at once. The **When** column tells you which milestone in the [implementation plan](implementation-plan.md) needs it. Always read the docs for the exact version you install, and write that version down.

## 1. Kubernetes and the cluster

| Doc | Read these sections | When |
|---|---|---|
| **Kubernetes Docs: Tutorials** | "Learn Kubernetes Basics" (all modules) | Before M0 |
| **Kubernetes Docs: Concepts** | Workloads (Pods, Deployments, StatefulSets), Services, Load Balancing and Networking, Configuration (ConfigMaps, Secrets, resource management), Horizontal Pod Autoscaling | Before M0, then as needed |
| **Kubernetes Docs: Tasks** | Configure Liveness, Readiness and Startup Probes; Specifying a Disruption Budget for your Application; HorizontalPodAutoscaler Walkthrough | M2 |
| **kind Docs** | Quick Start, Configuration (multi node clusters, extra port mappings), Local Registry, LoadBalancer | M0 |
| **metrics-server** (GitHub README) | Installation, flags for local clusters | M0 (needed for HPA and `kubectl top`) |
| **Gateway API Docs** | Introduction, API Overview, the HTTP routing guide | M0 |
| **Envoy Gateway Docs** | Quickstart, the tasks on HTTP routing | M0 |

## 2. Data layer on Kubernetes

| Doc | Read these sections | When |
|---|---|---|
| **CloudNativePG Docs** | Quickstart, Bootstrap, PostgreSQL Configuration, Declarative Database Management, Logical Replication, Connecting from an application (Secrets) | M1 |
| **Strimzi Docs** | Deploying and Managing (Kafka in KRaft mode, node pools, `KafkaTopic`, Kafka Connect with the `build` section, `KafkaConnector`) | M1 |
| **Debezium Docs** | PostgreSQL Connector; Outbox Event Router, especially placing extra outbox fields as Kafka headers | M1, and again in M6 for trace headers |
| **RabbitMQ Cluster Operator Docs** | Installation, Using the operator (`RabbitmqCluster`), Messaging Topology Operator (optional) | M1 |
| **OpenSearch Docs** | Install with Helm; Important settings (`vm.max_map_count`); Security plugin settings for local dev | M1 |
| **Docker Official Images: `redis`** | The image page on Docker Hub (configuration, persistence) | M1 |

## 3. Helm

| Doc | Read these sections | When |
|---|---|---|
| **Helm Docs** | Chart Template Guide (all of it), Chart Best Practices Guide, Library Charts, Charts (`Chart.yaml`, dependencies) | M2 |

## 4. Argo CD and Argo Rollouts

| Doc | Read these sections | When |
|---|---|---|
| **Argo CD Docs** | Getting Started; Cluster Bootstrapping (the app of apps pattern); Automated Sync Policy (prune, self heal); Sync Phases and Waves; Helm support | M4 |
| **Argo CD ApplicationSet Docs** | Introduction, Generators (List, Git, Matrix), Template fields | M4 |
| **Argo Rollouts Docs** | Getting Started, Canary strategy, Analysis and Progressive Delivery, the Prometheus metric provider, Rollback | M8 |

## 5. CI and supply chain

| Doc | Read these sections | When |
|---|---|---|
| **GitHub Actions Docs** | Workflow syntax, Using secrets, Publishing Docker images, Working with the Container registry (GHCR), Security hardening (pin actions by commit SHA, `GITHUB_TOKEN` permissions) | M5 |
| **GitHub Docs: Billing for GitHub Actions and Packages** | Included minutes and storage for your plan | M5, before you start |
| **Trivy Docs** | Container image scanning, severity filters, exit codes; the `trivy-action` README | M5 |
| **Sigstore Docs** | cosign: Signing Containers, keyless signing with OIDC in GitHub Actions, verifying signatures | M5 |

## 6. Observability

| Doc | Read these sections | When |
|---|---|---|
| **OpenTelemetry Docs: Concepts** | Signals (traces, metrics, logs), Context Propagation, Sampling | M6 |
| **OpenTelemetry Docs: Python** | Getting Started, zero code (automatic) instrumentation, manual spans, propagation | M6 |
| **OpenTelemetry Docs: Go** | Getting Started, instrumentation libraries (`otelhttp`), propagation | M6 |
| **OpenTelemetry Docs: Collector** | Configuration (receivers, processors, exporters, pipelines), deployment on Kubernetes, the tail sampling processor | M6 |
| **kube-prometheus-stack** (prometheus-community Helm chart README) | Install, values for Prometheus, Grafana, Alertmanager | M6 |
| **Prometheus Operator Docs** | `ServiceMonitor`, `PrometheusRule` | M6, M7 |
| **Prometheus Docs** | Data model, Metric types, Querying basics and functions, Histograms and summaries, Instrumentation best practices, Alerting rules, Feature flags (exemplar storage) | M6, M7 |
| **Prometheus Python client and Go client docs** | Counters, histograms, exemplars | M6 |
| **Alertmanager Docs** | Configuration (routes, receivers, email and webhook receivers) | M7 |
| **Grafana Docs** | Dashboards, Prometheus data source (exemplars), Loki data source (derived fields), Jaeger data source (trace to logs) | M6 |
| **Grafana Loki Docs** | Get started, LogQL, Labels best practices | M6 |
| **Grafana Alloy Docs** | Collect Kubernetes logs and send to Loki; Migrate from Promtail | M6 |
| **Jaeger Docs** | Getting Started, Deployment on Kubernetes, the Jaeger v2 architecture | M6 |

## 7. SRE, scaling and resilience

| Doc | Read these sections | When |
|---|---|---|
| **Google SRE Book** (free online) | Monitoring Distributed Systems (the 4 golden signals), Service Level Objectives, Postmortem Culture | Before M6 |
| **Google SRE Workbook** (free online) | Implementing SLOs, Alerting on SLOs (burn rate, multi window alerts) | M7 |
| **KEDA Docs** | Concepts (`ScaledObject`), Scalers: Apache Kafka, RabbitMQ Queue | M9 |
| **k6 Docs** | Get started, Scenarios, Thresholds, Checks | M9 |
| **Chaos Mesh Docs** | Quick start, installing with Helm (container runtime and socket settings for kind), PodChaos, NetworkChaos | M9 |

## Reading tips

- Start each tool with its Getting Started page, make it work, then read the deeper sections.
- When a doc and a blog post disagree, trust the official doc for your installed version.
- Write the versions you install into `PLAN.md`, so the setup can be repeated.
