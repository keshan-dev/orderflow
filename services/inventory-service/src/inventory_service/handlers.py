"""React to events on orders.events. Each handler is idempotent.

The duplicate check (processed_events), the stock change and the reply event in the outbox
are saved in 1 transaction, so a redelivered event is skipped and a reply is never lost.
"""

import logging
from collections.abc import Callable

from sqlalchemy import Connection

from inventory_service.reservations import Line, Outcome, Reservations, ReserveResult
from inventory_service.stock import InvalidItemsError, normalize_items
from orderflow_common.events import Event, first_time, write_outbox

log = logging.getLogger(__name__)

AGGREGATE = "inventory"


def _total_cents(lines: list[Line]) -> int:
    return sum(line.quantity * line.unit_price_cents for line in lines)


class InventoryEventHandler:
    def __init__(self, reservations: Reservations) -> None:
        self._reservations = reservations
        self._routes: dict[str, Callable[[Event], None]] = {
            "OrderCreated": self._order_created,
        }

    def __call__(self, event: Event) -> None:
        route = self._routes.get(event.event_type)
        if route is not None:
            route(event)

    def _order_created(self, event: Event) -> None:
        def guard(conn: Connection) -> bool:
            return first_time(conn, event.event_id)

        try:
            items = normalize_items(event.payload["order"]["items"])
        except (InvalidItemsError, KeyError, TypeError):
            log.warning("order has invalid items; rejecting it")
            with self._reservations.engine.begin() as conn:
                if guard(conn):
                    rejected = Event("StockRejected", event.order_id, {"reason": "invalid_items"})
                    write_outbox(conn, AGGREGATE, rejected)
            return

        def reply(conn: Connection, result: ReserveResult) -> None:
            write_outbox(conn, AGGREGATE, reserve_reply(result))

        result = self._reservations.reserve(event.order_id, items, guard=guard, on_result=reply)
        log.info(
            "order created handled", extra={"outcome": result.outcome, "reason": result.reason}
        )


def reserve_reply(result: ReserveResult) -> Event:
    if result.outcome in (Outcome.RESERVED, Outcome.ALREADY_RESERVED):
        payload = {
            "lines": [line.as_dict() for line in result.lines],
            "total_cents": _total_cents(result.lines),
        }
        return Event("StockReserved", result.order_id, payload)
    return Event("StockRejected", result.order_id, {"reason": result.reason or "out_of_stock"})
