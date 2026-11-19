import uuid

import pytest
from sqlalchemy import select, update

from inventory_service.reservations import Outcome, Reservations
from inventory_service.schema import reservations, stock
from inventory_service.seed import CATALOG, seed
from inventory_service.stock import Item, RedisStock, hold_key, load_stock_into_redis, stock_key

KEYBOARD, MOUSE, LAMP = CATALOG[0], CATALOG[1], CATALOG[-1]


@pytest.fixture
def service(engine, redis_client):
    seed(engine)
    load_stock_into_redis(engine, redis_client)
    return Reservations(engine, RedisStock(redis_client), hold_ttl_seconds=900)


def pg_stock(engine, product_id):
    with engine.connect() as conn:
        return conn.scalar(select(stock.c.available).where(stock.c.product_id == product_id))


def redis_stock(redis_client, product_id):
    return int(redis_client.get(stock_key(product_id)))


def test_reserve_takes_stock_in_both_places(service, engine, redis_client):
    order = uuid.uuid4()
    result = service.reserve(order, [Item(KEYBOARD.id, 2)])
    assert result.outcome is Outcome.RESERVED
    assert result.lines[0].name == KEYBOARD.name
    assert result.lines[0].unit_price_cents == KEYBOARD.price_cents
    assert pg_stock(engine, KEYBOARD.id) == KEYBOARD.stock - 2
    assert redis_stock(redis_client, KEYBOARD.id) == KEYBOARD.stock - 2
    with engine.connect() as conn:
        assert conn.scalar(select(reservations.c.status)) == "HELD"


def test_more_than_stock_is_rejected_and_changes_nothing(service, engine, redis_client):
    result = service.reserve(uuid.uuid4(), [Item(LAMP.id, LAMP.stock + 1)])
    assert (result.outcome, result.reason) == (Outcome.REJECTED, "out_of_stock")
    assert pg_stock(engine, LAMP.id) == LAMP.stock
    assert redis_stock(redis_client, LAMP.id) == LAMP.stock


def test_multi_item_order_with_1_short_item_takes_nothing(service, engine, redis_client):
    items = sorted([Item(KEYBOARD.id, 1), Item(LAMP.id, LAMP.stock + 1)])
    assert service.reserve(uuid.uuid4(), items).outcome is Outcome.REJECTED
    assert pg_stock(engine, KEYBOARD.id) == KEYBOARD.stock
    assert redis_stock(redis_client, KEYBOARD.id) == KEYBOARD.stock


def test_same_order_twice_takes_stock_once(service, engine, redis_client):
    order = uuid.uuid4()
    assert service.reserve(order, [Item(MOUSE.id, 1)]).outcome is Outcome.RESERVED
    again = service.reserve(order, [Item(MOUSE.id, 1)])
    assert again.outcome is Outcome.ALREADY_RESERVED
    assert again.lines[0].quantity == 1
    assert pg_stock(engine, MOUSE.id) == MOUSE.stock - 1
    assert redis_stock(redis_client, MOUSE.id) == MOUSE.stock - 1


def test_unknown_product_is_rejected(service):
    result = service.reserve(uuid.uuid4(), [Item(uuid.uuid4(), 1)])
    assert (result.outcome, result.reason) == (Outcome.REJECTED, "unknown_product")


def test_postgres_failure_undoes_the_redis_change(service, engine, redis_client):
    order = uuid.uuid4()

    def fail_inside_transaction(conn, result):
        raise RuntimeError("database write failed")

    with pytest.raises(RuntimeError):
        service.reserve(order, [Item(KEYBOARD.id, 3)], on_result=fail_inside_transaction)
    assert redis_stock(redis_client, KEYBOARD.id) == KEYBOARD.stock
    assert not redis_client.exists(hold_key(order))
    assert pg_stock(engine, KEYBOARD.id) == KEYBOARD.stock


def test_redis_drift_is_caught_by_postgres(service, engine, redis_client):
    with engine.begin() as conn:
        conn.execute(update(stock).where(stock.c.product_id == LAMP.id).values(available=0))
    result = service.reserve(uuid.uuid4(), [Item(LAMP.id, 1)])  # Redis still says 10
    assert result.outcome is Outcome.REJECTED
    assert redis_stock(redis_client, LAMP.id) == LAMP.stock


def test_guard_can_skip_the_work(service, engine):
    result = service.reserve(uuid.uuid4(), [Item(KEYBOARD.id, 1)], guard=lambda conn: False)
    assert result.outcome is Outcome.DUPLICATE
    assert pg_stock(engine, KEYBOARD.id) == KEYBOARD.stock
