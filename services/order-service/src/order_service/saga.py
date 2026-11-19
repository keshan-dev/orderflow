"""The order saga: order-service moves each order forward 1 step per event.

PENDING -> STOCK_RESERVED -> CONFIRMED
   |             |
   v             v (payment failed, stock released)
CANCELLED     CANCELLED

Every status change is a conditional UPDATE: it applies only if the order is still in the
expected status. An old, late or repeated event changes 0 rows and is ignored.
"""

import uuid
from typing import Any

from sqlalchemy import Connection, func, update

from order_service.schema import orders

PENDING = "PENDING"
STOCK_RESERVED = "STOCK_RESERVED"
CONFIRMED = "CONFIRMED"
CANCELLED = "CANCELLED"


def move(
    conn: Connection,
    order_id: uuid.UUID,
    expected: str,
    new: str,
    *,
    only_if_not_cancelling: bool = False,
    **values: Any,
) -> bool:
    """Change the status from `expected` to `new`. Returns False if the order was not in
    `expected` (or, with only_if_not_cancelling, a cancellation has already started)."""
    query = update(orders).where(orders.c.id == order_id, orders.c.status == expected)
    if only_if_not_cancelling:
        query = query.where(orders.c.cancel_reason.is_(None))
    changed = conn.execute(
        query.values(status=new, updated_at=func.now(), **values).returning(orders.c.id)
    ).first()
    return changed is not None
