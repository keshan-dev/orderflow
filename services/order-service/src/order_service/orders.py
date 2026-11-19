"""Create and read orders. An order and its OrderCreated event are saved in 1 transaction."""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, select
from sqlalchemy.dialects.postgresql import insert

from order_service.schema import order_items, orders
from orderflow_common.events import Event, write_outbox

AGGREGATE = "orders"


@dataclass(frozen=True, order=True)
class OrderItem:
    product_id: uuid.UUID
    quantity: int


@dataclass(frozen=True)
class NewOrder:
    customer_email: str
    items: list[OrderItem]

    @classmethod
    def build(cls, customer_email: str, items: list[tuple[uuid.UUID, int]]) -> "NewOrder":
        """Merge repeated products and sort items, so equal requests look exactly equal."""
        totals: dict[uuid.UUID, int] = {}
        for product_id, quantity in items:
            totals[product_id] = totals.get(product_id, 0) + quantity
        merged = sorted(OrderItem(pid, qty) for pid, qty in totals.items())
        return cls(customer_email.strip().lower(), merged)

    def fingerprint(self) -> str:
        """Same request body gives the same fingerprint; used to spot a reused Idempotency-Key."""
        canonical = json.dumps(
            {
                "customer_email": self.customer_email,
                "items": [[str(i.product_id), i.quantity] for i in self.items],
            },
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class CreateResult:
    order_id: uuid.UUID
    created: bool
    same_request: bool


def create_order(engine: Engine, idempotency_key: str, new_order: NewOrder) -> CreateResult:
    fingerprint = new_order.fingerprint()
    with engine.begin() as conn:
        order_id = conn.execute(
            insert(orders)
            .values(
                id=uuid.uuid4(),
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                customer_email=new_order.customer_email,
                status="PENDING",
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(orders.c.id)
        ).scalar()
        if order_id is None:
            existing = conn.execute(
                select(orders.c.id, orders.c.request_fingerprint).where(
                    orders.c.idempotency_key == idempotency_key
                )
            ).one()
            return CreateResult(existing.id, False, existing.request_fingerprint == fingerprint)

        conn.execute(
            insert(order_items),
            [
                {"order_id": order_id, "product_id": i.product_id, "quantity": i.quantity}
                for i in new_order.items
            ],
        )
        write_outbox(
            conn, AGGREGATE, Event("OrderCreated", order_id, order_payload(conn, order_id))
        )
    return CreateResult(order_id, True, True)


def order_payload(conn: Connection, order_id: uuid.UUID) -> dict[str, Any]:
    """Every orders.events event carries a full snapshot of the order."""
    snap = snapshot(conn, order_id)
    if snap is None:
        raise LookupError(f"order {order_id} not found")
    return {"order": snap}


def snapshot(conn: Connection, order_id: uuid.UUID) -> dict[str, Any] | None:
    row = conn.execute(select(orders).where(orders.c.id == order_id)).first()
    if row is None:
        return None
    items = conn.execute(
        select(order_items)
        .where(order_items.c.order_id == order_id)
        .order_by(order_items.c.product_id)
    ).all()
    return {
        "order_id": str(row.id),
        "customer_email": row.customer_email,
        "status": row.status,
        "cancel_reason": row.cancel_reason,
        "total_cents": row.total_cents,
        "items": [
            {
                "product_id": str(item.product_id),
                "quantity": item.quantity,
                "name": item.name,
                "unit_price_cents": item.unit_price_cents,
            }
            for item in items
        ],
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def get_order(engine: Engine, order_id: uuid.UUID) -> dict[str, Any] | None:
    with engine.connect() as conn:
        return snapshot(conn, order_id)
