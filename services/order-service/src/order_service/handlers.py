"""Saga steps: react to inventory.events and payments.events.

Each step runs in 1 transaction: the processed_events check, the conditional status change
and the next event in the outbox are saved together or not at all.
"""

import logging
import uuid
from collections.abc import Callable

from sqlalchemy import Connection, Engine, func, update

from order_service.orders import AGGREGATE, order_payload
from order_service.saga import CANCELLED, PENDING, STOCK_RESERVED, move
from order_service.schema import order_items
from orderflow_common.events import Event, first_time, write_outbox

log = logging.getLogger(__name__)


class SagaHandler:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._routes: dict[str, Callable[[Connection, Event], None]] = {
            "StockReserved": self._stock_reserved,
            "StockRejected": self._stock_rejected,
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
        _write_order_event(conn, "OrderCancelled", event.order_id)
        log.info("order cancelled", extra={"reason": reason})


def _write_order_event(conn: Connection, event_type: str, order_id: uuid.UUID) -> None:
    write_outbox(conn, AGGREGATE, Event(event_type, order_id, order_payload(conn, order_id)))
