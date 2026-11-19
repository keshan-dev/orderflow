# Phase 3: Kubernetes Operator

In this phase you extend Kubernetes itself. You write `appstack-operator`, a program in Go that adds a new kind of Kubernetes object called `AppStack`.

A developer writes 1 short YAML file that says "I want an app with this image, a database, a cache, 2 Kafka topics and a bucket". The operator reads it and creates everything the app needs. When the developer deletes the file, the operator cleans everything up.

The code lives in `platform/appstack-operator/`. It runs on the kind cluster you built in [Phase 2](../phase-2-gitops-observability/README.md).

## What you build

```yaml
apiVersion: platform.orderflow.dev/v1alpha1
kind: AppStack
metadata:
  name: order-service
  namespace: dev
spec:
  image: ghcr.io/you/order-service:1.4.0
  port: 8001
  replicas: 2
  autoscaling: { minReplicas: 2, maxReplicas: 6 }
  database: { enabled: true, name: orders_db }
  cache: { enabled: true }
  topics: [ { name: orders.events, partitions: 3 } ]
  bucket: { enabled: false }
```

From this file the operator creates:

- a Deployment, a Service, an HTTPRoute and an HPA,
- a PostgreSQL database and a Secret with its connection string,
- the Kafka topics,
- an S3 bucket in MinIO (when `bucket.enabled` is true),
- the environment variables that tell the app where all of these are.

It also checks every `AppStack` before Kubernetes saves it. A bad spec (no resource limits, an image tagged `latest`, a bad topic name) is rejected with a clear message.

## Why this phase matters

In Phase 2 you used Kubernetes. In Phase 3 you learn how Kubernetes works inside: the API server, controllers, the reconcile loop, webhooks, TLS and RBAC. Tools you already used (Argo CD, CloudNativePG, Strimzi, cert-manager) are all operators built the same way. After this phase you can read their code and understand their behaviour.

It also gives you real Go practice, which you need again in [Phase 4](../phase-4-ebpf-security-agent/README.md).

## What you will learn

- How the Kubernetes API, etcd and controllers fit together
- How to write a reconcile loop that is safe to run again and again
- Custom Resource Definitions (CRDs), spec and status, status conditions
- Owner references, garbage collection and finalizers
- Validating and mutating admission webhooks, and JSON Patch
- TLS certificates for webhooks with cert-manager
- Least-privilege RBAC
- Testing with unit tests, envtest and an end to end test on kind
- Shipping an operator with Helm and Argo CD, and watching it with Prometheus

## Before you start

- Phase 2 is done: the kind cluster runs, and Argo CD, Prometheus, the Gateway, CloudNativePG, Strimzi, Redis and MinIO are installed.
- You can read basic Go. If not, do milestone M0 in the [implementation plan](implementation-plan.md) first.
- You have read [concepts.md](concepts.md).

## Files in this folder

| File | What it gives you |
|---|---|
| [architecture.md](architecture.md) | Design, diagrams, the reconcile flow, decisions with reasons |
| [concepts.md](concepts.md) | Every new idea in simple words, and what breaks without it |
| [references.md](references.md) | The official docs to read, and when |
| [implementation-plan.md](implementation-plan.md) | Milestones M0 to M8, each with tasks, tests and "done when" |

## Done checklist

Phase 3 is done when all of these are true:

- [ ] `kubectl apply -f order-service-appstack.yaml` creates a working order-service with its database, topics, route and autoscaler.
- [ ] `kubectl get appstack` shows `Ready=True`, and each condition (`DatabaseReady`, `TopicsReady` and the others) is correct.
- [ ] Deleting the `AppStack` removes every child resource, including the database, topics and bucket when the deletion policy is `Delete`.
- [ ] With the deletion policy `Retain`, the database and bucket stay after deletion.
- [ ] A bad spec is rejected by the validating webhook with a clear message.
- [ ] The mutating webhook adds default labels, default resource requests and OpenTelemetry settings.
- [ ] Webhook TLS certificates come from cert-manager. No certificate is committed to Git.
- [ ] The operator's RBAC lists only the permissions it needs, and each one is explained.
- [ ] Unit tests, envtest tests and the kind end to end test pass in CI.
- [ ] The operator is installed by Argo CD from a Helm chart.
- [ ] Prometheus scrapes the operator metrics, and a Grafana panel shows reconcile rate and errors.
- [ ] You can run the demo in the [implementation plan](implementation-plan.md#demo-script) in under 5 minutes.
