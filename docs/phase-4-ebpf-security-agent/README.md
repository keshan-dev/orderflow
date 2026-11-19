# Phase 4: eBPF Security Agent

In this phase you build a security guard that watches every container in the cluster from inside the Linux kernel. It sees which programs start, which sensitive files are opened, and where network connections go. When something looks wrong, it raises an alert that names the exact pod.

## What you build

2 new parts:

| Part | Folder | Language | Job |
|---|---|---|---|
| `runtime-sentinel` | `security/runtime-sentinel/` | C (kernel side) + Go (user side) | Runs on every node as a DaemonSet. Small eBPF programs in the kernel catch events. The Go agent adds pod names and sends the events to Kafka. |
| `detection-service` | `services/detection-service/` | Python | Reads events from Kafka, checks them against rules, saves every event in OpenSearch, and sends alerts to Alertmanager. |

The flow in 1 line:

```
kernel (eBPF) -> ring buffer -> runtime-sentinel (Go) -> Kafka security.events -> detection-service (Python) -> OpenSearch + Alertmanager -> Grafana
```

## Why this phase exists

- Phases 1 to 3 taught you how to build and run the system. This phase teaches you how to see what really happens **inside** it, at the lowest level.
- Logs and metrics only show what the application chooses to report. An attacker who gets a shell inside a container does not write to your logs. The kernel sees everything, because every action goes through it.
- It covers skills that are rare and valued: eBPF, Linux internals, containers at the kernel level, and high volume event pipelines.

## What you will learn

- How the Linux kernel and user programs talk (system calls).
- How to write small, safe eBPF programs in C and load them from Go.
- How containers are really made (cgroups and namespaces) and how to map a kernel event back to a Kubernetes pod.
- How to run a privileged agent safely as a DaemonSet.
- How to move a large stream of events through Kafka without losing control.
- How to write detection rules and deal with false alarms.
- How to measure the cost (overhead) of your own tool honestly.

## Before you start

You need these from earlier phases:

- [ ] Phase 2 kind cluster running, with Kafka, OpenSearch, Prometheus, Alertmanager and Grafana.
- [ ] OrderFlow services deployed in the cluster (so there is real traffic to watch).
- [ ] The k6 load test from Phase 2 (used to measure overhead).
- [ ] A Linux kernel that supports what eBPF needs. Check this first in [M0 of the plan](implementation-plan.md#m0-environment-check-and-toolchain). If your machine fails the check, use an Ubuntu virtual machine.

## Files in this folder

| File | Read it for |
|---|---|
| [architecture.md](architecture.md) | The design, the event format, the rule format, and the decisions with reasons |
| [concepts.md](concepts.md) | Simple explanations of every new idea (kernel, eBPF, cgroups, ring buffer, and more) |
| [references.md](references.md) | The official docs and books to read, and when |
| [implementation-plan.md](implementation-plan.md) | Step by step milestones M0 to M8 with tests |

## Safety rules for this phase

- Only run the agent on **your own** local cluster or VM.
- Only use harmless "attack" simulations: open a shell with `kubectl exec`, run `curl` to a test IP address, read a protected file. Nothing else.
- Never point any test at a system, IP address or website you do not own.
- The agent runs with high privileges. Never deploy it to a shared or company cluster without approval.
- The optional AI summary feature (see [architecture.md](architecture.md#9-optional-ai-incident-summary)) uses an LLM. A paid LLM API needs a written budget first (spend rule). A local model through Ollama is free.

## Done checklist

Phase 4 is done when all of these are true:

- [ ] `runtime-sentinel` runs as a DaemonSet on every kind node.
- [ ] It catches 3 kinds of events: process start, sensitive file open, outbound TCP connection.
- [ ] Every event has the pod name, namespace and labels attached.
- [ ] Events flow through Kafka topic `security.events` to `detection-service`.
- [ ] All events are stored in OpenSearch indices `security-events-YYYY.MM.DD`, and an ISM policy deletes them after 7 days.
- [ ] At least 4 rules work, and each one has a test.
- [ ] Alerts arrive in Alertmanager and show in a Grafana dashboard.
- [ ] You measured overhead (CPU, memory, p99 latency) with the agent on and off, under the same k6 load, and wrote down the real numbers.
- [ ] The showcase demo works end to end (see [implementation-plan.md](implementation-plan.md#showcase-demo)).
- [ ] Decisions made during this phase are in the decision log in [`PLAN.md`](../../PLAN.md).

## Words you may not know

See [concepts.md](concepts.md) for full explanations, and the [glossary](../common/04-glossary.md) for short definitions.
