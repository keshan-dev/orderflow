# Phase 1 measured results

Only numbers measured on the dev machine are recorded here, each with the date and setup.

Machine: Windows 11, 16 logical CPUs, 7.7 GB RAM, Docker Desktop with about 3.9 GB for containers.

## M6: search during a zero downtime reindex (2026-11-19)

- Setup: 1 order-service container, OpenSearch 3.9.0 single node, 54 orders indexed.
- Load: k6, 5 virtual users, 45 seconds, `loadtest/phase1-search.js` against `http://localhost:8001`.
- Action: after about 12 seconds, `reindex.sh orders-v3 orders-v4` moved the `orders` alias.
- Result: 7032 requests, 156 requests per second, **0 failed**, p95 76.9 ms, max 843.8 ms.
- Raw k6 summary: [2026-11-19-m6-search-during-reindex.json](2026-11-19-m6-search-during-reindex.json)

## M7: failover through nginx (2026-11-19)

- Setup: nginx in front of order-service-1 and order-service-2.
- Load: k6, 4 virtual users, 30 seconds, `GET /api/orders/search?q=lamp` through `http://localhost:8080`.
- Action: `docker kill` order-service-1 after 8 seconds, `docker start` it 12 seconds later.
- Result: 6175 requests, **0 failed**, p95 32.6 ms, max 2005.7 ms (the 2 second connect timeout to the dead container, then a retry on the other copy).

## M7: shared rate limit (2026-11-19)

- Setup: limit of a burst of 20, then 10 per second, per client, in Redis.
- Load: k6, 20 virtual users, 100 `POST /api/orders` with the same `X-Client-Id`, through nginx.
- Result: about 22 accepted (202) and 78 limited (429): 39 by order-service-1 and 39 by order-service-2.

## M8: load and chaos verification, round 1 FAILED (2026-11-19)

- Setup: all services in Compose, payment-service declining 20% of charges, `bash chaos/phase1-verify.sh 3 180`.
- Load: k6, 8 virtual users, 180 seconds, `loadtest/phase1-orders.js` through nginx, while `chaos/phase1-kill-random.sh` paused or killed random services 9 times.
- k6: 4093 orders accepted, 99.58% of checks passed (threshold 98%), 0 repeated keys created a second order, 0.40% failed requests.
- Reconcile: 6 of 8 checks passed. Failed: "no order is stuck" (3892 orders still in progress after 15 minutes) and "reservations match orders" (136 paid orders with released stock).
- Causes: 2 open bugs, described in the decision log of `PLAN.md`. Rounds 2 and 3 did not run.
- Raw files: [k6 summary](2026-11-19-m8-round-1-k6.txt), [k6 JSON](2026-11-19-m8-round-1-k6.json), [chaos log](2026-11-19-m8-round-1-chaos.log), [reconcile output](2026-11-19-m8-round-1-reconcile.txt)
