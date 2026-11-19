import uuid

import pytest
from sqlalchemy import text

from order_service.handlers import SagaHandler
from order_service.orders import NewOrder, create_order, get_order
from orderflow_common.events import Event

PRODUCT = uuid.uuid4()


@pytest.fixture
def handler(engine):
    return SagaHandler(engine)


@pytest.fixture
def order_id(engine):
    new = NewOrder.build("buyer@example.com", [(PRODUCT, 2)])
    return create_order(engine, f"key-{uuid.uuid4()}", new).order_id


def stock_reserved(order_id, unit_price=500):
    lines = [
        {"product_id": str(PRODUCT), "name": "Lamp", "quantity": 2, "unit_price_cents": unit_price}
    ]
    return Event("StockReserved", order_id, {"lines": lines, "total_cents": 2 * unit_price})


def events_after_order_created(engine) -> list[Event]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT payload FROM outbox ORDER BY created_at")).scalars()
        return [Event.from_envelope(r) for r in rows if r["event_type"] != "OrderCreated"]


def test_stock_reserved_moves_order_and_requests_payment(handler, engine, order_id):
    handler(stock_reserved(order_id))
    order = get_order(engine, order_id)
    assert (order["status"], order["total_cents"]) == ("STOCK_RESERVED", 1000)
    assert order["items"][0]["name"] == "Lamp"
    [charge] = events_after_order_created(engine)
    assert charge.event_type == "ChargePaymentRequested"
    assert charge.payload["amount_cents"] == 1000
    assert charge.payload["order"]["status"] == "STOCK_RESERVED"


def test_stock_rejected_cancels_the_order(handler, engine, order_id):
    handler(Event("StockRejected", order_id, {"reason": "out_of_stock"}))
    order = get_order(engine, order_id)
    assert (order["status"], order["cancel_reason"]) == ("CANCELLED", "out_of_stock")
    assert [e.event_type for e in events_after_order_created(engine)] == ["OrderCancelled"]


def test_duplicate_event_is_handled_once(handler, engine, order_id):
    event = stock_reserved(order_id)
    handler(event)
    handler(event)
    assert len(events_after_order_created(engine)) == 1


def test_late_event_does_not_move_the_order_backwards(handler, engine, order_id):
    handler(Event("StockRejected", order_id, {"reason": "out_of_stock"}))
    handler(stock_reserved(order_id))  # a different event that arrives too late
    assert get_order(engine, order_id)["status"] == "CANCELLED"
    assert [e.event_type for e in events_after_order_created(engine)] == ["OrderCancelled"]


def payment_succeeded(order_id):
    return Event(
        "PaymentSucceeded", order_id, {"payment_id": str(uuid.uuid4()), "amount_cents": 1000}
    )


def test_payment_succeeded_confirms_the_order(handler, engine, order_id):
    handler(stock_reserved(order_id))
    handler(payment_succeeded(order_id))
    assert get_order(engine, order_id)["status"] == "CONFIRMED"
    types = [e.event_type for e in events_after_order_created(engine)]
    assert types == ["ChargePaymentRequested", "OrderConfirmed"]


def test_payment_failed_starts_compensation(handler, engine, order_id):
    handler(stock_reserved(order_id))
    handler(Event("PaymentFailed", order_id, {"reason": "card_declined"}))
    order = get_order(engine, order_id)
    assert (order["status"], order["cancel_reason"]) == (
        "STOCK_RESERVED",
        "payment_failed:card_declined",
    )
    assert events_after_order_created(engine)[-1].event_type == "ReleaseStockRequested"


def test_late_payment_after_cancellation_is_refunded(handler, engine, order_id):
    handler(stock_reserved(order_id))
    handler(Event("PaymentFailed", order_id, {"reason": "provider_timeout"}))
    handler(payment_succeeded(order_id))  # arrives late
    assert get_order(engine, order_id)["status"] == "STOCK_RESERVED"  # never CONFIRMED
    assert events_after_order_created(engine)[-1].event_type == "RefundPaymentRequested"
