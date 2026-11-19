"""Stock in 2 places: Redis is the fast gate, Postgres is the source of truth.

Rule that keeps them safe: Redis is decreased BEFORE Postgres and increased AFTER Postgres.
If anything fails in between, Redis shows less stock than Postgres, never more, so the
system can refuse a sale by mistake but can never oversell. A resync fixes the difference.
"""

import uuid

import redis
from sqlalchemy import Engine, select

from inventory_service.schema import stock


def stock_key(product_id: uuid.UUID | str) -> str:
    return f"stock:{product_id}"


def hold_key(order_id: uuid.UUID | str) -> str:
    return f"hold:{order_id}"


def load_stock_into_redis(engine: Engine, cache: redis.Redis, overwrite: bool = False) -> int:
    """Copy available stock from Postgres into stock:{product_id} keys.

    On startup overwrite=False: keys that already exist are kept, because Redis may already
    hold reservations made since the last start. overwrite=True is a full resync; run it
    only when no reservations are in progress.
    Returns how many keys were written.
    """
    with engine.connect() as conn:
        rows = conn.execute(select(stock.c.product_id, stock.c.available)).all()
    pipe = cache.pipeline(transaction=False)
    for product_id, available in rows:
        pipe.set(stock_key(product_id), available, nx=not overwrite)
    return sum(1 for written in pipe.execute() if written)
