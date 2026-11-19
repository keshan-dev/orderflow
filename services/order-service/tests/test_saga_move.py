from sqlalchemy import select

from order_service.orders import NewOrder, create_order
from order_service.saga import CANCELLED, CONFIRMED, PENDING, STOCK_RESERVED, move
from order_service.schema import orders


def new_order(engine, key="k"):
    import uuid

    return create_order(engine, key, NewOrder.build("a@b.co", [(uuid.uuid4(), 1)])).order_id


def status(engine, order_id):
    with engine.connect() as conn:
        return conn.scalar(select(orders.c.status).where(orders.c.id == order_id))


def test_move_from_the_expected_status(engine):
    order_id = new_order(engine)
    with engine.begin() as conn:
        assert move(conn, order_id, PENDING, STOCK_RESERVED, total_cents=100)
    assert status(engine, order_id) == STOCK_RESERVED


def test_old_or_repeated_event_changes_nothing(engine):
    order_id = new_order(engine)
    with engine.begin() as conn:
        move(conn, order_id, PENDING, STOCK_RESERVED)
        move(conn, order_id, STOCK_RESERVED, CONFIRMED)
    with engine.begin() as conn:
        # A late "stock reserved" must not move a confirmed order backwards.
        assert move(conn, order_id, PENDING, STOCK_RESERVED) is False
        assert move(conn, order_id, PENDING, CANCELLED) is False
    assert status(engine, order_id) == CONFIRMED


def test_only_if_not_cancelling_blocks_a_cancelling_order(engine):
    order_id = new_order(engine)
    with engine.begin() as conn:
        move(conn, order_id, PENDING, STOCK_RESERVED)
        conn.execute(orders.update().values(cancel_reason="payment_timeout"))
    with engine.begin() as conn:
        assert not move(conn, order_id, STOCK_RESERVED, CONFIRMED, only_if_not_cancelling=True)
    assert status(engine, order_id) == STOCK_RESERVED
