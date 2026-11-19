import uuid

import pytest
from sqlalchemy import select, text

from inventory_service.handlers import InventoryEventHandler
from inventory_service.reservations import Reservations
from inventory_service.schema import stock
from inventory_service.seed import CATALOG, seed
from inventory_service.stock import RedisStock, load_stock_into_redis
from orderflow_common.events import Event

LAMP = CATALOG[-1]


@pytest.fixture
def handler(engine, redis_client):
    seed(engine)
    load_stock_into_redis(engine, redis_client)
    return InventoryEventHandler(Reservations(engine, RedisStock(redis_client), 900))


def order_created(quantity: int, product_id=LAMP.id) -> Event:
    order = {"items": [{"product_id": str(product_id), "quantity": quantity}]}
    return Event("OrderCreated", uuid.uuid4(), {"order": order})


def outbox(engine) -> list[Event]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT payload FROM outbox ORDER BY created_at")).scalars()
        return [Event.from_envelope(row) for row in rows]


def lamp_stock(engine) -> int:
    with engine.connect() as conn:
        return conn.scalar(select(stock.c.available).where(stock.c.product_id == LAMP.id))


def test_order_created_reserves_and_replies_stock_reserved(handler, engine):
    event = order_created(2)
    handler(event)
    [reply] = outbox(engine)
    assert (reply.event_type, reply.order_id) == ("StockReserved", event.order_id)
    assert reply.payload["total_cents"] == 2 * LAMP.price_cents
    assert reply.payload["lines"][0]["name"] == LAMP.name
    assert lamp_stock(engine) == LAMP.stock - 2


def test_duplicate_order_created_changes_stock_once(handler, engine):
    event = order_created(1)
    handler(event)
    handler(event)  # Kafka delivered it again
    assert len(outbox(engine)) == 1
    assert lamp_stock(engine) == LAMP.stock - 1


def test_not_enough_stock_replies_stock_rejected(handler, engine):
    handler(order_created(LAMP.stock + 1))
    [reply] = outbox(engine)
    assert (reply.event_type, reply.payload["reason"]) == ("StockRejected", "out_of_stock")
    assert lamp_stock(engine) == LAMP.stock


def test_invalid_items_reply_stock_rejected(handler, engine):
    handler(Event("OrderCreated", uuid.uuid4(), {"order": {"items": []}}))
    [reply] = outbox(engine)
    assert reply.payload["reason"] == "invalid_items"


def test_other_event_types_are_ignored(handler, engine):
    handler(Event("SomethingElse", uuid.uuid4(), {}))
    assert outbox(engine) == []


def event_types(engine) -> list[str]:
    return [e.event_type for e in outbox(engine)]


def test_release_requested_returns_stock_and_replies(handler, engine):
    created = order_created(3)
    handler(created)
    handler(Event("ReleaseStockRequested", created.order_id, {}))
    assert event_types(engine) == ["StockReserved", "StockReleased"]
    assert lamp_stock(engine) == LAMP.stock


def test_repeated_release_request_still_gets_an_answer_but_stock_moves_once(handler, engine):
    created = order_created(3)
    handler(created)
    handler(Event("ReleaseStockRequested", created.order_id, {}))
    handler(Event("ReleaseStockRequested", created.order_id, {}))  # a new request
    assert event_types(engine) == ["StockReserved", "StockReleased", "StockReleased"]
    assert lamp_stock(engine) == LAMP.stock


def test_order_confirmed_commits_so_the_sweeper_never_returns_sold_stock(handler, engine):
    from datetime import timedelta

    from sqlalchemy import func, update

    from inventory_service.schema import reservations
    from inventory_service.sweeper import Sweeper

    created = order_created(2)
    handler(created)
    handler(Event("OrderConfirmed", created.order_id, {}))
    with engine.begin() as conn:
        conn.execute(update(reservations).values(expires_at=func.now() - timedelta(seconds=1)))
    assert Sweeper(handler._reservations, interval_seconds=60).sweep_once() == 0
    assert lamp_stock(engine) == LAMP.stock - 2


def test_sweeper_tells_order_service_about_expired_holds(handler, engine):
    from datetime import timedelta

    from sqlalchemy import func, update

    from inventory_service.handlers import write_released
    from inventory_service.schema import reservations
    from inventory_service.sweeper import Sweeper

    handler(order_created(1))
    with engine.begin() as conn:
        conn.execute(update(reservations).values(expires_at=func.now() - timedelta(seconds=1)))
    Sweeper(handler._reservations, 60, on_result=write_released).sweep_once()
    released = outbox(engine)[-1]
    assert (released.event_type, released.payload["reason"]) == ("StockReleased", "expired")
