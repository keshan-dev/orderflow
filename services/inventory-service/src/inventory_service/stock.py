"""Stock in 2 places: Redis is the fast gate, Postgres is the source of truth.

Rule that keeps them safe: Redis is decreased BEFORE Postgres and increased AFTER Postgres.
If anything fails in between, Redis shows less stock than Postgres, never more, so the
system can refuse a sale by mistake but can never oversell. A resync fixes the difference.
"""

import json
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum
from importlib import resources

import redis
from sqlalchemy import Engine, select

from inventory_service.schema import stock

log = logging.getLogger(__name__)


class InvalidItemsError(ValueError):
    """The order items are empty or have a bad product id or quantity."""


@dataclass(frozen=True, order=True)
class Item:
    product_id: uuid.UUID
    quantity: int


def normalize_items(raw: Iterable[dict]) -> list[Item]:
    """Validate items, merge repeated products, and sort them so keys are always in 1 order."""
    totals: dict[uuid.UUID, int] = {}
    for entry in raw:
        try:
            product_id = uuid.UUID(str(entry["product_id"]))
            quantity = int(entry["quantity"])
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidItemsError(f"bad item: {entry!r}") from exc
        if quantity <= 0:
            raise InvalidItemsError(f"quantity must be more than 0: {entry!r}")
        totals[product_id] = totals.get(product_id, 0) + quantity
    if not totals:
        raise InvalidItemsError("an order needs at least 1 item")
    return sorted(Item(pid, qty) for pid, qty in totals.items())


def items_to_dicts(items: list[Item]) -> list[dict]:
    return [{"product_id": str(i.product_id), "quantity": i.quantity} for i in items]


class RedisReserve(IntEnum):
    SHORT = 0
    RESERVED = 1
    ALREADY_HELD = 2


def _lua(name: str) -> str:
    return resources.files("inventory_service").joinpath("lua", name).read_text(encoding="utf-8")


class RedisStock:
    """The Lua scripts that change stock:{product_id} and hold:{order_id} keys atomically."""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client
        self._reserve = client.register_script(_lua("reserve.lua"))
        self._release = client.register_script(_lua("release.lua"))

    def try_reserve(self, order_id: uuid.UUID, items: list[Item], ttl_seconds: int) -> RedisReserve:
        keys = [stock_key(i.product_id) for i in items] + [hold_key(order_id)]
        args = [i.quantity for i in items] + [json.dumps(items_to_dicts(items)), ttl_seconds]
        return RedisReserve(int(self._reserve(keys=keys, args=args)))

    def forget_hold(self, order_id: uuid.UUID) -> None:
        """Remove the hold key of a sold order. The stock itself stays taken."""
        try:
            self._client.delete(hold_key(order_id))
        except redis.RedisError:
            # Not harmful: the key expires on its own and nothing reads it after the sale.
            log.warning("could not delete hold key of a sold order", exc_info=True)

    def give_back(self, order_id: uuid.UUID, items: list[Item]) -> None:
        keys = [stock_key(i.product_id) for i in items] + [hold_key(order_id)]
        self._release(keys=keys, args=[i.quantity for i in items])


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
