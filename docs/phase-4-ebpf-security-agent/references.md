# Phase 4 References

Read these in the order shown. You do not need to read everything before you start. Each row says when to read it.

## Start here (before M0)

| Doc | What it includes | Read when |
|---|---|---|
| **ebpf.io** (the "What is eBPF?" page and the docs section) | What eBPF is, hooks, maps, helpers, the verifier, and the wider ecosystem of tools | Before M0. A good 1 hour overview. |
| **Learning eBPF** (book by Liz Rice, O'Reilly) | A beginner path: first program, maps, program types, BTF and CO-RE, the verifier, eBPF for security and networking | Chapters 1 to 5 before M1. Later chapters during M2 to M5. This is your main guide. |

## While building the agent (M1 to M5)

| Doc | What it includes | Read when |
|---|---|---|
| **cilium/ebpf docs and examples** (the GitHub repository and pkg.go.dev) | The Go library to load programs, attach to tracepoints, and read ring buffers. The `examples` folder has small working programs for tracepoints, kprobes and ring buffers. | M1. Copy the structure of the tracepoint and ring buffer examples. |
| **bpf2go** (part of cilium/ebpf, `cmd/bpf2go`) | The tool that compiles your C file and generates Go code to load it | M1 |
| **Linux kernel BPF docs** (docs.kernel.org/bpf) | Official reference: program types, map types, helper functions, BTF, the verifier, ring buffer | When a book example does not match your kernel, or the verifier rejects your program |
| **libbpf-bootstrap** (GitHub) | Small, working eBPF C programs (for example tracing exec) that show modern CO-RE style | M2 to M4, as patterns for your C code |
| **bpftool** (man page and `bpftool help`) | Generate `vmlinux.h`, list loaded programs and maps, inspect what is running | M0 (generate `vmlinux.h`) and any time you debug |
| **Linux tracepoint formats** (on your own machine under `/sys/kernel/tracing/events/` or `/sys/kernel/debug/tracing/events/`) | The exact fields each tracepoint gives you, in the `format` file of each event | M2 to M4, before writing each program |

## Running it in Kubernetes (M5 to M6)

| Doc | What it includes | Read when |
|---|---|---|
| **Kubernetes docs: DaemonSet** | How DaemonSets work, scheduling on every node, updates | M6 |
| **Kubernetes docs: Downward API** | How to give a pod its own node name as an env var | M5 |
| **Kubernetes docs: Using RBAC Authorization** | Roles, ClusterRoles, ServiceAccounts for a read-only agent | M5 |
| **Kubernetes docs: "Configure a Security Context for a Pod or Container"** | `privileged`, capabilities, `hostPID` and other security settings | M6 |
| **Linux capabilities man page** (`man 7 capabilities`) | What each capability allows, including `CAP_BPF`, `CAP_PERFMON`, `CAP_SYS_RESOURCE` | M6, when you reduce privileges |
| **Linux cgroups v2 docs** (docs.kernel.org, "Control Group v2") | How cgroup v2 folders work under `/sys/fs/cgroup` | M5, when you map cgroup ids to containers |

## Pipeline, storage and alerts (M6 to M7)

| Doc | What it includes | Read when |
|---|---|---|
| **franz-go docs** (pkg.go.dev, github.com/twmb/franz-go) | A Go Kafka client: producing, batching, error handling | M6, for the agent's Kafka producer |
| **confluent-kafka-python docs** | The Python Kafka client: consumer, commits, error handling. Same as Phase 1. | M7, for detection-service |
| **OpenSearch docs: Index State Management (ISM)** | Policies, states, actions such as delete and rollover | M7 |
| **OpenSearch docs: Index templates and Bulk API** | Field types for new daily indices, and fast bulk writes | M7 |
| **Prometheus Alertmanager docs** (including the API section) | How to send alerts with `POST /api/v2/alerts`, grouping and routing | M7 |
| **Grafana docs: OpenSearch data source** | How to show OpenSearch data in Grafana panels | M8 |

## Optional

| Doc | What it includes | Read when |
|---|---|---|
| **Ollama docs** | Run a local LLM for free, for the optional incident summary | Only if you build the optional AI summary |
| **BPF Performance Tools** (book by Brendan Gregg) | Deep reference on tracing with eBPF, many real tool examples | After Phase 4, to go deeper |

## Tip

When the verifier rejects your program, copy the full error message and read it from the bottom. The last lines usually say exactly which instruction is unsafe. Search the cilium/ebpf and libbpf-bootstrap issues for the same message before changing your design.
