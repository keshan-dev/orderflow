"""Reserve stock for orders: Redis first as the fast gate, then Postgres as the source of truth.

Callers can pass 2 hooks that run inside the same Postgres transaction:
- guard(conn) -> bool: return False to skip (for example, this event was already handled).
- on_result(conn, result): write follow-up rows (for example an outbox event).
So the stock change, the duplicate check and the event are saved together or not at all.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum

from sqlalchemy import Connection, Engine, func, insert, select, update

from inventory_service.schema import products, reservations, stock
from inventory_service.stock import Item, RedisReserve, RedisStock

log = logging.getLogger(__name__)


class Outcome(StrEnum):
    RESERVED = "RESERVED"
    ALREADY_RESERVED = "ALREADY_RESERVED"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True)
class Line:
    product_id: uuid.UUID
    name: str
    quantity: int
    unit_price_cents: int

    def as_dict(self) -> dict:
        return {
            "product_id": str(self.product_id),
            "name": self.name,
            "quantity": self.quantity,
            "unit_price_cents": self.unit_price_cents,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Line":
        return cls(
            product_id=uuid.UUID(data["product_id"]),
            name=data["name"],
            quantity=int(data["quantity"]),
            unit_price_cents=int(data["unit_price_cents"]),
        )


@dataclass(frozen=True)
class ReserveResult:
    order_id: uuid.UUID
    outcome: Outcome
    lines: list[Line] = field(default_factory=list)
    reason: str | None = None


class ReleaseOutcome(StrEnum):
    RELEASED = "RELEASED"
    ALREADY_RELEASED = "ALREADY_RELEASED"
    COMMITTED = "COMMITTED"
    NOT_FOUND = "NOT_FOUND"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True)
class ReleaseResult:
    order_id: uuid.UUID
    outcome: ReleaseOutcome
    lines: list[Line] = field(default_factory=list)
    reason: str = "requested"


Guard = Callable[[Connection], bool]
OnReserve = Callable[[Connection, ReserveResult], None]
OnRelease = Callable[[Connection, ReleaseResult], None]


class Reservations:
    def __init__(self, engine: Engine, gate: RedisStock, hold_ttl_seconds: int) -> None:
        self._engine = engine
        self._gate = gate
        self._hold_ttl_seconds = hold_ttl_seconds

    @property
    def engine(self) -> Engine:
        return self._engine

    def reserve(
        self,
        order_id: uuid.UUID,
        items: list[Item],
        *,
        guard: Guard | None = None,
        on_result: OnReserve | None = None,
    ) -> ReserveResult:
        taken_in_redis = False
        try:
            with self._engine.begin() as conn:
                if guard is not None and not guard(conn):
                    return ReserveResult(order_id, Outcome.DUPLICATE)
                result = self._existing(conn, order_id)
                if result is None:
                    result, taken_in_redis = self._reserve_new(conn, order_id, items)
                if on_result is not None:
                    on_result(conn, result)
            return result
        except Exception:
            # Postgres did not commit. Only undo Redis if this call took the stock there.
            if taken_in_redis:
                self._give_back_safely(order_id, items)
            raise

    def release(
        self,
        order_id: uuid.UUID,
        *,
        guard: Guard | None = None,
        on_result: OnRelease | None = None,
    ) -> ReleaseResult:
        """Give an order's stock back. Safe to call many times: only HELD stock is returned."""
        with self._engine.begin() as conn:
            if guard is not None and not guard(conn):
                return ReleaseResult(order_id, ReleaseOutcome.DUPLICATE)
            row = conn.execute(
                select(reservations.c.status, reservations.c["items"])
                .where(reservations.c.order_id == order_id)
                .with_for_update()
            ).first()
            if row is None:
                result = ReleaseResult(order_id, ReleaseOutcome.NOT_FOUND)
            else:
                lines = [Line.from_dict(d) for d in row.items]
                if row.status == "HELD":
                    self._return_to_postgres(conn, order_id, lines)
                    result = ReleaseResult(order_id, ReleaseOutcome.RELEASED, lines)
                elif row.status == "RELEASED":
                    result = ReleaseResult(order_id, ReleaseOutcome.ALREADY_RELEASED, lines)
                else:
                    result = ReleaseResult(order_id, ReleaseOutcome.COMMITTED, lines)
            if on_result is not None:
                on_result(conn, result)
        # Redis is increased only after Postgres committed (see the module docstring in stock.py).
        if result.outcome is ReleaseOutcome.RELEASED:
            self._give_back_safely(order_id, _items(result.lines))
        return result

    def release_expired(self, limit: int = 50, on_result: OnRelease | None = None) -> int:
        """Release HELD reservations whose time is up. Returns how many were released.

        SKIP LOCKED makes each sweeper take different rows, so 2 sweepers running at the
        same time never release the same reservation twice.
        """
        released: list[ReleaseResult] = []
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(reservations.c.order_id, reservations.c["items"])
                .where(reservations.c.status == "HELD", reservations.c.expires_at < func.now())
                .order_by(reservations.c.expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for row in rows:
                lines = [Line.from_dict(d) for d in row.items]
                self._return_to_postgres(conn, row.order_id, lines)
                result = ReleaseResult(row.order_id, ReleaseOutcome.RELEASED, lines, "expired")
                if on_result is not None:
                    on_result(conn, result)
                released.append(result)
        for result in released:
            self._give_back_safely(result.order_id, _items(result.lines))
        return len(released)

    @staticmethod
    def _return_to_postgres(conn: Connection, order_id: uuid.UUID, lines: list[Line]) -> None:
        for line in sorted(lines, key=lambda line: line.product_id):
            conn.execute(
                update(stock)
                .where(stock.c.product_id == line.product_id)
                .values(available=stock.c.available + line.quantity, updated_at=func.now())
            )
        conn.execute(
            update(reservations)
            .where(reservations.c.order_id == order_id)
            .values(status="RELEASED", updated_at=func.now())
        )

    def _reserve_new(
        self, conn: Connection, order_id: uuid.UUID, items: list[Item]
    ) -> tuple[ReserveResult, bool]:
        catalog = self._catalog(conn, items)
        if len(catalog) != len(items):
            return ReserveResult(order_id, Outcome.REJECTED, reason="unknown_product"), False

        status = self._gate.try_reserve(order_id, items, self._hold_ttl_seconds)
        if status is RedisReserve.SHORT:
            return ReserveResult(order_id, Outcome.REJECTED, reason="out_of_stock"), False
        # ALREADY_HELD means an earlier attempt took the Redis stock but never saved to
        # Postgres. Finish that reservation now. If it fails, keep the hold: Redis then shows
        # less stock than Postgres (the safe side) until the hold is resynced.
        taken_in_redis = status is RedisReserve.RESERVED

        lines = [
            Line(i.product_id, catalog[i.product_id][0], i.quantity, catalog[i.product_id][1])
            for i in items
        ]
        if not self._take_in_postgres(conn, order_id, items, lines):
            log.warning("redis allowed a reservation that postgres refused; redis has drifted")
            if taken_in_redis:
                self._give_back_safely(order_id, items)
            return ReserveResult(order_id, Outcome.REJECTED, reason="out_of_stock"), False
        return ReserveResult(order_id, Outcome.RESERVED, lines), taken_in_redis

    def _existing(self, conn: Connection, order_id: uuid.UUID) -> ReserveResult | None:
        row = conn.execute(
            select(reservations.c["items"]).where(reservations.c.order_id == order_id)
        ).first()
        if row is None:
            return None
        lines = [Line.from_dict(d) for d in row.items]
        return ReserveResult(order_id, Outcome.ALREADY_RESERVED, lines)

    @staticmethod
    def _catalog(conn: Connection, items: list[Item]) -> dict[uuid.UUID, tuple[str, int]]:
        ids = [i.product_id for i in items]
        rows = conn.execute(
            select(products.c.id, products.c.name, products.c.price_cents).where(
                products.c.id.in_(ids)
            )
        )
        return {row.id: (row.name, row.price_cents) for row in rows}

    def _take_in_postgres(
        self, conn: Connection, order_id: uuid.UUID, items: list[Item], lines: list[Line]
    ) -> bool:
        # Lock the stock rows in a fixed order (items are sorted) so 2 orders never deadlock.
        rows = conn.execute(
            select(stock.c.product_id, stock.c.available)
            .where(stock.c.product_id.in_([i.product_id for i in items]))
            .order_by(stock.c.product_id)
            .with_for_update()
        )
        available = {row.product_id: row.available for row in rows}
        if any(available.get(i.product_id, 0) < i.quantity for i in items):
            return False
        for item in items:
            conn.execute(
                update(stock)
                .where(stock.c.product_id == item.product_id)
                .values(available=stock.c.available - item.quantity, updated_at=func.now())
            )
        conn.execute(
            insert(reservations).values(
                order_id=order_id,
                items=[line.as_dict() for line in lines],
                status="HELD",
                expires_at=func.now() + timedelta(seconds=self._hold_ttl_seconds),
            )
        )
        return True

    def _give_back_safely(self, order_id: uuid.UUID, items: list[Item]) -> None:
        try:
            self._gate.give_back(order_id, items)
        except Exception:
            # Redis keeps less stock than Postgres: safe (no overselling), fixed by a resync.
            log.error("giving stock back to redis failed; run a stock resync", exc_info=True)


def _items(lines: list[Line]) -> list[Item]:
    return sorted(Item(line.product_id, line.quantity) for line in lines)
