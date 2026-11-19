# Phase 2: GitOps and Observability

In Phase 1 you built OrderFlow and ran it with Docker Compose on your machine. In Phase 2 you move the same system onto **Kubernetes**, ship every change through **Git** (GitOps), and make the system **observable**: you can see what it is doing, find out why it is slow, and get an alert when it breaks.

No new business features are added in this phase. The order flow stays the same. What changes is **how it runs, how it is shipped, and how you watch it.**

## What you build

1. A local Kubernetes cluster with [kind](../common/04-glossary.md): 1 control plane node and 2 worker nodes, all running as Docker containers.
2. The data layer (PostgreSQL, Kafka, RabbitMQ, OpenSearch, Redis, S3 storage) running inside Kubernetes, managed by **operators** and official charts. It lives in 2 shared namespaces, `data` and `kafka`, used by all environments to save RAM. You also install **cert-manager**, which Phase 3 needs.
3. A **Helm library chart** (`deploy/helm/orderflow-lib`) that holds the shared Kubernetes templates. Each service has a small chart that uses it.
4. **Argo CD** that watches the Git repository and makes the cluster match it. 3 environments: `dev`, `staging` and `prod`, as 3 namespaces in the same cluster.
5. A **GitHub Actions** pipeline: lint, test, build the image, scan it with Trivy, push it to GHCR, sign it with cosign, and open a pull request that bumps the image tag.
6. **Canary releases** with Argo Rollouts. A new version gets a small share of traffic first. If the error rate goes up, it rolls back by itself.
7. **Observability**: metrics (Prometheus), logs (Loki), traces (Jaeger through OpenTelemetry), dashboards (Grafana), and alerts (Alertmanager). 1 request can be followed from an alert, to its trace, to its exact log line.
8. **SLOs** (service level objectives) for `POST /api/orders` with burn rate alerts.
9. **Autoscaling**: HPA for `order-service`, KEDA for `search-indexer` (Kafka lag) and `notification-worker` (RabbitMQ queue length).
10. **Resilience tests**: k6 load tests and Chaos Mesh experiments (kill pods, add network delay, kill a Kafka broker), each with a short incident write-up.

## Why this phase matters

Real teams do not run `docker compose up` in production. They:

- run many copies of each service on a cluster, so 1 crash does not take the system down,
- never deploy by typing commands; Git is the single place where changes happen,
- release new versions slowly and roll back fast,
- find problems from dashboards and alerts before customers notice.

This phase gives you hands-on experience with each of these.

## What you will learn

| Area | Skills |
|---|---|
| Kubernetes | Pods, Deployments, Services, Gateway API, probes, resource requests and limits, HPA, PDB, StatefulSets, operators |
| Packaging | Helm charts, values per environment, library charts |
| Delivery | GitOps, Argo CD (app of apps, ApplicationSet, sync waves, rollback), GitHub Actions, image scanning and signing |
| Release safety | Canary releases, automatic analysis and rollback with Argo Rollouts |
| Observability | OpenTelemetry, context propagation through HTTP, Kafka and RabbitMQ, Prometheus and PromQL, Grafana, Loki, Jaeger, exemplars |
| SRE | SLI, SLO, error budget, burn rate alerts, load testing, chaos engineering, incident write-ups |
| Scaling | HPA on CPU, KEDA on Kafka lag and RabbitMQ queue length |

## Before you start

- Phase 1 is done: all 5 services work in Docker Compose and the full order flow passes end to end.
- You have read the Kubernetes Concepts pages listed in [references.md](references.md).
- Your machine has enough free RAM. This phase runs many components at once. Read the RAM saving tips in [architecture.md](architecture.md#8-saving-ram) first.

## Files in this folder

| File | What it gives you |
|---|---|
| [architecture.md](architecture.md) | Cluster layout, GitOps flow, telemetry flow, decisions and RAM tips |
| [concepts.md](concepts.md) | Simple explanations of every new idea, and what breaks without it |
| [references.md](references.md) | Official docs to read, which sections, and when |
| [implementation-plan.md](implementation-plan.md) | Milestones M0 to M9 with tasks, tests, and "done when" |

## Done checklist

Phase 2 is done when all of these are true:

- [ ] A fresh kind cluster can be created and filled from Git with no manual `kubectl apply` of app resources (only bootstrap steps).
- [ ] All 5 services run in `dev`, and you can place an order through the Gateway.
- [ ] Argo CD shows every app as `Synced` and `Healthy`.
- [ ] A push to `main` runs CI, produces a signed image in GHCR, and opens a tag bump pull request. Merging it deploys the new version through Argo CD.
- [ ] A deliberately broken release is rolled back by Argo Rollouts without you touching the cluster.
- [ ] Grafana shows request rate, errors and latency for every HTTP service, plus Kafka consumer lag and RabbitMQ queue depth.
- [ ] 1 order shows up in Jaeger as 1 trace that crosses HTTP, Kafka and RabbitMQ.
- [ ] Every log line has a `trace_id`, and you can jump from a trace to its logs in Grafana.
- [ ] SLO burn rate alerts fire during a chaos test and arrive in Mailpit or the local webhook receiver. No real notifications are sent.
- [ ] KEDA scales `search-indexer` and `notification-worker` up under load and back down after.
- [ ] You ran at least 3 chaos experiments and wrote an incident write-up for each.
- [ ] You collected measured numbers (latency, error rate, recovery time) for your CV. Only numbers you measured.
- [ ] Decisions made in this phase are in the decision log in [`PLAN.md`](../../PLAN.md).
