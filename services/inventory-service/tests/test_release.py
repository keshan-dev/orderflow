import uuid

import pytest
from sqlalchemy import select, update

from inventory_service.reservations import ReleaseOutcome, Reservations
from inventory_service.schema import reservations, stock
from inventory_service.seed import CATALOG, seed
from inventory_service.stock import Item, RedisStock, hold_key, load_stock_into_redis, stock_key

KEYBOARD = CATALOG[0]


@pytest.fixture
def service(engine, redis_client):
    seed(engine)
    load_stock_into_redis(engine, redis_client)
    return Reservations(engine, RedisStock(redis_client), hold_ttl_seconds=900)


def stock_in_both(engine, redis_client):
    with engine.connect() as conn:
        pg = conn.scalar(select(stock.c.available).where(stock.c.product_id == KEYBOARD.id))
    return pg, int(redis_client.get(stock_key(KEYBOARD.id)))


def test_release_returns_stock_in_both_places(service, engine, redis_client):
    order = uuid.uuid4()
    service.reserve(order, [Item(KEYBOARD.id, 4)])
    result = service.release(order)
    assert result.outcome is ReleaseOutcome.RELEASED
    assert stock_in_both(engine, redis_client) == (KEYBOARD.stock, KEYBOARD.stock)
    assert not redis_client.exists(hold_key(order))


def test_release_twice_returns_stock_once(service, engine, redis_client):
    order = uuid.uuid4()
    service.reserve(order, [Item(KEYBOARD.id, 4)])
    service.release(order)
    again = service.release(order)
    assert again.outcome is ReleaseOutcome.ALREADY_RELEASED
    assert again.lines[0].quantity == 4
    assert stock_in_both(engine, redis_client) == (KEYBOARD.stock, KEYBOARD.stock)


def test_release_of_unknown_order_changes_nothing(service, engine, redis_client):
    assert service.release(uuid.uuid4()).outcome is ReleaseOutcome.NOT_FOUND
    assert stock_in_both(engine, redis_client) == (KEYBOARD.stock, KEYBOARD.stock)


def test_committed_stock_is_never_released(service, engine, redis_client):
    order = uuid.uuid4()
    service.reserve(order, [Item(KEYBOARD.id, 2)])
    with engine.begin() as conn:
        conn.execute(update(reservations).values(status="COMMITTED"))
    assert service.release(order).outcome is ReleaseOutcome.COMMITTED
    expected = KEYBOARD.stock - 2
    assert stock_in_both(engine, redis_client) == (expected, expected)
