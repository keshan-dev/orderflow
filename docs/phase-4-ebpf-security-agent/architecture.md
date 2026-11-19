# Phase 4 Architecture: eBPF Security Agent

This doc explains how the security agent is designed. It uses the names from the main [architecture doc](../common/02-architecture.md): Kafka topic `security.events`, services `runtime-sentinel` and `detection-service`, and OpenSearch indices `security-events-*`.

## 1. The big picture

```
 Each kind node (all nodes share the same Linux kernel)
 +--------------------------------------------------------------------+
 |                                                                    |
 |  Pods (order-service, inventory-service, ...)                      |
 |     | every action is a system call                                |
 |     v                                                              |
 |  +--------------------- Linux kernel ---------------------------+  |
 |  |  eBPF programs (C)                                           |  |
 |  |   exec.bpf.c     tracepoint sched/sched_process_exec         |  |
 |  |   file.bpf.c     tracepoint syscalls/sys_enter_openat        |  |
 |  |   net.bpf.c      tracepoint sock/inet_sock_set_state         |  |
 |  |        |                                                     |  |
 |  |        v                                                     |  |
 |  |   BPF ring buffer (shared memory between kernel and agent)   |  |
 |  +--------+-----------------------------------------------------+  |
 |           |                                                        |
 |           v                                                        |
 |  runtime-sentinel (Go, 1 pod per node, DaemonSet)                  |
 |    - reads the ring buffer                                         |
 |    - cgroup id -> container id -> pod name, namespace, labels      |
 |    - batches events                                                |
 |    - exposes /metrics (events, drops, Kafka errors)                |
 +-----------+--------------------------------------------------------+
             |
             v
     Kafka topic security.events
             |
             v
     detection-service (Python)
       - checks each event against rules (rules.yaml)
       - writes every event to OpenSearch security-events-YYYY.MM.DD
       - sends matches as alerts to Alertmanager
             |                         |
             v                         v
        OpenSearch               Alertmanager (from Phase 2)
             |                         |
             +-----------+-------------+
                         v
                      Grafana
           (event dashboard + alert panel)
```

## 2. The parts

### 2.1 eBPF programs (kernel side, C)

Small programs that the kernel runs every time a certain event happens. They collect a few fields, do quick filtering, and write a record to the ring buffer. They must be short and safe, because the kernel **verifier** checks them before they can run.

| Program | Hook | What it catches | Filtered in the kernel? |
|---|---|---|---|
| `exec.bpf.c` | tracepoint `sched/sched_process_exec` | Every new program that starts (path, pid, parent pid, command name) | No. Exec events are not too many, and every one matters. |
| `file.bpf.c` | tracepoint `syscalls/sys_enter_openat` | A file being opened | Yes. Only paths that start with a sensitive prefix are sent (see below). Without this filter you would get many thousands of events per second. |
| `net.bpf.c` | tracepoint `sock/inet_sock_set_state` | Outbound TCP connections (when the state changes to `TCP_SYN_SENT`) | Yes. Only the `SYN_SENT` change is sent, all other state changes are dropped. |

Sensitive path prefixes (start with these, keep the list short):

- `/etc/shadow`
- `/etc/sudoers`
- `/root/.ssh/`
- `/var/run/secrets/kubernetes.io/serviceaccount/` (the pod's Kubernetes token)

Every record carries:

- `bpf_get_current_cgroup_id()`: which cgroup (and so which container) did this.
- `bpf_get_current_pid_tgid()`: process id.
- `bpf_get_current_comm()`: short command name.
- `bpf_ktime_get_ns()`: time in the kernel clock.

### 2.2 runtime-sentinel (user side, Go)

Runs as 1 pod on every node (a DaemonSet). Its jobs:

1. **Load** the eBPF programs into the kernel and attach them to their hooks. Uses `cilium/ebpf`. The C code is compiled and turned into Go code by `bpf2go`.
2. **Read** records from the ring buffer in a loop.
3. **Enrich** each record with Kubernetes information (see section 4).
4. **Batch and send** events to Kafka topic `security.events`. Uses a Go Kafka client (for example `franz-go`).
5. **Report its own health** on `/metrics`: events per type, ring buffer drops, Kafka send errors, enrichment misses.

### 2.3 detection-service (Python)

A normal Python worker, like `search-indexer` in Phase 1. Its jobs:

1. Consume `security.events` (consumer group `detection-service`).
2. Check each event against the rules in `rules.yaml`.
3. Write **every** event to OpenSearch (with a `matched_rules` field), in bulk.
4. For each rule match, send an alert to Alertmanager (`POST /api/v2/alerts`).
5. Expose `/metrics`: events processed, alerts sent per rule, OpenSearch write errors.

It follows the [conventions](../common/07-conventions.md): timeouts and retry limits on every network call, structured logs, idempotent writes (the OpenSearch document id is the `event_id`, so a repeated event overwrites itself instead of making a copy).

## 3. Event format

The agent sends this JSON to Kafka. It follows the same idea as the OrderFlow event envelope: an id, a type, a time, and a payload.

```json
{
  "event_id": "uuid",
  "event_type": "process_exec",
  "occurred_at": "2026-11-18T10:00:00.123Z",
  "node": "orderflow-worker",
  "process": {
    "pid": 4321,
    "ppid": 4300,
    "comm": "sh",
    "path": "/bin/sh"
  },
  "k8s": {
    "namespace": "dev",
    "pod": "order-service-7c9d8-abcde",
    "container": "order-service",
    "labels": { "app.kubernetes.io/name": "order-service" }
  },
  "payload": { }
}
```

`event_type` values and their `payload`:

| event_type | payload fields |
|---|---|
| `process_exec` | `path`, `args` (if captured) |
| `file_open` | `path`, `flags` |
| `tcp_connect` | `src_ip`, `src_port`, `dst_ip`, `dst_port`, `family` (`ipv4` or `ipv6`) |

If enrichment fails (for example the pod was just deleted), `k8s` is `null` and the event is still sent. Missing context is better than a missing event.

**Kafka key:** the pod name (or the node name when `k8s` is `null`). This keeps events from the same pod in order inside 1 partition.

## 4. From a kernel event to a pod name

The kernel does not know what a "pod" is. It only knows processes and cgroups. So the agent builds a lookup table:

```
cgroup id (from the eBPF record)
   |  the agent walks /sys/fs/cgroup; each cgroup folder's inode number is its cgroup id,
   |  and the folder name contains the container id
   v
container id
   |  the agent watches pods on its own node through the Kubernetes API
   |  (field selector spec.nodeName=<this node>) and reads
   |  status.containerStatuses[].containerID
   v
pod name, namespace, container name, labels
```

Details:

- The node name comes from the Downward API (an env var `NODE_NAME` set from `spec.nodeName`).
- The agent keeps the table in memory and updates it when pods start or stop (Kubernetes watch). It does not call the API for every event.
- This needs cgroup v2. Check it in [M0](implementation-plan.md#m0-environment-check-and-toolchain).

## 5. Rules

Rules live in `services/detection-service/rules.yaml`. They are data, not code, so you can add a rule without changing Python.

```yaml
rules:
  - id: shell-in-web-container
    description: A shell started inside a web-facing container
    severity: high
    when:
      event_type: process_exec
      process.comm_in: [sh, bash, dash, ash]
      k8s.labels.app.kubernetes.io/component: api

  - id: unexpected-outbound-connection
    description: Outbound TCP connection to an IP that is not on the allowlist
    severity: high
    when:
      event_type: tcp_connect
      k8s.namespace: dev
      payload.dst_ip_not_in: allowlist.cluster_and_services

  - id: sensitive-file-read
    description: A sensitive file was opened inside a container
    severity: medium
    when:
      event_type: file_open
      k8s.namespace_not_in: [kube-system]

  - id: unexpected-binary
    description: A package manager or a suspicious tool started in a production pod
    severity: high
    when:
      event_type: process_exec
      k8s.namespace: dev
      process.comm_in: [apt, apt-get, apk, yum, pip, xmrig, nc, ncat]

allowlists:
  cluster_and_services:
    - 10.0.0.0/8      # cluster pod and service ranges in kind; check your real ranges
    - 172.16.0.0/12
    - 192.168.0.0/16
```

Notes:

- Each rule has an `id`, a `severity` and a `description`. These become Alertmanager labels and annotations.
- The condition syntax above is a sketch. Keep the matcher small: equals, "in list", "not in list", and "IP in CIDR range". Do not build a full query language.
- Every rule gets at least 1 test that matches and 1 test that must not match.
- The label `app.kubernetes.io/component: api` must be set on HTTP services by the Phase 2 Helm chart. If your chart uses a different label, change the rule, not the chart.

## 6. Storage and alerts

### OpenSearch

- 1 index per day: `security-events-YYYY.MM.DD`.
- An **index template** for `security-events-*` sets the field types (for example `dst_ip` as `ip`, `occurred_at` as `date`, `k8s.labels` as `flattened` or `object`).
- An **ISM policy** (Index State Management) deletes each index when it is 7 days old. Because the index name already changes every day, you do not need a rollover step; the policy only needs a "delete after 7 days" rule. (The other way is 1 write alias with rollover every day. That is useful when indices also need a size limit. Read about both in the OpenSearch ISM docs and record your choice in `PLAN.md`.)

### Alertmanager

detection-service sends alerts with this shape:

```json
[{
  "labels": {
    "alertname": "SecurityRuleMatched",
    "rule_id": "unexpected-outbound-connection",
    "severity": "high",
    "namespace": "dev",
    "pod": "order-service-7c9d8-abcde"
  },
  "annotations": {
    "summary": "Outbound TCP connection to an IP that is not on the allowlist",
    "event_id": "uuid",
    "dst": "203.0.113.10:80"
  }
}]
```

Alertmanager groups and routes these like the Phase 2 alerts. The Grafana dashboard shows them next to the event counts.

### Grafana dashboard

| Panel | Data source |
|---|---|
| Events per second by type and node | Prometheus (`runtime-sentinel` metrics) |
| Ring buffer drops and Kafka errors | Prometheus |
| Alerts per rule | Prometheus (`detection-service` metrics) |
| Latest events table (pod, type, path or destination) | OpenSearch data source |
| Active alerts | Alertmanager data source |

## 7. Deployment

`runtime-sentinel` is a **DaemonSet**: Kubernetes runs exactly 1 copy on every node.

It needs special access to the node:

| Need | Why |
|---|---|
| `CAP_BPF` | Load eBPF programs and create maps |
| `CAP_PERFMON` | Attach to tracepoints and read kernel data |
| `CAP_SYS_RESOURCE` | Raise the memory lock limit. Only needed on older kernels; newer kernels count eBPF memory differently. Test without it first. |
| `hostPID: true` | See the real process ids of the node, not only the pod's own |
| Mount `/sys/fs/cgroup` (read only) | Build the cgroup id to container id table |
| Mount `/sys/kernel/btf` (read only) | Read BTF type data for CO-RE |

**Trade-off:** The simple way is `privileged: true`. It always works but gives the pod full control of the node. The better way is to list only the capabilities above. Start with `privileged: true` to get it working, then remove it and add capabilities one by one until it works again. Write down the final list and what failed without each one. That list is a good interview answer.

**RBAC:** a ServiceAccount with a ClusterRole that can only `get`, `list` and `watch` `pods`. Nothing else. The agent never writes to the Kubernetes API.

`detection-service` is a normal Deployment with no special access.

## 8. Measuring overhead

A security tool that slows the system too much will be turned off. So you measure its cost.

Method:

1. Use the same k6 script from Phase 2, the same duration, the same number of virtual users.
2. Run it 3 times with the agent **off** (DaemonSet deleted).
3. Run it 3 times with the agent **on**.
4. For each run record: k6 p99 latency for `POST /api/orders`, node CPU, node memory, and the agent pod's own CPU and memory (from Prometheus).
5. Also record events per second and ring buffer drops during the "on" runs.
6. Put the numbers in a table in `security/runtime-sentinel/README.md`. Use the average of the 3 runs and show the spread.

Only report numbers you measured. If the runs vary a lot, say so.

## 9. Optional: AI incident summary

**Optional and not part of the done checklist.**

After an alert, a small job collects the related events (same pod, 5 minutes before and after) and asks an LLM to write a short, plain summary.

- A paid LLM API costs money, so it needs a written budget before you use it (spend rule).
- A local model through Ollama is free and keeps the data on your machine. Use this by default.
- The summary is a helper only. The alert and the raw events stay the source of truth, and the summary must link the event ids it used.

## 10. Decisions

| Decision | Why | What we gave up |
|---|---|---|
| Tracepoints instead of kprobes where possible | Tracepoints are a stable kernel interface, so they keep working across kernel versions. kprobes attach to internal kernel functions that can be renamed or changed. | Fewer hook points. Some details are only reachable with kprobes or fentry. |
| `sock/inet_sock_set_state` for TCP connects, not a kprobe on `tcp_v4_connect` | Stable tracepoint, covers IPv4 and IPv6 in 1 place, and the addresses are already filled in. With `tcp_v4_connect` you need an entry and an exit probe to read the destination, and a second probe for IPv6. | Only TCP. UDP (for example DNS) is not covered. |
| Filter file opens in the kernel, send exec events unfiltered | `openat` happens many thousands of times per second. Sending all of them would flood the ring buffer, Kafka and OpenSearch. Exec events are fewer and all of them matter. | Kernel filter list is fixed at load time and must be short. A program could also use `open` or `openat2`, which this hook does not see. Write that gap down. |
| Send events through Kafka, not straight to OpenSearch | Kafka absorbs spikes, keeps events if detection-service is down, and lets you add more consumers later. Same pattern as Phase 1. | 1 more hop and a little more delay |
| detection-service in Python | Matches the project rule (Python for backend services), rules are easy to read and test, and the volume after kernel filtering is moderate | Lower throughput than Go. If it cannot keep up, you will see Kafka consumer lag; scale it with more consumers first. |
| Rules in YAML, not code | Add or change a rule without a code change | Limited matching power on purpose |
| Start `privileged`, then reduce to capabilities | Get it working first, then learn exactly what each capability does | Extra step |

## 11. Known gaps (write these down honestly)

- `open` and `openat2` system calls are not traced, only `openat`.
- UDP traffic is not traced.
- Short-lived processes may be gone before enrichment; their event has a container id but maybe no pod.
- If the ring buffer is full, events are dropped. The drop counter in `/metrics` shows this.
- An attacker with root on the node can stop the agent. This tool detects; it does not prevent.
