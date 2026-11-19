"""Cancel orders that waited too long for a payment answer.

The timeout must stay shorter than inventory-service's hold expiry (HOLD_TTL_SECONDS), so
order-service starts the compensation before the stock hold runs out on its own.
"""

import logging
from datetime import timedelta

from sqlalchemy import Engine, func, select

from order_service.handlers import start_cancelling, write_order_event
from order_service.saga import STOCK_RESERVED
from order_service.schema import orders

log = logging.getLogger(__name__)


def cancel_timed_out_orders(engine: Engine, timeout_seconds: int, limit: int = 50) -> int:
    """Start compensation for orders stuck in STOCK_RESERVED. Returns how many were found.

    SKIP LOCKED lets both order-service copies run this at the same time without
    handling the same order twice.
    """
    with engine.begin() as conn:
        order_ids = (
            conn.execute(
                select(orders.c.id)
                .where(
                    orders.c.status == STOCK_RESERVED,
                    orders.c.cancel_reason.is_(None),
                    orders.c.stock_reserved_at < func.now() - timedelta(seconds=timeout_seconds),
                )
                .order_by(orders.c.stock_reserved_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        for order_id in order_ids:
            if start_cancelling(conn, order_id, "payment_timeout"):
                write_order_event(conn, "ReleaseStockRequested", order_id)
    if order_ids:
        log.warning("payment timed out; stock release requested", extra={"orders": len(order_ids)})
    return len(order_ids)
