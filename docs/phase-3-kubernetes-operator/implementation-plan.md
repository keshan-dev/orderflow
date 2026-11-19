# Phase 3 Implementation Plan

Build `appstack-operator` in 9 small milestones, M0 to M8. Finish and test each one before starting the next. Each milestone should end with a commit and a short note in the decision log in [`PLAN.md`](../../PLAN.md) if you decided anything.

Design details are in [architecture.md](architecture.md). New ideas are explained in [concepts.md](concepts.md). Docs to read for each milestone are in [references.md](references.md).

Commands below are examples. Your kind cluster name, namespaces and image registry come from Phase 2. Use your real values.

---

## M0: Go warm-up

**Goal.** Read and write basic Go comfortably before touching Kubernetes code.

**Tasks**

- [ ] Do A Tour of Go: Basics, Methods and interfaces, and Concurrency up to channels.
- [ ] Read the Effective Go sections on names, errors and interfaces.
- [ ] Write a tiny CLI in Go that reads a YAML file into a struct, checks 3 rules (like the webhook rules), and prints clear errors.
- [ ] Write table-driven tests for it with `go test`.
- [ ] Look at `services/payment-service` from Phase 1 again and make sure you understand every line.

**How to test**

```bash
go test ./...
go vet ./...
```

**Done when.** The CLI works, tests pass, and you can explain structs, interfaces, error wrapping and `context.Context` without notes.

---

## M1: Scaffold the project and the CRD

**Goal.** A Kubebuilder project with the `AppStack` type installed on kind.

**Tasks**

- [ ] Follow the Kubebuilder Book Quick Start once with their example, in a scratch folder. Throw it away.
- [ ] Create the real project:

```bash
cd platform/appstack-operator
kubebuilder init --domain orderflow.dev --repo <your-git-host>/<you>/orderflow/platform/appstack-operator
kubebuilder create api --group platform --version v1alpha1 --kind AppStack
```

- [ ] Write `AppStackSpec` and `AppStackStatus` in `api/v1alpha1/appstack_types.go` with the fields from [architecture.md](architecture.md#4-the-appstack-resource).
- [ ] Add validation markers for simple rules (required fields, `Minimum`/`Maximum` for replicas, `Enum` for deletion policies).
- [ ] Add the status subresource, a short name `as`, and printer columns for `Ready`, `URL` and `Age`.
- [ ] Write `config/samples/` with the order-service example from the [README](README.md#what-you-build).

**How to test**

```bash
make manifests generate
make install                      # installs the CRD into the current kube context
kubectl get crd appstacks.platform.orderflow.dev
kubectl apply -f config/samples/
kubectl get as -n dev
kubectl apply -f bad-replicas.yaml  # replicas: 50, should be rejected by the schema
```

**Done when.** The CRD is installed, the sample is saved, and a sample with `replicas: 50` is rejected by the schema.

---

## M2: Reconcile Deployment and Service

**Goal.** Applying an AppStack creates a running app. Deleting it removes the app.

**Tasks**

- [ ] In `internal/controller/appstack_controller.go`, get the AppStack and return if not found.
- [ ] Build the Deployment in a separate function (`buildDeployment(app) *appsv1.Deployment`) so it can be unit tested.
- [ ] Use `controllerutil.CreateOrUpdate` and `controllerutil.SetControllerReference` for the Deployment and the Service.
- [ ] Add probes on `/healthz` and `/readyz`.
- [ ] Register watches: `For(&AppStack{})`, `Owns(&appsv1.Deployment{})`, `Owns(&corev1.Service{})`.
- [ ] Add RBAC markers for Deployments and Services only.
- [ ] Unit test `buildDeployment` with table-driven tests.

**How to test**

```bash
make run                                  # runs the controller on your machine against kind
kubectl apply -f config/samples/
kubectl get deploy,svc -n dev
kubectl delete deploy order-service -n dev   # the controller should create it again
kubectl delete as order-service -n dev       # Deployment and Service should disappear
```

**Done when.** The app starts. A Deployment deleted by hand comes back within seconds. Deleting the AppStack removes the Deployment and Service through garbage collection.

---

## M3: HTTPRoute and HPA

**Goal.** The app is reachable through the Phase 2 Gateway and scales on CPU.

**Tasks**

- [ ] Add the Gateway API types to the scheme in `cmd/main.go`, and a `--gateway` flag.
- [ ] Create an `HTTPRoute` with `spec.route.pathPrefix`, attached to the Phase 2 Gateway.
- [ ] Create an `autoscaling/v2` HPA from `spec.autoscaling`. When autoscaling is set, do not overwrite `replicas` on the Deployment, or the operator and the HPA will fight.
- [ ] Add `Owns` watches and RBAC markers for both.

**How to test**

```bash
kubectl get httproute,hpa -n dev
curl http://<gateway-address>/api/orders/healthz
```

Then run a short load test from Phase 2 (k6) and watch `kubectl get hpa -n dev -w`.

**Done when.** The route answers through the Gateway, and the HPA adds pods under load and removes them after.

---

## M4: Database, topics and bucket

**Goal.** The app gets its own database, Kafka topics and bucket, and the env vars to reach them.

**Tasks**

- [ ] Add flags: `--postgres-cluster`, `--kafka-cluster`, `--redis-url`, `--minio-endpoint`.
- [ ] Database: create a password Secret, add a role entry to the CNPG Cluster's managed roles, create a CNPG `Database` with that owner, and build a `DATABASE_URL` Secret in the app namespace. Check field names in the CloudNativePG docs for your version.
- [ ] Topics: create a Strimzi `KafkaTopic` for each entry, plus `.retry` and `.dlq` when `withRetryAndDlq` is true. Delete topics removed from the spec.
- [ ] Bucket: create a Job in `data` that runs `mc mb --ignore-existing`. Read MinIO credentials from an existing Secret. Never put them in the AppStack.
- [ ] Cache: add `REDIS_URL` and `REDIS_KEY_PREFIX` env vars.
- [ ] Add the label `platform.orderflow.dev/appstack: <namespace>.<name>` to every object outside the app namespace.
- [ ] Add `Watches` with a label-based map function so changes to these objects trigger the right AppStack.
- [ ] Wire all env vars into the Deployment (see [architecture.md](architecture.md#5-environment-variables-wired-into-the-app)).
- [ ] Make the Phase 1 order-service read `DATABASE_URL`, or map its own variable name with `spec.env`.

**How to test**

```bash
kubectl get database -n data
kubectl get kafkatopic -n kafka -l platform.orderflow.dev/appstack=dev.order-service
kubectl get job -n data
kubectl exec -n dev deploy/order-service -- env | grep -E 'DATABASE_URL|KAFKA|REDIS|S3'
```

Then place 1 order through the API and check it is saved and its event reaches the topic.

**Done when.** order-service, created only from its AppStack, runs end to end: it saves orders, publishes events and uses Redis.

---

## M5: Finalizers, status conditions and Events

**Goal.** Clean deletion of everything, and a status that tells the truth.

**Tasks**

- [ ] Add the finalizer `platform.orderflow.dev/cleanup` on first reconcile.
- [ ] On delete: apply `deletionPolicy` for the database and bucket, delete the topics, then remove the finalizer.
- [ ] Set conditions with `meta.SetStatusCondition`: `DeploymentReady`, `RouteReady`, `DatabaseReady`, `CacheReady`, `TopicsReady`, `BucketReady`, `Ready`. Each with a clear `reason` and `message`.
- [ ] Set `status.observedGeneration` and `status.url`.
- [ ] Return `RequeueAfter` while parts are still being created. Never sleep inside Reconcile.
- [ ] Emit Events for important actions and for errors.
- [ ] Add a CEL rule in the schema: `minReplicas <= maxReplicas`.

**How to test**

```bash
kubectl get as order-service -n dev -o jsonpath='{.status.conditions}' | jq
kubectl describe as order-service -n dev      # look at Events at the bottom
kubectl delete as order-service -n dev
kubectl get database -n data; kubectl get kafkatopic -n kafka -l platform.orderflow.dev/appstack
```

Repeat the delete test once with `deletionPolicy: Retain` and once with `Delete`.

Break it on purpose: stop the Strimzi Topic Operator, apply a new AppStack, and check that `TopicsReady=False` with a useful message while everything else becomes ready.

**Done when.** Delete with `Delete` leaves nothing behind. Delete with `Retain` leaves the database and bucket. Every condition matches reality, including when something is broken.

---

## M6: Webhooks with cert-manager

**Goal.** Defaults are added and bad specs are rejected before they are saved.

**Tasks**

- [ ] Scaffold:

```bash
kubebuilder create webhook --group platform --version v1alpha1 --kind AppStack --defaulting --programmatic-validation
```

- [ ] Defaulter: labels, default resource requests, OpenTelemetry env vars, default deletion policies, default `cpuPercent`.
- [ ] Validator: the rules in [architecture.md](architecture.md#validating-webhook-rules). Return all problems at once, not just the first one, using `field.ErrorList`.
- [ ] Validator on update: `database.name` cannot change.
- [ ] Turn on the cert-manager and webhook sections in `config/default/kustomization.yaml`.
- [ ] Decide `failurePolicy` and write the reason in the decision log.
- [ ] Unit test the defaulter and validator with table-driven tests.
- [ ] Write down, as a JSON Patch, what the defaulter changes for the sample. This is good interview practice.

**How to test**

Webhooks need TLS, so test them in the cluster, not with `make run`:

```bash
make docker-build IMG=<registry>/appstack-operator:dev
kind load docker-image <registry>/appstack-operator:dev --name <kind-cluster>
make deploy IMG=<registry>/appstack-operator:dev
kubectl get certificate -n appstack-system
kubectl apply -f bad-latest-tag.yaml        # should be rejected with a clear message
kubectl apply -f config/samples/ && kubectl get as order-service -n dev -o yaml | grep -A3 labels
```

**Done when.** The sample gets its defaults. Each bad spec (no limits, `latest` tag, bad replicas, bad topic name, changed database name) is rejected with a clear message. The certificate is issued by cert-manager, and the webhook configuration has a `caBundle` filled in by the CA injector.

---

## M7: RBAC hardening and tests

**Goal.** Least-privilege permissions, and tests that catch regressions.

**Tasks**

- [ ] Review every RBAC marker. Remove any you do not need. Use `namespace=` markers so the `data` and `kafka` permissions are namespaced Roles.
- [ ] Write the "why" for each permission in [architecture.md](architecture.md#9-rbac-permissions) if it differs from the plan.
- [ ] Check the operator cannot do things it should not:

```bash
SA=system:serviceaccount:appstack-system:appstack-operator   # use your real ServiceAccount name
kubectl auth can-i delete nodes --as=$SA                      # expect: no
kubectl auth can-i get secrets -n kube-system --as=$SA        # expect: no
kubectl auth can-i create kafkatopics -n kafka --as=$SA       # expect: yes
```

- [ ] envtest tests in `internal/controller/`: children created, status conditions set, finalizer added, cleanup of outside objects. Remember envtest has no garbage collector and no running pods.
- [ ] Extend the Kubebuilder e2e test on kind: install, apply sample, wait for `Ready`, apply bad spec, delete, check cleanup.
- [ ] Add `make test` and the e2e test to the Phase 2 GitHub Actions pipeline.

**How to test**

```bash
make test         # unit + envtest
make test-e2e     # on kind
```

**Done when.** All tests pass locally and in CI, and the `can-i` checks give the expected answers.

---

## M8: Helm chart, Argo CD and metrics

**Goal.** The operator is installed the same way as everything else: from Git, by Argo CD, and watched by Prometheus.

**Tasks**

- [ ] Package the operator as a Helm chart in `deploy/helm/appstack-operator/`. Recent Kubebuilder versions have a Helm plugin that generates a chart from `config/`. If yours does not, write the chart from the `config/` output. Include CRDs, RBAC, webhook configuration, cert-manager objects and the metrics Service.
- [ ] Note in the decision log how CRD upgrades are handled. Helm does not upgrade CRDs placed in the `crds/` folder.
- [ ] Add an Argo CD `Application` in `deploy/argocd/`. Add the `ServerSideApply=true` sync option if Argo CD complains that the CRD is too large.
- [ ] Turn on 2 replicas with leader election. Kill the leader pod and check another takes over.
- [ ] Scrape operator metrics with the same method Phase 2 uses (a `ServiceMonitor` if Phase 2 installed the Prometheus Operator).
- [ ] Add a Grafana panel: reconcile rate, reconcile errors, reconcile time, work queue depth.
- [ ] Move the order-service (and optionally the other services) to AppStack objects in Git, so Argo CD syncs AppStacks and the operator does the rest.

**How to test**

```bash
argocd app get appstack-operator
kubectl get lease -n appstack-system
kubectl delete pod -n appstack-system <leader-pod>
```

In Prometheus, query `rate(controller_runtime_reconcile_total[5m])` and `controller_runtime_reconcile_errors_total`.

**Done when.** A Git commit changes an AppStack, Argo CD syncs it, the operator reconciles it, and the Grafana panel shows the reconcile.

---

## Demo script

Practice until it runs in under 5 minutes.

1. Show the 15 line `order-service` AppStack in Git.
2. `kubectl apply -f order-service-appstack.yaml` (or commit it and let Argo CD sync).
3. `kubectl get as -n dev -w` until `READY` is `True`.
4. `kubectl get deploy,svc,httproute,hpa,secret -n dev` and `kubectl get database -n data`, `kubectl get kafkatopic -n kafka`. Everything was made from 1 file.
5. Place an order through the Gateway with `curl`. It works.
6. `kubectl delete deploy order-service -n dev`. It comes back.
7. `kubectl apply -f bad-latest-tag.yaml`. Show the webhook message.
8. Show the Grafana panel with reconcile rate and errors.
9. `kubectl delete as order-service -n dev` with `deletionPolicy: Delete`. Show that the database, topics and children are all gone.

## Evidence to collect

Write these down from real runs only. Do not estimate.

- Time from `kubectl apply` to `Ready=True`, measured on your kind cluster.
- Time for a hand-deleted Deployment to come back.
- Number of unit, envtest and e2e tests, and the CI run that passed.
- The list of RBAC permissions and the `kubectl auth can-i` results.
- Screenshot of the Grafana operator panel.
- 1 problem you hit (for example a stuck finalizer or a webhook TLS error), how you found the cause, and how you fixed it. Interviewers ask about this more than anything else.
