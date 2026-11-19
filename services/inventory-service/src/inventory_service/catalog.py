"""Product list, read from Postgres and cached in Redis for a short time."""

import json
import logging
from typing import Any

import redis
from sqlalchemy import Engine, select

from inventory_service.schema import products, stock

log = logging.getLogger(__name__)

CACHE_KEY = "cache:products"


def load_products(engine: Engine) -> list[dict[str, Any]]:
    query = (
        select(
            products.c.id,
            products.c.sku,
            products.c.name,
            products.c.price_cents,
            stock.c.available,
        )
        .join(stock, stock.c.product_id == products.c.id)
        .order_by(products.c.sku)
    )
    with engine.connect() as conn:
        return [{**row._asdict(), "id": str(row.id)} for row in conn.execute(query)]


def list_products(engine: Engine, cache: redis.Redis, ttl_seconds: int) -> list[dict[str, Any]]:
    """Cached product list. `available` can be up to ttl_seconds old.

    Reservations never use this cache; they use live stock.
    """
    try:
        cached = cache.get(CACHE_KEY)
        if cached is not None:
            return json.loads(cached)
    except redis.RedisError:
        log.warning("product cache read failed, reading from postgres", exc_info=True)

    items = load_products(engine)
    try:
        cache.set(CACHE_KEY, json.dumps(items), ex=ttl_seconds)
    except redis.RedisError:
        log.warning("product cache write failed", exc_info=True)
    return items
