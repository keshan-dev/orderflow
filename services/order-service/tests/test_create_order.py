import uuid

import pytest
from sqlalchemy import func, select

from order_service import orders as orders_module
from order_service.orders import NewOrder, create_order
from order_service.schema import order_items, orders
from orderflow_common.events import Event

P1, P2 = uuid.uuid4(), uuid.uuid4()


def outbox_rows(engine):
    from sqlalchemy import text

    with engine.connect() as conn:
        return conn.execute(text("SELECT type, aggregateid, payload FROM outbox")).all()


def count(engine, table):
    with engine.connect() as conn:
        return conn.scalar(select(func.count()).select_from(table))


def test_order_and_its_event_are_saved_together(engine):
    new = NewOrder.build("Buyer@Example.com", [(P1, 1), (P2, 2), (P1, 1)])
    result = create_order(engine, "key-1", new)
    assert result.created

    rows = outbox_rows(engine)
    assert len(rows) == 1
    event_type, aggregateid, payload = rows[0]
    assert (event_type, aggregateid) == ("OrderCreated", str(result.order_id))
    event = Event.from_envelope(payload)
    order = event.payload["order"]
    assert order["status"] == "PENDING"
    assert order["customer_email"] == "buyer@example.com"
    assert {i["product_id"]: i["quantity"] for i in order["items"]} == {str(P1): 2, str(P2): 2}


def test_failed_transaction_saves_neither_order_nor_event(engine, monkeypatch):
    def broken_outbox(*args, **kwargs):
        raise RuntimeError("outbox insert failed")

    monkeypatch.setattr(orders_module, "write_outbox", broken_outbox)
    with pytest.raises(RuntimeError):
        create_order(engine, "key-2", NewOrder.build("a@b.co", [(P1, 1)]))
    assert count(engine, orders) == 0
    assert count(engine, order_items) == 0
    assert outbox_rows(engine) == []


def test_same_key_returns_the_first_order(engine):
    new = NewOrder.build("a@b.co", [(P1, 1)])
    first = create_order(engine, "key-3", new)
    second = create_order(engine, "key-3", new)
    assert (second.order_id, second.created, second.same_request) == (first.order_id, False, True)
    assert count(engine, orders) == 1
    assert len(outbox_rows(engine)) == 1


def test_same_key_with_a_different_body_is_spotted(engine):
    create_order(engine, "key-4", NewOrder.build("a@b.co", [(P1, 1)]))
    other = create_order(engine, "key-4", NewOrder.build("a@b.co", [(P1, 5)]))
    assert other.same_request is False
