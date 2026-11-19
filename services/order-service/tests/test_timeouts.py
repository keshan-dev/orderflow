import uuid
from datetime import timedelta

from sqlalchemy import func, text, update

from order_service.handlers import SagaHandler
from order_service.orders import NewOrder, create_order, get_order
from order_service.schema import orders
from order_service.timeouts import cancel_timed_out_orders
from orderflow_common.events import Event


def reserved_order(engine) -> uuid.UUID:
    product = uuid.uuid4()
    order_id = create_order(
        engine, str(uuid.uuid4()), NewOrder.build("a@b.co", [(product, 1)])
    ).order_id
    lines = [{"product_id": str(product), "name": "x", "quantity": 1, "unit_price_cents": 100}]
    SagaHandler(engine)(Event("StockReserved", order_id, {"lines": lines, "total_cents": 100}))
    return order_id


def make_old(engine, order_id):
    with engine.begin() as conn:
        conn.execute(
            update(orders)
            .where(orders.c.id == order_id)
            .values(stock_reserved_at=func.now() - timedelta(minutes=10))
        )


def last_event(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT type FROM outbox ORDER BY created_at DESC LIMIT 1")
        ).scalar()


def test_order_waiting_too_long_starts_compensation(engine):
    old, fresh = reserved_order(engine), reserved_order(engine)
    make_old(engine, old)
    assert cancel_timed_out_orders(engine, timeout_seconds=120) == 1
    assert get_order(engine, old)["cancel_reason"] == "payment_timeout"
    assert get_order(engine, fresh)["cancel_reason"] is None
    assert last_event(engine) == "ReleaseStockRequested"


def test_timed_out_order_is_handled_once(engine):
    order_id = reserved_order(engine)
    make_old(engine, order_id)
    cancel_timed_out_orders(engine, timeout_seconds=120)
    assert cancel_timed_out_orders(engine, timeout_seconds=120) == 0
