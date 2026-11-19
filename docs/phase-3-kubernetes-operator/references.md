# Phase 3 References

The official docs to read for this phase. Do not read everything at once. The "When" column matches the milestones in the [implementation plan](implementation-plan.md).

Always read the docs for the **versions you actually installed**. Operator APIs (CloudNativePG, Strimzi, Gateway API) change between versions, and old blog posts are often wrong.

## Go

| Doc | What it includes | Which parts | When |
|---|---|---|---|
| **A Tour of Go** (go.dev/tour) | Interactive lessons in the browser: basics, structs, methods, interfaces, errors, goroutines | All of "Basics" and "Methods and interfaces". "Concurrency" up to channels. | M0 |
| **Effective Go** (go.dev/doc/effective_go) | How to write Go the normal way: naming, errors, interfaces | Names, Errors, Interfaces | M0, then come back to it |
| **Go standard library: `context`** (pkg.go.dev/context) | How deadlines and cancel signals work | The package overview | M0 |

## Kubebuilder (your main guide)

| Doc | What it includes | Which parts | When |
|---|---|---|---|
| **The Kubebuilder Book** (book.kubebuilder.io) | Step by step guide to building an operator with Kubebuilder | "Quick Start", then the "Tutorial: Building CronJob". Follow it once with their example before you start your own. | M1 |
| Kubebuilder Book: **Implementing a controller** and **Adding a new API** | How Reconcile, `Owns` and status updates fit together | Read while writing M2 | M2 |
| Kubebuilder Book: **Implementing defaulting/validating webhooks** | How `Default` and `Validate*` functions are wired, and how cert-manager is turned on | Whole section | M6 |
| Kubebuilder Book: **Writing controller tests** (envtest) | How to start envtest and write tests with it | Whole section | M7 |
| Kubebuilder Book: **Reference > Markers for Config/Code Generation** | Every `+kubebuilder:` marker (CRD validation, RBAC, webhooks) and what YAML it generates | Look things up when needed | M1 to M7 |

## Kubernetes official docs (kubernetes.io/docs)

| Doc | What it includes | Which parts | When |
|---|---|---|---|
| **Concepts > Extend Kubernetes > Custom Resources** | What CRDs are, when to use them | Whole page | M1 |
| **Concepts > Extend Kubernetes > Operator pattern** | What an operator is and why | Whole page | M1 |
| **Tasks > Extend Kubernetes > Custom Resources > Extend the Kubernetes API with CustomResourceDefinitions** | Schemas, status subresource, printer columns, CEL validation rules | Validation, Subresources, Additional printer columns | M1, M5 |
| **Reference > Access Authn Authz > Dynamic Admission Control** | How webhooks are called, `failurePolicy`, `sideEffects`, timeouts, JSON Patch responses | Whole page | M6 |
| **Owners and Dependents** (under Concepts > Overview) and **Garbage Collection** (under Concepts > Cluster Architecture) | Owner references and how cleanup works | Both pages | M2 |
| **Finalizers** (under Concepts > Overview) | How finalizers block deletion | Whole page | M5 |
| **Reference > Access Authn Authz > Using RBAC Authorization** | Role, ClusterRole, bindings, verbs, aggregation | Whole page | M7 |
| **Tasks > Run Applications > Horizontal Pod Autoscaling** | HPA behaviour and `autoscaling/v2` fields | Whole page | M3 |

## Libraries (pkg.go.dev)

| Doc | What it includes | When |
|---|---|---|
| **sigs.k8s.io/controller-runtime** | API reference: `client`, `controllerutil` (`CreateOrUpdate`, `SetControllerReference`, finalizer helpers), `builder` (`For`, `Owns`, `Watches`), `webhook/admission` | M2 to M7 |
| **k8s.io/client-go** | The lower-level client under controller-runtime: informers, work queues, the `record` package for Events | Read the package overviews to understand what controller-runtime does for you |
| **k8s.io/apimachinery/pkg/api/meta** | `SetStatusCondition` and `FindStatusCondition` for conditions | M5 |

## Tools this operator talks to

| Doc | What it includes | Which parts | When |
|---|---|---|---|
| **cert-manager docs** (cert-manager.io/docs) | Issuers, Certificates, the CA Injector | "Concepts > CA Injector" and "Concepts > Certificate" | M6 |
| **CloudNativePG docs** (cloudnative-pg.io) | The `Database` resource and declarative role management | "Declarative Database Management" and "Database Role Management" | M4 |
| **Strimzi docs** (strimzi.io/docs) | The `KafkaTopic` resource and the Topic Operator | "Using the Topic Operator" in the Deploying and Managing guide | M4 |
| **Gateway API docs** (gateway-api.sigs.k8s.io) | `Gateway` and `HTTPRoute`, how a route attaches to a Gateway | "API Overview" and the HTTPRoute guide | M3 |
| **MinIO client (`mc`) docs** (min.io/docs) | `mc alias set`, `mc mb`, `mc rb` | The pages for these 3 commands | M4 |
| **Argo CD docs** (argo-cd.readthedocs.io) | Sync options, including `ServerSideApply` | "User Guide > Sync Options" | M8 |
| **Prometheus Operator docs** (prometheus-operator.dev), if Phase 2 uses it | `ServiceMonitor` | "Getting Started" and the ServiceMonitor API | M8 |

## Optional, after the phase works

| Doc | What it includes |
|---|---|
| **Kubernetes API Conventions** (in the `kubernetes/community` GitHub repo, `contributors/devel/sig-architecture/api-conventions.md`) | The official rules for spec, status, conditions and naming. Good for interview answers about "why conditions". |
| **Source code of CloudNativePG or Strimzi** on GitHub | Real operators to compare with yours |
