# Phase 3 Concepts

Every new idea in this phase, in simple words. For each one: what it is, an everyday comparison where it helps, and what breaks without it. Short terms are also in the [glossary](../common/04-glossary.md).

## Contents

1. [Go primer](#go-primer)
2. [Kubernetes API server and etcd](#kubernetes-api-server-and-etcd)
3. [Desired state and actual state](#desired-state-and-actual-state)
4. [Controllers and the reconcile loop](#controllers-and-the-reconcile-loop)
5. [Informers, caches and work queues](#informers-caches-and-work-queues)
6. [Operators](#operators)
7. [CRDs and schemas](#crds-and-schemas)
8. [Spec, status and conditions](#spec-status-and-conditions)
9. [Owner references and garbage collection](#owner-references-and-garbage-collection)
10. [Finalizers](#finalizers)
11. [Admission control](#admission-control)
12. [JSON Patch](#json-patch)
13. [TLS, x509 certificates and CAs](#tls-x509-certificates-and-cas)
14. [cert-manager](#cert-manager)
15. [RBAC](#rbac)
16. [Leader election](#leader-election)
17. [envtest](#envtest)

---

## Go primer

Only the Go features you need for this phase.

**Structs** hold data. Your `AppStack` type is a struct.

```go
type AppStackSpec struct {
    Image    string `json:"image"`
    Port     int32  `json:"port"`
    Replicas *int32 `json:"replicas,omitempty"`
}
```

The text in back quotes is a **tag**. It tells the JSON encoder the field name. A pointer (`*int32`) means "this field may be missing", which is different from 0.

**Methods** are functions attached to a type. **Interfaces** are a list of methods. Any type that has those methods fits the interface. controller-runtime uses this everywhere: your reconciler fits the `Reconciler` interface because it has a `Reconcile` method.

```go
func (r *AppStackReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
    // ...
}
```

**Errors are values.** Go has no exceptions. A function returns an error, and you check it right away.

```go
if err := r.Get(ctx, req.NamespacedName, &app); err != nil {
    return ctrl.Result{}, client.IgnoreNotFound(err)
}
```

Wrap errors to add context: `fmt.Errorf("create topic %s: %w", name, err)`.

**context.Context** carries a deadline and a "stop" signal. You pass `ctx` into every call that talks to the API server. If the operator is shutting down, the calls stop instead of hanging. This is how Go follows the rule "every network call has a timeout".

**Goroutines** are light threads started with `go f()`. **Channels** pass values between them. You will rarely write these yourself in an operator, because controller-runtime runs the workers for you. You still need to know they exist, so you understand why shared data needs care.

**Modules**: `go.mod` lists your dependencies and their versions, like `pyproject.toml` with a lock file.

---

## Kubernetes API server and etcd

**What it is.** The API server is the front door of Kubernetes. Every tool (`kubectl`, Argo CD, controllers, the kubelet) reads and writes objects only through it. It stores the objects in **etcd**, a small, reliable key-value database.

**Comparison.** The API server is the reception desk of a big office. Nobody walks into the records room (etcd) directly. Everyone asks reception.

**Without it.** Every tool would need to talk to the database directly, with no single place for login checks, permission checks and validation. 2 tools could write conflicting data.

**Why it matters for you.** Your operator is just another client of the API server. It has no special powers, only the permissions you give it.

---

## Desired state and actual state

**What it is.** You write down what you want (desired state). Kubernetes keeps comparing it with what really exists (actual state) and fixes the difference.

**Comparison.** A thermostat. You set 24 degrees. It does not "run a heating script once". It keeps checking and keeps fixing.

**Without it.** You would write scripts that run step 1, 2, 3. If step 2 fails, or someone changes something later by hand, nothing fixes it.

---

## Controllers and the reconcile loop

**What it is.** A controller is a program that watches some objects and makes the actual state match the desired state. The function that does this is called **Reconcile**. It is called again and again: when the object changes, when a child changes, and on a timer.

Rules for a good Reconcile:

- **Idempotent.** Running it twice gives the same result as running it once. Always "create if missing, update if different", never "create".
- **Level based, not edge based.** Do not ask "what changed?". Ask "what should exist, and what exists now?". The loop might miss an event, but it never misses the current state.
- **Never block.** If something is not ready, return and ask to be called again later (`RequeueAfter`).
- **Return errors.** controller-runtime then retries with growing delays (backoff).

**Without it.** Your operator would work once on a good day, then drift as soon as anything changes or fails.

---

## Informers, caches and work queues

**What they are.**

- An **informer** opens a long-lived watch on the API server and receives every change to a type of object.
- It keeps a local **cache** of those objects in memory. When your code calls `r.Get(...)`, it usually reads from this cache, not from the API server.
- Changes are turned into keys (`namespace/name`) and put in a **work queue**. Workers take keys from the queue and call Reconcile. If 10 changes happen to the same object quickly, the queue holds the key once, so Reconcile runs once with the latest state.

controller-runtime builds all of this for you when you write `For(&AppStack{})`, `Owns(&appsv1.Deployment{})` and `Watches(...)`.

**Without them.** Every reconcile would ask the API server for everything, and a busy cluster would overload it. Many quick changes would cause many wasted reconciles.

**Watch out.** The cache can be a moment behind. That is fine for a level-based loop, but it is why you never assume "I just created it, so Get will return it".

---

## Operators

**What it is.** An operator is a controller plus a custom resource, written to manage 1 kind of thing the way a human expert would. CloudNativePG knows how to run Postgres. Strimzi knows how to run Kafka. Your operator knows how to set up an OrderFlow app.

**Without it.** A person follows a runbook by hand for every new app, and forgets a step sometimes.

---

## CRDs and schemas

**What it is.** A **CustomResourceDefinition (CRD)** teaches the API server a new type, here `AppStack`. After you install it, `kubectl get appstacks` works like `kubectl get pods`.

The CRD includes an **OpenAPI schema**. The API server uses it to reject objects with the wrong shape (a string where a number should be, a missing required field, a number out of range). Kubebuilder writes the schema from your Go struct and markers like:

```go
// +kubebuilder:validation:Minimum=1
// +kubebuilder:validation:Maximum=10
Replicas *int32 `json:"replicas,omitempty"`
```

The schema can also hold **CEL rules** (`x-kubernetes-validations`) for small rules between fields, like "min must not be greater than max".

**Without it.** Nobody can describe "an app" to Kubernetes in 1 object. Bad YAML would be saved and fail later in confusing ways.

**Versions.** `v1alpha1` means "early, may change". Real projects move to `v1beta1` and `v1` with conversion between versions. You do not need conversion in this phase, but be ready to explain what it is.

---

## Spec, status and conditions

**What it is.**

- `spec` is what the user wants. Only users (or Git through Argo CD) write it.
- `status` is what is true now. Only the controller writes it. It is a separate **subresource** (`/status`), so writing status cannot change the spec by accident.
- **Conditions** are a list in the status, 1 per part: `type`, `status` (`True`, `False`, `Unknown`), `reason`, `message`, `lastTransitionTime`, `observedGeneration`.
- `metadata.generation` goes up every time the spec changes. `status.observedGeneration` says which generation the controller last finished. If they differ, the controller has not caught up yet.

**Without it.** Users see "something is wrong" with no idea which part. Tools like Argo CD cannot tell if the app is healthy. You cannot tell if a status is old or current.

---

## Owner references and garbage collection

**What it is.** Each child object (Deployment, Service, ...) gets an `ownerReferences` entry pointing to the AppStack. When the AppStack is deleted, the Kubernetes **garbage collector** deletes the children for you. `controllerutil.SetControllerReference` sets this up.

**Limit.** An owner reference only works inside the same namespace (or from a namespaced child to a cluster-wide owner). An AppStack in `dev` cannot own a KafkaTopic in `kafka`.

**Without it.** Deleting an app leaves old Deployments and Services running and costing resources.

---

## Finalizers

**What it is.** A finalizer is a string in `metadata.finalizers`. While it is there, Kubernetes will not fully delete the object. It only sets `deletionTimestamp`. Your controller sees that, does its cleanup (delete the database, topics, bucket), then removes the finalizer. Only then does the object disappear.

**Comparison.** A "do not close" note on a shop door. The shop cannot close until the last person checks out and removes the note.

**Without it.** Things in other namespaces or outside Kubernetes (topics, databases, buckets) would be left behind forever.

**Danger.** If cleanup keeps failing, the object is stuck in "Terminating". Do not just delete the finalizer by hand without checking what was not cleaned up. Find the error in the operator logs and Events first.

---

## Admission control

**What it is.** After the API server checks who you are (authentication) and what you may do (authorization), it runs **admission** before saving. Admission can change the object or reject it. You can add your own admission steps as **webhooks**: the API server sends the object to your HTTPS endpoint and waits for an answer.

| Type | Runs | Can it change the object? | Use it for |
|---|---|---|---|
| Mutating webhook | First | Yes, by returning a JSON Patch | Defaults, labels, injected settings |
| Validating webhook | After all mutating steps | No, only allow or deny | Rules and policies |

Order matters: validation sees the object after defaults were added, so "requests are required" can be met by the defaulter.

Important settings in the webhook configuration:

- `failurePolicy: Fail` means "if the webhook is down, reject". Safe, but if your operator is broken, nobody can create AppStacks. `Ignore` is the opposite. Choose on purpose and be ready to explain it.
- `sideEffects: None` tells the API server the webhook changes nothing else, so dry runs are safe.
- Webhooks must answer quickly. A slow webhook slows every `kubectl apply`.

**Schema rules or webhook?** Simple shape checks belong in the CRD schema (no running pod needed). Rules that need code or outside data belong in the webhook.

**Without it.** Bad specs get saved, and you find out later when a pod crashes in production. Every team forgets labels or tracing settings in a different way.

---

## JSON Patch

**What it is.** A standard format (RFC 6902) for describing changes to a JSON document as a list of operations.

```json
[
  { "op": "add", "path": "/metadata/labels/app.kubernetes.io~1part-of", "value": "orderflow" },
  { "op": "add", "path": "/spec/env/-", "value": { "name": "OTEL_SERVICE_NAME", "value": "order-service" } }
]
```

Notes: `/` inside a key is written as `~1`, and `-` at the end of a path means "add at the end of the list".

A mutating webhook answers with a JSON Patch like this. In Kubebuilder you edit the Go object, and controller-runtime builds the patch for you by comparing before and after.

**Without it.** The webhook would have to send back the whole object, and 2 webhooks could overwrite each other's changes.

---

## TLS, x509 certificates and CAs

**What it is.**

- **TLS** encrypts a connection and proves the server is who it says it is.
- An **x509 certificate** is the server's ID card. It says "I am `appstack-webhook.appstack-system.svc`" and holds a public key.
- A **Certificate Authority (CA)** signs certificates. A client trusts a server if the certificate is signed by a CA the client trusts.

For webhooks, the API server is the client. It trusts your webhook only if the webhook configuration contains the CA that signed your certificate (the `caBundle` field). The name in the certificate must match the Service DNS name the API server calls.

**Without it.** The API server refuses to call the webhook. If TLS were optional, anyone on the network could pretend to be your webhook and approve bad objects.

---

## cert-manager

**What it is.** An operator that creates and renews certificates inside Kubernetes. You create a `Certificate` object, and cert-manager writes the key and certificate into a Secret. Its **CA injector** reads the annotation `cert-manager.io/inject-ca-from` on your webhook configuration and fills in `caBundle` for you.

**Without it.** You make certificates by hand with `openssl`, paste them into YAML, and the webhook breaks the day they expire.

---

## RBAC

**What it is.** Role-Based Access Control decides what each identity may do.

| Object | Meaning |
|---|---|
| ServiceAccount | The identity a pod runs as. Your operator has its own. |
| Role | A list of allowed actions (verbs) on resources, inside 1 namespace |
| ClusterRole | The same, for the whole cluster or for cluster-wide resources |
| RoleBinding | Gives a Role (or a ClusterRole) to an identity, inside 1 namespace |
| ClusterRoleBinding | Gives a ClusterRole to an identity everywhere |

Verbs: `get`, `list`, `watch`, `create`, `update`, `patch`, `delete`.

**Least privilege** means: only the verbs, resources and namespaces the operator really needs. Test it with:

```bash
kubectl auth can-i delete nodes --as=system:serviceaccount:appstack-system:appstack-operator
```

**Without it.** A bug or a stolen operator token could delete anything in the cluster.

---

## Leader election

**What it is.** You can run 2 or more copies of the operator for availability. Only 1 should make changes at a time, or they fight. They agree on a leader using a `Lease` object. If the leader dies, another copy takes over after the lease expires.

**Without it.** With 2 replicas, both reconcile the same object at once, and you get conflicts and duplicate work. With 1 replica, a crash means no reconciles until the pod restarts.

---

## envtest

**What it is.** A test helper from controller-runtime that starts a real API server and etcd on your machine, without nodes. Your controller runs against it in tests.

What it does **not** have: no kubelet (pods never run), no scheduler, no garbage collector, no other controllers. So in envtest a Deployment never gets ready, and owned objects are not deleted when the owner is deleted. Test those things in the kind end to end test.

**Without it.** You either test only pure functions, or every test needs a full cluster and is slow and flaky.
