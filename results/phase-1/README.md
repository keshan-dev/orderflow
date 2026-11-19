# Phase 1 measured results

Only numbers measured on the dev machine are recorded here, each with the date and setup.

Machine: Windows 11, 16 logical CPUs, 7.7 GB RAM, Docker Desktop with about 3.9 GB for containers.

## M6: search during a zero downtime reindex (2026-11-19)

- Setup: 1 order-service container, OpenSearch 3.9.0 single node, 54 orders indexed.
- Load: k6, 5 virtual users, 45 seconds, `loadtest/phase1-search.js` against `http://localhost:8001`.
- Action: after about 12 seconds, `reindex.sh orders-v3 orders-v4` moved the `orders` alias.
- Result: 7032 requests, 156 requests per second, **0 failed**, p95 76.9 ms, max 843.8 ms.
- Raw k6 summary: [2026-11-19-m6-search-during-reindex.json](2026-11-19-m6-search-during-reindex.json)
