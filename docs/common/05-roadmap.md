# Roadmap

This page shows the 5 phases, why they come in this order, and how to track your progress.

## 1. The 5 phases

| Phase | Folder | You build | Runs on |
|---|---|---|---|
| 1 | [phase-1-order-platform](../phase-1-order-platform/README.md) | The 5 services, the saga, outbox, Kafka, RabbitMQ, Redis, OpenSearch, S3 | Docker Compose |
| 2 | [phase-2-gitops-observability](../phase-2-gitops-observability/README.md) | Helm chart, Argo CD, GitHub Actions, canary releases, metrics, logs, traces, SLOs, chaos tests | kind |
| 3 | [phase-3-kubernetes-operator](../phase-3-kubernetes-operator/README.md) | `appstack-operator` in Go with the `AppStack` CRD and webhooks | kind |
| 4 | [phase-4-ebpf-security-agent](../phase-4-ebpf-security-agent/README.md) | `runtime-sentinel` eBPF agent and `detection-service` | kind on a kernel with BTF |
| 5 | [phase-5-aws-terraform](../phase-5-aws-terraform/README.md) | OrderFlow on AWS with Terraform, 1 module also in CDK | AWS (needs a written budget) |

## 2. Why this order

Each phase needs something from the phase before it.

```
Phase 1  The app
   |     You need something real to deploy and watch.
   v
Phase 2  Kubernetes, GitOps, observability
   |     You need to know Kubernetes well before you extend it.
   v
Phase 3  Operator in Go
   |     You now know Go and how Kubernetes controllers work.
   v
Phase 4  eBPF agent
   |     Runs as a DaemonSet on your cluster, sends events through Kafka,
   |     and links kernel events to pods.
   v
Phase 5  AWS with Terraform
         Last, because it costs money. By now you know exactly what to build,
         so you spend less time (and money) on AWS.
```

| Phase | Depends on |
|---|---|
| 1 | Docker, Python, basic SQL |
| 2 | Phase 1 services and Dockerfiles |
| 3 | Phase 2 cluster, Helm, cert-manager knowledge, Go from payment-service |
| 4 | Phase 2 cluster, Kafka and OpenSearch from Phase 1, Go from Phase 3, a Linux kernel with BTF |
| 5 | Phase 1 services and images, Phase 2 CI pipeline, a written budget for AWS spend |

## 3. Milestones per phase

These are summaries. Each phase's `implementation-plan.md` has the full steps, tests and "done" rules.

### Phase 1: Order platform
1. Repo skeleton, Docker Compose with PostgreSQL, Redis, nginx.
2. inventory-service: products, stock in Redis with a Lua script, product cache.
3. order-service: orders API, `Idempotency-Key`, rate limit, outbox table.
4. Kafka and Debezium: outbox tables published to topics.
5. payment-service in Go with a fake provider that can fail or be slow.
6. The saga: confirm and cancel paths, compensation, idempotent consumers, retry and DLQ topics.
7. RabbitMQ jobs: email to Mailpit, PDF invoice to MinIO.
8. search-indexer and OpenSearch with an alias.
9. Load and failure tests: many orders at once, kill services, prove no lost or duplicate payments and no oversold stock.

### Phase 2: GitOps and observability
1. kind cluster with Envoy Gateway (Gateway API).
2. Data stores through operators and official charts (CloudNativePG, Strimzi, RabbitMQ Cluster Operator, OpenSearch, MinIO, Redis).
3. Helm library chart and 1 values file per service.
4. GitHub Actions: lint, test, build, Trivy scan, cosign sign, push, bump tag.
5. Argo CD app of apps and ApplicationSet.
6. OpenTelemetry, Prometheus, Grafana, Loki with Alloy, Jaeger. Trace context through Kafka and RabbitMQ.
7. SLOs, burn rate alerts, Alertmanager.
8. Argo Rollouts canary with automatic rollback. KEDA on Kafka lag.
9. Chaos experiments with Chaos Mesh, each with a short write-up.

### Phase 3: Kubernetes operator
1. Go basics refresh, Kubebuilder project, `AppStack` CRD.
2. Reconcile loop that creates Deployment, Service, HTTPRoute, HPA.
3. Database (CloudNativePG `Database`), Kafka topics (Strimzi `KafkaTopic`), S3 bucket.
4. Status conditions, owner references, finalizers.
5. Validating and mutating webhooks with cert-manager TLS.
6. Least privilege RBAC, envtest tests, end to end tests on kind, Helm chart for the operator.

### Phase 4: eBPF security agent
1. Check the kernel (BTF), first "hello" eBPF program.
2. Process exec, file open and network connect events with a ring buffer.
3. Go loader with cilium/ebpf and `bpf2go`.
4. Link events to pods using the cgroup id.
5. DaemonSet, events to Kafka `security.events`.
6. detection-service with rules, OpenSearch `security-events-*` with ISM, alerts to Alertmanager.
7. Measure the agent's overhead under load.

### Phase 5: AWS with Terraform
1. Written budget, AWS Budgets alert, remote state in S3 with `use_lockfile`.
2. VPC with public, private and isolated subnets, NAT, VPC endpoints.
3. ECR, ECS Fargate services behind an ALB.
4. RDS PostgreSQL, ElastiCache, Secrets Manager.
5. CloudFront and WAF.
6. S3 to SQS to Lambda invoice flow, with a DLQ. Same module again in CDK.
7. Test, measure, write up, then `terraform destroy`.

## 4. Tracking progress in PLAN.md

[`PLAN.md`](../../PLAN.md) is the 1 place for status and decisions.

- **Status table:** change a phase from "Not started" to "In progress" to "Done". Write the current milestone next to it, for example "In progress (milestone 4: Debezium)".
- **Decision log:** add a row on the same day for every decision: date, who, what, why. Example: "Use orchestrated saga instead of choreography, because the flow is easier to follow in 1 place."
- **Results:** when you measure something (latency, throughput, overhead), write the real number and how you measured it. Never write a number you did not measure.

## 5. Weekly rhythm

How long each phase takes depends on your experience, your free time and how much goes wrong. Do not plan by days. Plan by milestones, and use a simple loop for each one:

| Step | What you do |
|---|---|
| **1. Read** | Read the milestone's sections in `references.md` and `concepts.md`. Only what you need now. |
| **2. Build** | Make the smallest version that works. Commit often. |
| **3. Break** | Kill it, slow it, send it bad input. Watch what happens. This is where most learning happens. |
| **4. Write up** | 5 to 10 lines: what you built, what broke, what you learned, any decision for `PLAN.md`. |

Rough guidance: Phase 1 is usually the longest, because you learn many tools at once. Phase 4 can be slow if eBPF and C are new to you. Phase 5 should be short on AWS itself, because you prepare and test locally first.

## 6. "Ready for interview" checkpoint per phase

You are ready to talk about a phase when you can do all of these without notes.

### Phase 1
- Draw the architecture from memory and walk 1 order through it.
- Explain the outbox, the saga, idempotent consumers and the DLQ, and show each one in your code.
- Explain Kafka vs RabbitMQ with your own example from OrderFlow.
- Run the "kill services during 1,000 orders" demo and show 0 lost or duplicate payments.

### Phase 2
- Push a change and show it reach the cluster with no manual step.
- Deploy a broken version and show it roll back by itself.
- Go from a Grafana alert to the Jaeger trace to the Loki log line.
- Explain your SLO, error budget and burn rate alert.

### Phase 3
- Apply 1 `AppStack` file and show the full environment appear, then delete it and show cleanup.
- Explain the reconcile loop, finalizers, owner references and why reconcile must be idempotent.
- Show a webhook rejecting a bad spec, and explain how its TLS works.

### Phase 4
- Explain what eBPF is, the verifier, and why it is safer than a kernel module.
- Trigger a suspicious action in a pod and show the alert with the pod name.
- Show the overhead numbers you measured and how you measured them.

### Phase 5
- Run `terraform plan` and explain every resource type.
- Explain why only the ALB is public and how traffic reaches the database.
- Show a WAF rule blocking a test request.
- Explain what it cost, and how you made sure nothing was left running.
