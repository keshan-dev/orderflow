# OrderFlow

An event-driven order platform built to learn a production stack end to end: Python and Go services with PostgreSQL, Redis, Kafka, RabbitMQ, OpenSearch and S3.

- Plan and decision log: [PLAN.md](PLAN.md)
- Documentation: [docs/README.md](docs/README.md)

## Run the local stack

You need Docker Desktop. The stack is sized for about 4 GB of Docker memory.

```bash
cp deploy/compose/.env.example deploy/compose/.env    # then change the passwords
alias dc='docker compose -f deploy/compose/docker-compose.yml'
dc up -d                     # core stack
dc --profile ui up -d        # optional: also start Kafka UI and OpenSearch Dashboards
dc ps                        # every long-running container should be "healthy"
```

`kafka-init` and `s3-init` are 1-shot containers. They create the Kafka topics and the invoice bucket, then exit with code 0.

## Local addresses

| Address | What |
|---|---|
| `127.0.0.1:15432` | PostgreSQL (`orders_db`, `inventory_db`, `payments_db`; containers use `postgres:5432`) |
| `127.0.0.1:6379` | Redis |
| `127.0.0.1:29092` | Kafka (containers use `kafka:19092`) |
| http://127.0.0.1:8083 | Kafka Connect (Debezium) REST API |
| http://127.0.0.1:8085 | Kafka UI (`ui` profile) |
| http://127.0.0.1:15672 | RabbitMQ management |
| http://127.0.0.1:9200 | OpenSearch (no login, local only) |
| http://127.0.0.1:5601 | OpenSearch Dashboards (`ui` profile) |
| http://127.0.0.1:7333 | S3 API (SeaweedFS) |
| http://127.0.0.1:7888/buckets/ | S3 file browser |
| http://127.0.0.1:8025 | Mailpit inbox (fake email) |

Use `127.0.0.1` rather than `localhost` from your machine: on Windows `localhost` can resolve to `::1`, where other programs (for example a WSL port relay) may answer instead of Docker.

Some host ports differ from the usual defaults. Kafka (29092) and S3 (7333) move because Windows reserves the ranges 8295 to 8894 and 8995 to 9194 on the dev machine. PostgreSQL (15432) moves because a native PostgreSQL service already uses 5432. Check yours with `netsh int ipv4 show excludedportrange protocol=tcp`.

## Reset everything

```bash
dc down -v    # stops the stack and deletes all data volumes
dc up -d
```
