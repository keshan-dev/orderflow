import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from inventory_service.reservations import Reservations
from inventory_service.schema import reservations, stock
from inventory_service.seed import CATALOG, seed
from inventory_service.stock import Item, RedisStock, load_stock_into_redis, stock_key
from inventory_service.sweeper import Sweeper

MOUSE = CATALOG[1]
ORDERS = 40


@pytest.fixture
def service(engine, redis_client):
    seed(engine)
    load_stock_into_redis(engine, redis_client)
    return Reservations(engine, RedisStock(redis_client), hold_ttl_seconds=900)


def expire_all(engine):
    with engine.begin() as conn:
        conn.execute(update(reservations).values(expires_at=func.now() - timedelta(seconds=1)))


def test_sweeper_releases_only_expired_holds(service, engine, redis_client):
    expired, fresh = uuid.uuid4(), uuid.uuid4()
    service.reserve(expired, [Item(MOUSE.id, 1)])
    expire_all(engine)
    service.reserve(fresh, [Item(MOUSE.id, 1)])

    assert Sweeper(service, interval_seconds=60).sweep_once() == 1
    with engine.connect() as conn:
        statuses = dict(conn.execute(select(reservations.c.order_id, reservations.c.status)).all())
    assert statuses == {expired: "RELEASED", fresh: "HELD"}
    assert int(redis_client.get(stock_key(MOUSE.id))) == MOUSE.stock - 1


def test_2_sweepers_at_once_never_release_the_same_hold_twice(service, engine, redis_client):
    for _ in range(ORDERS):
        service.reserve(uuid.uuid4(), [Item(MOUSE.id, 1)])
    expire_all(engine)

    counts: list[int] = []
    barrier = threading.Barrier(2)

    def sweep():
        barrier.wait()
        total = 0
        while released := service.release_expired(limit=5):
            total += released
        counts.append(total)

    threads = [threading.Thread(target=sweep) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(counts) == ORDERS
    with engine.connect() as conn:
        pg = conn.scalar(select(stock.c.available).where(stock.c.product_id == MOUSE.id))
    assert pg == MOUSE.stock
    assert int(redis_client.get(stock_key(MOUSE.id))) == MOUSE.stock
