"""Run every consistency check and exit with 1 if any fails.

  docker compose -f deploy/compose/docker-compose.yml run --rm reconcile

Run it when the system is quiet (no load running, timeouts passed), otherwise orders that
are simply still in progress look stuck.
"""

import json
import logging
import sys
from datetime import timedelta

from orderflow_common.connections import make_engine, make_redis
from orderflow_common.logging import configure_logging
from orderflow_common.settings import env_int, env_str
from reconcile.checks import run_all
from reconcile.load import load_snapshot

log = logging.getLogger("reconcile")


def main() -> int:
    configure_logging("reconcile")
    engines = [
        make_engine(env_str(name), pool_size=1)
        for name in ("ORDERS_DATABASE_URL", "INVENTORY_DATABASE_URL", "PAYMENTS_DATABASE_URL")
    ]
    cache = make_redis(env_str("REDIS_URL"))
    snapshot = load_snapshot(
        *engines,
        cache,
        env_str("S3_BUCKET"),
        env_str("S3_ENDPOINT_URL", "") or None,
    )
    results = run_all(snapshot, timedelta(seconds=env_int("STUCK_AFTER_SECONDS", 300)))

    totals = {
        "orders": len(snapshot.orders),
        "confirmed": sum(o.status == "CONFIRMED" for o in snapshot.orders),
        "cancelled": sum(o.status == "CANCELLED" for o in snapshot.orders),
        "payments": len(snapshot.payments),
    }
    print(json.dumps({"totals": totals}))
    for result in results:
        print(json.dumps(result.summary()))
    failed = [r.name for r in results if not r.ok]
    print(json.dumps({"passed": len(results) - len(failed), "failed": failed}))
    for engine in engines:
        engine.dispose()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
