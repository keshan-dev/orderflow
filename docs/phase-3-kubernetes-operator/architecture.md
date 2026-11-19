# Phase 3 Architecture: appstack-operator

This doc explains how `appstack-operator` is designed. For the names of services, topics and databases, see the main [architecture](../common/02-architecture.md).

## 1. The big idea

Kubernetes works by **desired state**. You tell it what you want, and controllers keep working until the real world matches.

`appstack-operator` adds 1 new desired state: an `AppStack`. It is a short description of an app and what it needs. The operator turns it into the 10 or more lower-level resources a real app needs, and keeps them correct.

## 2. Where everything runs

The operator does not create a new database server, Kafka cluster or MinIO. Those were installed in Phase 2. The operator creates **a piece inside each one** for every app.

| Namespace | What lives there | Installed by |
|---|---|---|
| `appstack-system` | The operator itself | Argo CD, from the operator Helm chart |
| `dev` (also `staging`, `prod`) | The apps: Deployments, Services, HTTPRoutes, HPAs, Secrets, and the `AppStack` objects | The operator |
| `data` | The shared CloudNativePG cluster, Redis and MinIO | Phase 2 |
| `kafka` | The shared Strimzi Kafka cluster | Phase 2 |

The namespace and cluster names above are examples. Use the names your Phase 2 setup really has. The operator reads them from command-line flags, so nothing is hard-coded:

| Flag | Example value |
|---|---|
| `--postgres-cluster` | `data/orderflow-pg` |
| `--kafka-cluster` | `kafka/orderflow-kafka` |
| `--redis-url` | `redis://redis.data.svc:6379` |
| `--minio-endpoint` | `http://minio.data.svc:9000` |
| `--gateway` | the Gateway name and namespace from Phase 2 |
| `--otel-endpoint` | the OpenTelemetry Collector address from Phase 2 |

## 3. Diagram

```
  developer
     |  kubectl apply -f appstack.yaml   (or Argo CD syncs it from Git)
     v
+--------------------+       1. mutate      +--------------------------+
|  Kubernetes API    | -------------------> | mutating webhook         |
|  server            | <------------------- | adds labels, defaults,   |
|                    |    JSON Patch        | OpenTelemetry env vars   |
|                    |                      +--------------------------+
|                    |       2. validate    +--------------------------+
|                    | -------------------> | validating webhook       |
|                    | <------------------- | allow or reject + reason |
|                    |                      +--------------------------+
|                    |   3. saved in etcd                (both webhooks run inside
+---------+----------+                                  the operator pod, over TLS
          |                                             with a cert from cert-manager)
          | 4. watch event
          v
+--------------------+
|  controller        |  reconcile loop: read AppStack, compare, create or update children,
|  (operator pod)    |  write status
+---------+----------+
          | 5. creates and updates
          v
 In namespace dev (owned by the AppStack):             In other namespaces (NOT owned, cleaned by finalizer):
  - Deployment  (env vars wired in)                     - data:  CNPG Database + role entry
  - Service                                             - data:  bucket Job (MinIO client)
  - HTTPRoute   (attached to the Phase 2 Gateway)       - kafka: Strimzi KafkaTopic objects
  - HorizontalPodAutoscaler
  - Secret      (DATABASE_URL)
```

## 4. The AppStack resource

Group `platform.orderflow.dev`, version `v1alpha1`, kind `AppStack`, short name `as`. It is namespaced.

### Spec (what you want)

| Field | Type | Meaning |
|---|---|---|
| `image` | string | Container image with a fixed tag or digest. `latest` is not allowed. |
| `port` | int | Port the app listens on |
| `replicas` | int | Starting number of pods, 1 to 10 |
| `resources` | requests and limits | CPU and memory. Limits are required. Requests get defaults. |
| `route.pathPrefix` | string | Path on the Gateway, for example `/api/orders` |
| `autoscaling.minReplicas`, `maxReplicas` | int | HPA range, max 10 |
| `autoscaling.cpuPercent` | int | Target CPU use, default 70 |
| `database.enabled` | bool | Create a PostgreSQL database for this app |
| `database.name` | string | Database name, for example `orders_db`. Default: the app name with `_db` added. |
| `database.deletionPolicy` | `Retain` or `Delete` | What happens to the data when the AppStack is deleted. Default `Retain`. |
| `cache.enabled` | bool | Give the app a Redis key prefix on the shared Redis |
| `topics[]` | list | Kafka topics: `name`, `partitions`, `withRetryAndDlq` |
| `bucket.enabled` | bool | Create an S3 bucket in MinIO |
| `bucket.deletionPolicy` | `Retain` or `Delete` | Default `Retain` |
| `env[]` | list | Extra environment variables for the app |

The limits (1 to 10 replicas, max 10 for autoscaling) are our own choice for a laptop-sized cluster. They are not Kubernetes rules.

### Status (what is true right now)

The operator writes the status. Users never edit it.

| Field | Meaning |
|---|---|
| `observedGeneration` | The spec version the operator last finished working on. If it is lower than `metadata.generation`, the operator has not caught up yet. |
| `conditions[]` | 1 entry per part, each `True`, `False` or `Unknown`, with a reason and a message |
| `url` | The public path of the app |
| `databaseSecretName` | Name of the Secret with `DATABASE_URL` |

Conditions:

| Condition | True when |
|---|---|
| `DeploymentReady` | Enough pods are ready |
| `RouteReady` | The HTTPRoute is accepted by the Gateway |
| `DatabaseReady` | The CNPG Database reports it is applied, and the Secret exists |
| `CacheReady` | The Redis settings are in the Deployment |
| `TopicsReady` | Every Strimzi KafkaTopic reports Ready |
| `BucketReady` | The bucket Job finished successfully |
| `Ready` | All of the above that are enabled are True |

Example of what `kubectl get appstack` shows (with printer columns):

```
NAME            READY   URL            AGE
order-service   True    /api/orders    5m
```

## 5. Environment variables wired into the app

The operator adds these to the Deployment, so the app never needs hard-coded addresses:

| Variable | Comes from |
|---|---|
| `DATABASE_URL` | The Secret the operator created (Secret reference, not plain text) |
| `REDIS_URL`, `REDIS_KEY_PREFIX` | `--redis-url` flag, and `<namespace>.<appstack-name>:` |
| `KAFKA_BOOTSTRAP_SERVERS` | The Strimzi cluster bootstrap address |
| `KAFKA_TOPICS` | Comma separated list from `spec.topics` |
| `S3_ENDPOINT`, `S3_BUCKET` | `--minio-endpoint` flag and the bucket name |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME` | Added by the mutating webhook |

The Phase 1 services must read these names. If a service reads a different name (for example `ORDERS_DB_URL`), either change the service to read `DATABASE_URL` or map it with `spec.env`.

## 6. How each part is created

| Part | Kubernetes object | Owned by AppStack? | How it is cleaned up |
|---|---|---|---|
| App pods | `Deployment` (apps/v1) | Yes | Garbage collection |
| Network inside cluster | `Service` | Yes | Garbage collection |
| Public route | `HTTPRoute` (Gateway API) | Yes | Garbage collection |
| Autoscaling | `HorizontalPodAutoscaler` (autoscaling/v2) | Yes | Garbage collection |
| DB connection string | `Secret` | Yes | Garbage collection |
| Database | CloudNativePG `Database` in `data` | No, different namespace | Finalizer |
| Database user | Entry in the CNPG `Cluster` managed roles, password from a Secret | No | Finalizer |
| Kafka topics | Strimzi `KafkaTopic` in `kafka` | No, different namespace | Finalizer |
| Bucket | A `Job` running the MinIO client `mc mb --ignore-existing` | No | Finalizer runs a cleanup Job when the policy is `Delete` |
| Cache | Nothing new, only env vars | n/a | n/a |

Why some parts are not owned: **owner references cannot point across namespaces.** A KafkaTopic in `kafka` cannot be owned by an AppStack in `dev`. That is exactly why the operator needs a finalizer. Every object it creates outside the app namespace gets the label `platform.orderflow.dev/appstack: <namespace>.<name>`, so the operator can find and delete them later.

Check the exact field names of the CNPG `Database`, the CNPG managed roles and the Strimzi `KafkaTopic` in their docs for the versions you installed in Phase 2. They change between versions.

### Why Redis is a key prefix, not a new Redis

Options:

1. A new Redis pod per app: strong isolation, but heavy for a laptop cluster and more to watch.
2. A shared Redis with a key prefix per app: light and simple, but any app could still read another app's keys if it ignores the prefix.
3. A shared Redis with a Redis ACL user per app, allowed only `~<prefix>*` keys: real isolation, a bit more work.

We start with option 2 and list option 3 as a stretch task. The decision and the risk are written down, which is what matters in an interview.

## 7. The reconcile flow, step by step

The controller runs this every time the AppStack or any child changes, and also on a timer.

1. **Get** the AppStack. If it is gone, stop. Nothing to do.
2. **Deleting?** If `deletionTimestamp` is set, run cleanup (step 10) and stop.
3. **Add the finalizer** `platform.orderflow.dev/cleanup` if it is missing, save, and continue.
4. **Database** (if enabled): make sure the password Secret, the role entry and the CNPG `Database` exist. Build the `DATABASE_URL` Secret in the app namespace. Read the Database status and set `DatabaseReady`.
5. **Topics**: for each entry, create or update a `KafkaTopic` (plus `.retry` and `.dlq` when `withRetryAndDlq` is true). Delete topics that were removed from the spec. Set `TopicsReady`.
6. **Bucket** (if enabled): create the bucket Job if it has not succeeded yet. Set `BucketReady`.
7. **Deployment**: create or update it with the image, port, resources, env vars and probes on `/healthz` and `/readyz`. Set `DeploymentReady`.
8. **Service, HTTPRoute, HPA**: create or update each one. Set `RouteReady`.
9. **Status**: set `Ready`, set `observedGeneration`, save the status. Emit a Kubernetes Event for anything important ("Created database orders_db").
10. **Cleanup on delete**: for each outside object, apply the deletion policy (delete it, or leave it and remove only the label). When all are gone, remove the finalizer. Kubernetes then deletes the AppStack, and garbage collection removes the owned children.

Rules that keep the loop safe:

- **Idempotent.** Every step uses "create or update" (`controllerutil.CreateOrUpdate`), so running the loop 100 times gives the same result as running it once.
- **No waiting inside the loop.** If something is not ready yet (a database still being created), set the condition to `False` with a reason and return `RequeueAfter`. The loop must never block.
- **Errors go back to the work queue.** Returning an error makes controller-runtime retry with growing delays (backoff), so a broken dependency does not cause a tight loop.
- **Watches on owned objects.** The controller watches Deployments, Services, HTTPRoutes, HPAs and Secrets it owns (`Owns(...)`). If someone deletes the Deployment by hand, the controller gets an event and creates it again.
- **Watches on outside objects.** KafkaTopic and CNPG Database changes are mapped back to their AppStack with the label above (`Watches(...)` with a map function).

## 8. Webhooks

Kubernetes calls the webhooks **before** it saves an AppStack. The mutating webhook runs first, then the validating webhook. Both run inside the operator pod on port 9443 over HTTPS.

### Mutating webhook (defaults)

| What it adds | Why |
|---|---|
| Labels `app.kubernetes.io/name`, `app.kubernetes.io/part-of: orderflow`, `app.kubernetes.io/managed-by: appstack-operator` | Every app gets the same labels, so dashboards and selectors work |
| Default resource requests if missing | The scheduler needs requests to place pods well |
| `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME` in `spec.env` if missing | Every app sends traces to the Phase 2 collector without extra work |
| `autoscaling.cpuPercent: 70`, deletion policies `Retain` | Safe defaults |

In Kubebuilder you change the Go object in a `Default` function. controller-runtime compares the old and new object and sends Kubernetes the difference as a **JSON Patch**. You should still understand JSON Patch, because that is what travels over the wire and what you see when you debug.

### Validating webhook (rules)

| Rule | Example message |
|---|---|
| Resource limits must be set | `spec.resources.limits: CPU and memory limits are required` |
| Image must have a fixed tag or digest, not `latest` | `spec.image: tag "latest" is not allowed, use a version tag or digest` |
| `replicas` 1 to 10, `minReplicas` not above `maxReplicas`, `maxReplicas` not above 10 | `spec.autoscaling: minReplicas (8) is greater than maxReplicas (4)` |
| Topic names use only lowercase letters, numbers, `.` and `-`, and start and end with a letter or number | `spec.topics[1].name: "Orders_Events" is not a valid topic name` |
| `database.name` uses only lowercase letters, numbers and `_` | `spec.database.name: "orders-db" is not valid` |
| On update: `database.name` cannot change | `spec.database.name is immutable` |

Some simple rules (types, required fields, number ranges) can also be written as CRD schema rules with Kubebuilder markers. Use the schema for simple shape checks and the webhook for rules that need code. Both are explained in [concepts.md](concepts.md#admission-control).

### Webhook TLS

The API server only talks to webhooks over HTTPS, and it must trust the certificate.

1. cert-manager (installed in Phase 2) has an `Issuer` that makes a self-signed CA.
2. A `Certificate` asks for a serving certificate for the webhook Service name. cert-manager puts it in a Secret.
3. The operator pod mounts that Secret.
4. The webhook configuration objects have the annotation `cert-manager.io/inject-ca-from`. The cert-manager **CA injector** copies the CA into them, so the API server trusts the operator.
5. cert-manager renews the certificate before it expires. No certificate is ever committed to Git.

Kubebuilder generates most of this under `config/certmanager` and `config/webhook`. You turn it on in `config/default/kustomization.yaml`.

## 9. RBAC (permissions)

The operator runs as its own ServiceAccount. Permissions are written as Kubebuilder markers above the reconcile function, and `make manifests` turns them into RBAC YAML.

| Resource | Verbs | Where | Why |
|---|---|---|---|
| `appstacks` | get, list, watch, update, patch | all app namespaces | Read the desired state, add or remove the finalizer |
| `appstacks/status` | get, update, patch | all app namespaces | Write status. Kept separate so status writes cannot change the spec. |
| `appstacks/finalizers` | update | all app namespaces | Needed to set owner references with `blockOwnerDeletion` |
| `deployments`, `services`, `secrets`, `horizontalpodautoscalers`, `httproutes` | get, list, watch, create, update, patch, delete | app namespaces | Manage owned children |
| `events` | create, patch | app namespaces | Tell users what happened |
| CNPG `databases`, `clusters` | get, list, watch, create, update, patch, delete (patch only on `clusters`) | `data` only | Create the database and the role entry |
| `jobs` | get, list, watch, create, delete | `data` only | Bucket create and delete Jobs |
| Strimzi `kafkatopics` | get, list, watch, create, update, patch, delete | `kafka` only | Manage topics |
| `leases` | get, create, update | `appstack-system` only | Leader election |

What the operator does **not** get: no access to Pods it does not need, no `nodes`, no `clusterroles`, no `*` wildcards, and no `secrets` outside the namespaces listed above. The permissions for `data` and `kafka` are a namespaced `Role` and `RoleBinding`, not a cluster-wide one. Kubebuilder markers support a `namespace=` option for this.

## 10. Testing

| Level | Tool | What it proves |
|---|---|---|
| Unit | `go test` | Pure functions: name building, env var building, validation rules, JSON Patch results |
| Integration | envtest | The controller against a real API server and etcd (no nodes, no kubelet). Children are created, status is set, finalizer works. |
| End to end | Kubebuilder e2e test on kind | The full operator image with webhooks, cert-manager, CNPG and Strimzi. Apply, check, delete, check cleanup. |

Note: envtest has no kubelet and no garbage collector, so pods never start and owned objects are not deleted automatically there. Test garbage collection in the kind e2e test, not in envtest.

## 11. Shipping and watching

- Image built and pushed by the Phase 2 GitHub Actions pipeline, then loaded into kind or pulled from the registry.
- Helm chart for the operator, including CRDs, RBAC, webhook configuration, cert-manager objects and a metrics Service.
- Argo CD `Application` in `deploy/argocd/` installs the chart. The CRD is large, so Argo CD may need the `ServerSideApply=true` sync option.
- controller-runtime exposes metrics such as `controller_runtime_reconcile_total`, `controller_runtime_reconcile_errors_total`, `controller_runtime_reconcile_time_seconds` and `workqueue_depth`. Prometheus from Phase 2 scrapes them. Add a Grafana panel for reconcile rate, error rate and queue depth.
- Leader election stays on, so you can run 2 operator replicas and only 1 makes changes at a time.

## 12. Decisions

| Decision | Why | What we gave up |
|---|---|---|
| Kubebuilder + controller-runtime | It is the most common way to write Go operators. It generates CRD YAML, RBAC, webhooks, cert-manager wiring and test setup, so you focus on the logic. | Less control than raw client-go, and some generated files you must learn to read |
| Reuse CNPG, Strimzi and MinIO instead of running databases ourselves | Those operators already handle backups, failover and topic config well. Our operator only asks them for a piece. This is how real platform teams build. | Depends on their CRD versions, which can change |
| Shared Postgres cluster, 1 database per app | Matches the "1 database per service" rule from the main architecture, without 5 Postgres servers on a laptop | Apps share the server's CPU and memory |
| Redis key prefix per app | Light and simple for a local cluster | Weak isolation until Redis ACLs are added |
| Finalizer for outside objects | Owner references cannot cross namespaces, so without a finalizer the database and topics would be left behind | Deletion can get stuck if cleanup keeps failing. You must know how to fix that safely. |
| Deletion policy, default `Retain` | Deleting an AppStack by mistake should not destroy data | You must set `Delete` on purpose for a full cleanup |
| Status conditions instead of a single "phase" string | Each part reports separately, so you see exactly what is not ready and why. This is the Kubernetes API convention. | More status code to write |
| Webhook for logic, CRD schema for simple shape checks | Schema checks are fast and need no running pod. The webhook handles rules that need code. | Rules live in 2 places |
| Bucket made by a Job with the MinIO client | Simple and easy to see in `kubectl` | Slower than calling the MinIO API from Go. Calling the API directly is a fine later change. |
