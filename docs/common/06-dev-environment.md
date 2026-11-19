# Dev Environment

How to set up your Windows 11 machine for all 5 phases. Install only what the current phase needs. You do not need everything on day 1.

**Version rule:** for every tool, install the current stable version, then write the exact version in the project (lock files, Dockerfile tags, `go.mod`, `.terraform.lock.hcl`). This is called pinning. It means the project works the same way next month.

## 1. Hardware (recommendation)

OrderFlow runs many things at once: Kafka, PostgreSQL, OpenSearch, RabbitMQ, Redis, MinIO and 5 services. Later, a Kubernetes cluster runs on top.

| | Recommended | Can work |
|---|---|---|
| RAM | 32 GB | 16 GB, if you only start what you need (tips below) |
| Free disk | 100 GB on an SSD | 50 GB, if you clean Docker often |
| CPU | 8 cores or more | 4 cores, but slower |

These are guidance from experience, not hard rules. Watch your own machine's memory use and adjust.

### Tips to save RAM
- Limit WSL2's memory in `C:\Users\<you>\.wslconfig` so Windows stays usable:
  ```ini
  [wsl2]
  memory=12GB
  processors=6
  ```
  Then run `wsl --shutdown` and start WSL again.
- Give OpenSearch a small heap in Docker Compose, for example `OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m`.
- Use Docker Compose profiles so you start only the parts you are working on (for example, no OpenSearch while you build the saga).
- Run 1 Kafka broker locally, not 3.
- Stop Phase 1 Compose before you start the kind cluster in Phase 2.
- Clean up regularly: `docker system df` shows what uses space, `docker system prune` removes unused data. Read what it will delete before you confirm.

## 2. Base setup (all phases)

Do all your work **inside WSL2 (Ubuntu)**, not in Windows folders. Keep the project in the Linux file system (for example `~/code/orderflow`). File access from `/mnt/c` or `/mnt/d` is much slower, and file watching does not work well there.

| Tool | What it is for | Verify |
|---|---|---|
| **WSL2 + Ubuntu** | A real Linux system inside Windows. All tools run here. Install with `wsl --install -d Ubuntu` in PowerShell. | `wsl -l -v` (in PowerShell) shows Ubuntu with VERSION 2 |
| **Docker** | Runs containers. 2 options below. | `docker version` and `docker run --rm hello-world` |
| **Docker Compose** | Starts the Phase 1 system from 1 file | `docker compose version` |
| **git** | Version control. Install and configure inside Ubuntu. | `git --version` |
| **VS Code + WSL extension** | Edit code inside WSL from Windows | Run `code .` inside a WSL folder; the bottom left corner shows "WSL: Ubuntu" |
| **jq** | Reads and filters JSON on the command line. Useful for API and Kafka output. | `jq --version` |

### Docker: choose 1 option
- **Docker Desktop with the WSL2 backend.** Easiest. In settings, turn on WSL integration for your Ubuntu distro. Docker Desktop is a paid product for some companies, so check Docker's current subscription terms before you use it for work.
- **Docker Engine inside WSL2 Ubuntu.** Free and open source. Install it with the official Docker docs for Ubuntu. Slightly more setup, and no Windows GUI.

### OpenSearch needs 1 kernel setting
OpenSearch in Docker needs a larger memory map limit. Inside WSL:

```bash
sudo sysctl -w vm.max_map_count=262144
```

This resets when WSL restarts. The Phase 1 docs explain how to make it permanent.

## 3. Phase 1: Order platform

| Tool | What it is for | Verify |
|---|---|---|
| **uv** | Installs Python, manages dependencies and lock files | `uv --version` |
| **Python** (through uv) | order-service, inventory-service, workers | `uv python list` shows an installed version |
| **Go** | payment-service | `go version` |
| **ruff** (through uv) | Python lint and format | `uv run ruff --version` inside a service |
| **golangci-lint** | Go lint | `golangci-lint --version` |
| **k6** | Load tests in `loadtest/` | `k6 version` |
| **psql** (optional) | Look inside PostgreSQL by hand | `psql --version` |

## 4. Phase 2: GitOps and observability

| Tool | What it is for | Verify |
|---|---|---|
| **kubectl** | Talk to any Kubernetes cluster | `kubectl version --client` |
| **kind** | Run a Kubernetes cluster in Docker | `kind version`, then `kind create cluster` and `kubectl get nodes` |
| **helm** | Install charts and build the OrderFlow chart | `helm version` |
| **argocd CLI** | Log in to Argo CD, sync and check apps from the terminal | `argocd version --client` |
| **kubectl argo rollouts plugin** | Watch and control canary releases | `kubectl argo rollouts version` |
| **trivy** | Scan images locally before CI does | `trivy --version` |
| **cosign** | Sign and verify images | `cosign version` |
| **GitHub account + gh CLI** | Repository, Actions, container registry | `gh --version` and `gh auth status` |

## 5. Phase 3: Kubernetes operator

| Tool | What it is for | Verify |
|---|---|---|
| **Go** (already installed) | The operator code | `go version` |
| **kubebuilder** | Creates the operator project, CRDs and webhooks | `kubebuilder version` |
| **make** | Kubebuilder projects use a Makefile | `make --version` |
| **cert-manager** (in the cluster) | Webhook certificates | `kubectl get pods -n cert-manager` shows running pods |

`envtest` binaries are downloaded by the Kubebuilder Makefile when you run `make test`.

## 6. Phase 4: eBPF security agent

| Tool | What it is for | Verify |
|---|---|---|
| **clang** and **llvm** | Compile the C eBPF programs | `clang --version` and `llvm-strip --version` |
| **libbpf-dev** | C headers for eBPF programs | `dpkg -s libbpf-dev` shows "Status: install ok installed" |
| **bpftool** | Inspect loaded programs and create `vmlinux.h` | `bpftool version` |
| **Go** with **cilium/ebpf** | Load programs and read events (added as a Go module, not installed globally) | `go list -m github.com/cilium/ebpf` inside the agent's folder |

Install clang, llvm and libbpf-dev with `sudo apt install clang llvm libbpf-dev`.

On a normal Ubuntu machine, `bpftool` comes with the `linux-tools` packages for your kernel. On WSL2 those packages usually do not match the WSL kernel, so you may need to build bpftool from its official repository (`libbpf/bpftool` on GitHub).

### Important: the kernel
- eBPF programs run in the **kernel of the host machine**.
- kind nodes are Docker containers. Containers do not have their own kernel. They share the host's kernel. So when your agent runs in kind, it runs in the WSL2 kernel (or the Docker Desktop VM kernel, which is the same WSL2 kernel).
- Our eBPF programs use CO-RE, which needs **BTF**. Check it inside WSL:

  ```bash
  uname -r
  ls /sys/kernel/btf/vmlinux
  ```

  If the file exists, BTF is available. Then try a first small program from the Phase 4 docs.

- **If BTF is missing, or the tracepoints you need are not available**, use an **Ubuntu VM** instead. Windows 11 Pro includes Hyper-V, which can create an Ubuntu VM. Run Docker, kind and the agent inside that VM. A normal Ubuntu server kernel has BTF turned on.

## 7. Phase 5: AWS with Terraform

| Tool | What it is for | Verify |
|---|---|---|
| **terraform** | Build AWS resources from code | `terraform version` |
| **aws CLI** | Log in to AWS, check resources | `aws --version`, then `aws sts get-caller-identity` (after login) |
| **Node.js** and **npm** | Needed for AWS CDK | `node --version` and `npm --version` |
| **AWS CDK** | The 1 module rebuilt in CDK (use it through `npx`) | `npx cdk --version` |
| **LocalStack** | Test AWS services locally first | `docker ps` shows the LocalStack container running |
| **tflint** (optional) | Finds mistakes in Terraform code | `tflint --version` |

Do not create AWS credentials or log in to AWS until you have written the Phase 5 budget. See [cost and safety](08-cost-and-safety.md). Never save AWS keys in the repository. Use `aws configure sso` or short-lived credentials where possible.

## 8. Check everything at once

Paste this inside WSL to see what is installed. Missing tools show "not found".

```bash
for t in docker git jq uv go k6 kubectl kind helm argocd trivy cosign gh kubebuilder clang bpftool terraform aws node; do
  printf "%-12s " "$t"; command -v "$t" >/dev/null && echo "ok" || echo "not found"
done
```
