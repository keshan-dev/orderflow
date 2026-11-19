# OrderFlow Docs

This folder explains everything about OrderFlow: what it is, why each tool is used, and how to build it step by step.

OrderFlow is a learning project. It is a small online ordering system (orders, stock, payments, notifications) that is built, deployed, watched and protected the same way real companies do it. The goal is to get real hands-on experience with the full stack used by modern backend and platform teams.

## Start here

Read these in order before you write any code:

1. [The big picture](common/01-big-picture.md): what OrderFlow is, in simple words, and how 1 order moves through the whole system.
2. [Architecture](common/02-architecture.md): every service, database, topic, queue and port. This is the main reference while building.
3. [Tools explained](common/03-tools-explained.md): every tool, what it does, and what goes wrong without it.
4. [Roadmap](common/05-roadmap.md): the 5 phases, their order, and how they depend on each other.
5. [Dev environment](common/06-dev-environment.md): what to install on your machine.

## Folder map

```
docs/
  README.md                    <- you are here
  interview-readiness.html     <- open in a browser; practice questions and answers
  common/                      <- end to end docs that apply to every phase
    01-big-picture.md
    02-architecture.md
    03-tools-explained.md
    04-glossary.md
    05-roadmap.md
    06-dev-environment.md
    07-conventions.md
    08-cost-and-safety.md
  phase-1-order-platform/         <- the application itself
  phase-2-gitops-observability/   <- ship it to Kubernetes and watch it
  phase-3-kubernetes-operator/    <- extend Kubernetes with Go
  phase-4-ebpf-security-agent/    <- watch the system from the Linux kernel
  phase-5-aws-terraform/          <- run it on real AWS, built with code
```

## What is inside each phase folder

Every phase folder has the same 5 files, so you always know where to look:

| File | What it gives you |
|---|---|
| `README.md` | What you build in this phase, why, what you will learn, and the "done" checklist |
| `architecture.md` | The design for this phase: diagram, parts, data flow, and the decisions with reasons |
| `concepts.md` | Simple explanations of every new idea in this phase, and what breaks without it |
| `references.md` | The official docs to read, which sections, and when to read them |
| `implementation-plan.md` | Step by step milestones, each with tasks, how to test it, and when it counts as done |
| `commit-plan.md` | Phase 1 only for now: the build order as a list of Conventional Commits, with a check for each |

## Phases at a glance

| Phase | Name | Main skills |
|---|---|---|
| 1 | [Order platform](phase-1-order-platform/README.md) | Python, Go, PostgreSQL, Redis, Kafka, RabbitMQ, OpenSearch, S3, Docker |
| 2 | [GitOps and observability](phase-2-gitops-observability/README.md) | Kubernetes, Helm, Argo CD, GitHub Actions, Prometheus, Grafana, Loki, OpenTelemetry, Jaeger |
| 3 | [Kubernetes operator](phase-3-kubernetes-operator/README.md) | Go, Kubebuilder, CRDs, webhooks, TLS, RBAC |
| 4 | [eBPF security agent](phase-4-ebpf-security-agent/README.md) | eBPF (C), Go, Linux kernel, Kafka, OpenSearch |
| 5 | [AWS with Terraform](phase-5-aws-terraform/README.md) | Terraform, AWS VPC, ECS Fargate, RDS, CloudFront, WAF, Lambda, SQS |

## Rules that apply everywhere

- Build locally first. Only Phase 5 touches real AWS, and only after you write down a budget and a spend limit. See [cost and safety](common/08-cost-and-safety.md).
- Decisions go into the decision log in [`PLAN.md`](../PLAN.md) on the same day.
- Only write on your CV what you have actually built and measured.
