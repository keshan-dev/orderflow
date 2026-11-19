# Phase 4 Concepts

This doc explains every new idea in Phase 4 in simple words. For each one you get: what it is, a simple picture, and what breaks without it. Short definitions are also in the [glossary](../common/04-glossary.md).

---

## 1. Kernel space and user space

**What it is.** A Linux machine has 2 worlds:

- **Kernel space:** the core of the operating system. It controls the CPU, memory, files, network and all hardware. Code here has full power.
- **User space:** where normal programs run (Python, Go, nginx, your services). They have limited power and must ask the kernel for anything important.

**Simple picture.** The kernel is a bank vault with 1 guarded counter. Programs are customers. They cannot walk into the vault; they ask at the counter.

**Without it.** Any program could read any other program's memory or write anywhere on disk. 1 bug could crash the whole machine.

**Why it matters here.** Your eBPF programs run in kernel space. Your Go agent runs in user space. They pass data through a ring buffer (see section 6).

---

## 2. System calls

**What it is.** A system call ("syscall") is how a user program asks the kernel to do something: open a file (`openat`), start a program (`execve`), open a network connection (`connect`).

**Simple picture.** The request form at the bank counter. Every important action needs a form.

**Without it.** There is no safe way for programs to use files, network or other programs.

**Why it matters here.** Every action in every container ends as a syscall. If you watch syscalls, you see everything, even what the application never logs. This is why kernel-level security tools are hard to hide from.

---

## 3. What eBPF is, and the verifier

**What it is.** eBPF lets you run small programs **inside the kernel** without changing the kernel's source code and without loading a kernel module. You attach a program to a hook (an event), and the kernel runs it each time that event happens.

**The verifier.** Before the kernel accepts an eBPF program, the **verifier** checks it. It makes sure the program:

- always finishes (no endless loops),
- never reads memory it is not allowed to read,
- uses only allowed helper functions.

If the check fails, the program is rejected with an error message. You will see many of these messages while learning. They are normal.

**Simple picture.** A security camera you can mount on any door in the vault, but a guard checks every camera first to make sure it cannot break anything.

**Without it.** You would need a kernel module to watch these events. A bug in a kernel module can crash the whole machine. Many companies do not allow kernel modules in production.

---

## 4. Program types: tracepoints, kprobes, fentry

eBPF programs attach to different kinds of hooks.

| Type | What it attaches to | Stable across kernel versions? | Used in Phase 4 |
|---|---|---|---|
| **Tracepoint** | Fixed points that kernel developers added on purpose (for example `sched_process_exec`) | Yes, they are meant to stay | Yes, for all 3 events |
| **kprobe / kretprobe** | The start (or end) of almost any kernel function | No. Function names and arguments can change between versions | Not by default; useful to know |
| **fentry / fexit** | Like kprobes but faster and with typed arguments. Needs BTF | No, same reason as kprobes | Not by default; useful to know |

**Without the right choice.** If you use a kprobe on an internal function, your agent may break on the next kernel update. Tracepoints are safer when they give you the data you need.

---

## 5. Maps

**What it is.** A **map** is a data store shared between eBPF programs and user space. Types include hash maps, arrays, and ring buffers.

**Simple picture.** A shared whiteboard. The kernel program and the Go agent can both read and write it.

**Without it.** eBPF programs could not keep any state (for example "which paths are sensitive") and could not send anything to user space.

**Used here.** A ring buffer map for events. Optionally an array or hash map for the sensitive path list or for counters.

---

## 6. Ring buffer vs perf buffer

**What it is.** 2 ways to send events from the kernel to user space.

| | Perf buffer (older) | Ring buffer (newer) |
|---|---|---|
| Memory | 1 buffer per CPU | 1 buffer shared by all CPUs |
| Event order | Can be out of order across CPUs | Kept in order |
| Memory use | Often wastes memory (each CPU gets its own) | More efficient |
| Kernel needed | Older kernels | Linux 5.8 or newer |

**Simple picture.** A perf buffer is 1 mailbox per worker. A ring buffer is 1 shared mailbox with a fixed size that wraps around.

**Without it.** No way to move many events out of the kernel quickly.

**When it is full.** New events are **dropped**. Your agent must count drops and show them on `/metrics`. Hiding drops makes the tool look better than it is.

---

## 7. BTF and CO-RE

**What it is.**

- **BTF** (BPF Type Format): a description of all kernel data structures (what fields a struct has and where they sit). Many kernels ship it at `/sys/kernel/btf/vmlinux`.
- **CO-RE** (Compile Once, Run Everywhere): your eBPF program is compiled once. When it is loaded, the loader uses BTF to fix the field offsets for the kernel it is running on.

**Simple picture.** You write "give me the 3rd drawer from the left" as "give me the drawer labelled Passport". If the furniture changes, the label still works.

**Without it.** You would need to compile your eBPF program on every machine against that machine's exact kernel headers. Updating the kernel could break the agent.

---

## 8. vmlinux.h

**What it is.** A single C header file with **all** kernel types, generated from BTF:

```bash
bpftool btf dump file /sys/kernel/btf/vmlinux format c > vmlinux.h
```

Your eBPF C files include it instead of many kernel headers.

**Without it.** You would need the full kernel header package for your exact kernel, and many includes that often conflict.

---

## 9. cgroups and namespaces (how containers are made)

A "container" is not a special kernel object. It is a normal process with 2 kinds of limits:

- **Namespaces** change **what a process can see**: its own process ids (PID namespace), its own network (network namespace), its own file system view (mount namespace), and others.
- **cgroups** (control groups) control **what a process can use**: CPU, memory, and so on. Every container gets its own cgroup.

**Simple picture.** Namespaces are blinders on a horse (it only sees its own lane). cgroups are the fence around its field (how much grass it can eat).

**Why it matters here.** The kernel event only tells you the process id and the cgroup id. The cgroup id is the link to the container, and the container is the link to the pod. That is how the agent can say "this happened in pod `order-service-7c9d8-abcde`".

**cgroup v2.** Newer systems use cgroup version 2, where every cgroup is 1 folder in `/sys/fs/cgroup`. The folder's inode number is the cgroup id that `bpf_get_current_cgroup_id()` returns.

**Without this mapping.** An alert says "process 4321 started sh". Nobody can tell which pod, which team, or which service. The alert is almost useless.

---

## 10. Capabilities

**What it is.** Linux splits "root power" into many small permissions called **capabilities**. Examples:

- `CAP_BPF`: load eBPF programs.
- `CAP_PERFMON`: attach to tracepoints and read performance data.
- `CAP_SYS_RESOURCE`: go over some resource limits.
- `CAP_SYS_ADMIN`: a very broad one. Avoid it if you can.

**Simple picture.** Instead of giving someone the master key, you give them only the keys to the 2 rooms they need.

**Without it.** You must run the agent as fully privileged. If the agent has a bug or is attacked, the attacker gets full control of the node.

---

## 11. DaemonSet

**What it is.** A Kubernetes object that runs **exactly 1 copy of a pod on every node**. When a new node joins, it gets a copy automatically.

**Without it.** You would have to start the agent on each node by hand, and a new node would have no protection until someone remembers.

**Used here.** `runtime-sentinel` is a DaemonSet, because each node has its own kernel events and must be watched locally.

---

## 12. High volume event pipelines

**What it is.** A system that moves a large, constant stream of small events from many sources to storage and analysis.

The Phase 4 pipeline:

```
kernel -> ring buffer -> agent -> Kafka -> detection-service -> OpenSearch
```

Each step must be faster than the step before it fills up. Otherwise events pile up and are lost.

**Without a buffer like Kafka.** If OpenSearch is slow for 1 minute, the agent must either block (and the ring buffer fills and drops events) or throw events away. Kafka holds the events until the consumer catches up.

---

## 13. Backpressure and sampling

- **Backpressure:** when a slow step tells the fast step "slow down". Example: Kafka producer buffer is full, so the agent pauses sending.
- **Sampling:** keep only some events (for example 1 in 10) when there are too many.

**Without a plan.** The system fails in a random place in a random way. With a plan, you choose: "under heavy load we drop low-value events first and we count every drop".

**In Phase 4.** Filter in the kernel first (cheapest). Batch in the agent. Count every drop. Do not sample security events unless you must, and say so if you do.

---

## 14. Detection rules and false positives

- **Detection rule:** "if an event looks like X, raise an alert". Example: a shell started in a web container.
- **False positive:** an alert for something that is actually fine. Example: an engineer runs `kubectl exec` to debug.
- **False negative:** a real attack that raises no alert.

**Without care.** Too many false positives and people stop reading alerts. Too few rules and real attacks pass.

**In Phase 4.** Every rule has a test that must match and a test that must not match. When you find a false positive, write it down and adjust the rule (for example with an allowlist), do not just delete the rule.

---

## 15. Index lifecycle (ISM)

**What it is.** OpenSearch **Index State Management** (ISM) is a policy that changes or deletes indices automatically as they get older. Example: "delete any `security-events-*` index after 7 days".

**Simple picture.** A rule for the filing cabinet: shred any folder older than 7 days.

**Without it.** Security events keep growing until the disk is full and OpenSearch stops accepting writes. Then you lose new events, which is the worst time to lose them.
