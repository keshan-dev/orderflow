# Conventions

These are the rules for code and docs in OrderFlow.

## Code

- **Python** for backend services and workers. **Go** for payment-service, the operator and the eBPF agent. **C** only for the eBPF kernel programs.
- Small functions with 1 clear job each. Readable names over clever code.
- **Every network call has a timeout and a retry limit.** No call waits forever, and no call retries forever.
  - Python: `httpx` with `timeout=` set, retries with `tenacity` (`stop_after_attempt`, `wait_exponential`).
  - Go: `http.Client{Timeout: ...}` and a context with a deadline.
- **Log what was tried, what came back, and what was skipped.** Use structured JSON logs with `service`, `order_id`, `event_id` and `trace_id` fields.
- **No secrets in the repository.** Passwords, keys and tokens come from environment variables. Commit a `.env.example` with fake values, never a real `.env`.
- Pin versions. Docker images use exact tags (`postgres:17.2`, not `postgres:latest`). Python dependencies are locked.
- Every service has `/healthz` (am I alive?) and `/readyz` (can I serve traffic right now?).

## Python tools

| Need | Tool |
|---|---|
| Dependency management | `uv` with a lock file |
| Web framework | FastAPI |
| Database | SQLAlchemy 2.x + Alembic migrations |
| Validation | Pydantic v2 |
| HTTP client | `httpx` |
| Retries | `tenacity` |
| Tests | `pytest`, plus Testcontainers for real Postgres, Redis and Kafka in tests |
| Lint and format | `ruff` |

## Go tools

| Need | Tool |
|---|---|
| Build | Go modules, current stable Go |
| Lint | `golangci-lint` |
| Tests | `go test`, `envtest` for the operator |
| Kafka client | `franz-go` (runtime-sentinel) |
| eBPF loader | `cilium/ebpf` with `bpf2go` |

## Naming

| Thing | Style | Example |
|---|---|---|
| Services | kebab-case | `order-service` |
| Kafka topics | `domain.events` | `orders.events` |
| Event types | PascalCase, past tense | `StockReserved` |
| RabbitMQ queues | `domain.action` | `invoices.generate` |
| Database tables | snake_case, plural | `order_items` |
| Redis keys | `prefix:id` | `hold:{order_id}` |
| Environment variables | UPPER_SNAKE_CASE, generic names (see [architecture](02-architecture.md)) | `DATABASE_URL` |

## Git

- Small commits, 1 change per commit, using **Conventional Commits** (`type(scope): summary`). The types, scopes and rules are in [the Phase 1 commit plan](../phase-1-order-platform/commit-plan.md#1-commit-message-rules-conventional-commits).
- **No AI attribution anywhere**: no `Co-Authored-By` lines for AI tools, no "Generated with" lines, no tool names or badges in commits, pull requests, code comments or docs.
- Work on a branch, open a pull request, merge to `main` when CI passes.
- `main` is what Argo CD deploys (Phase 2 onwards), so keep it working.

## Decisions

Every decision made in a chat, a call or while coding goes into the decision log in [`PLAN.md`](../../PLAN.md) on the same day: date, who, what, why. If it is not in `PLAN.md`, it is not decided.

## Docs

- Simple words. Explain a term the first time you use it, or link to the [glossary](04-glossary.md).
- No em dashes or en dashes. Use numerals (3, not three).
- Update the docs in the same pull request as the code change.
