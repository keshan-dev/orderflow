"""Saga steps: react to inventory.events and payments.events.

Each step runs in 1 transaction: the processed_events check, the conditional status change
and the next event in the outbox are saved together or not at all.
"""

import logging
import uuid
from collections.abc import Callable

from sqlalchemy import Connection, Engine, func, select, update

from order_service.orders import AGGREGATE, order_payload
from order_service.saga import CANCELLED, CONFIRMED, PENDING, STOCK_RESERVED, move
from order_service.schema import order_items, orders
from orderflow_common.events import Event, first_time, write_outbox

log = logging.getLogger(__name__)


class SagaHandler:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._routes: dict[str, Callable[[Connection, Event], None]] = {
            "StockReserved": self._stock_reserved,
            "StockRejected": self._stock_rejected,
            "PaymentSucceeded": self._payment_succeeded,
            "PaymentFailed": self._payment_failed,
            "StockReleased": self._stock_released,
        }

    def __call__(self, event: Event) -> None:
        route = self._routes.get(event.event_type)
        if route is None:
            return
        with self._engine.begin() as conn:
            if not first_time(conn, event.event_id):
                log.info("duplicate event skipped", extra={"event_type": event.event_type})
                return
            route(conn, event)

    def _stock_reserved(self, conn: Connection, event: Event) -> None:
        total = int(event.payload["total_cents"])
        moved = move(
            conn,
            event.order_id,
            PENDING,
            STOCK_RESERVED,
            total_cents=total,
            stock_reserved_at=func.now(),
        )
        if not moved:
            log.info("stock reserved ignored: order is not PENDING")
            return
        for line in event.payload["lines"]:
            conn.execute(
                update(order_items)
                .where(
                    order_items.c.order_id == event.order_id,
                    order_items.c.product_id == uuid.UUID(line["product_id"]),
                )
                .values(name=line["name"], unit_price_cents=int(line["unit_price_cents"]))
            )
        payload = {**order_payload(conn, event.order_id), "amount_cents": total}
        write_outbox(conn, AGGREGATE, Event("ChargePaymentRequested", event.order_id, payload))
        log.info("stock reserved; payment requested", extra={"amount_cents": total})

    def _stock_rejected(self, conn: Connection, event: Event) -> None:
        reason = str(event.payload.get("reason", "out_of_stock"))
        if not move(conn, event.order_id, PENDING, CANCELLED, cancel_reason=reason):
            log.info("stock rejected ignored: order is not PENDING")
            return
        write_order_event(conn, "OrderCancelled", event.order_id)
        log.info("order cancelled", extra={"reason": reason})

    def _payment_succeeded(self, conn: Connection, event: Event) -> None:
        if move(conn, event.order_id, STOCK_RESERVED, CONFIRMED, only_if_not_cancelling=True):
            write_order_event(conn, "OrderConfirmed", event.order_id)
            log.info("order confirmed")
            return
        # The order is already cancelled or cancelling (for example the payment timed out
        # first). The money was taken, so it must be given back.
        payload = {"payment_id": event.payload.get("payment_id"), "reason": "order_not_payable"}
        write_outbox(conn, AGGREGATE, Event("RefundPaymentRequested", event.order_id, payload))
        log.warning("payment succeeded for an order that cannot be confirmed; refund requested")

    def _payment_failed(self, conn: Connection, event: Event) -> None:
        reason = f"payment_failed:{event.payload.get('reason', 'unknown')}"
        if not start_cancelling(conn, event.order_id, reason):
            log.info("payment failed ignored: order is not waiting for payment")
            return
        write_order_event(conn, "ReleaseStockRequested", event.order_id)
        log.info("payment failed; stock release requested", extra={"reason": reason})

    def _stock_released(self, conn: Connection, event: Event) -> None:
        # Usually cancel_reason is already set (payment failed or timed out). If the hold
        # simply expired first, record that as the reason.
        reason = conn.execute(
            select(orders.c.cancel_reason).where(orders.c.id == event.order_id)
        ).scalar()
        new_reason = reason or f"stock_{event.payload.get('reason', 'released')}"
        if not move(conn, event.order_id, STOCK_RESERVED, CANCELLED, cancel_reason=new_reason):
            log.info("stock released ignored: order is not waiting for payment")
            return
        write_order_event(conn, "OrderCancelled", event.order_id)
        log.info("order cancelled after stock release", extra={"reason": new_reason})


def start_cancelling(conn: Connection, order_id: uuid.UUID, reason: str) -> bool:
    """Mark a STOCK_RESERVED order as cancelling. The status stays STOCK_RESERVED until the
    stock is really released; cancel_reason stops a late payment from confirming it."""
    changed = conn.execute(
        update(orders)
        .where(
            orders.c.id == order_id,
            orders.c.status == STOCK_RESERVED,
            orders.c.cancel_reason.is_(None),
        )
        .values(cancel_reason=reason, updated_at=func.now())
        .returning(orders.c.id)
    ).first()
    return changed is not None


def write_order_event(conn: Connection, event_type: str, order_id: uuid.UUID) -> None:
    write_outbox(conn, AGGREGATE, Event(event_type, order_id, order_payload(conn, order_id)))
