"""Many buyers, few items: the system must never sell more than it has."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import delete, func, select, text, update

from inventory_service.reservations import Outcome, Reservations
from inventory_service.schema import reservations, stock
from inventory_service.seed import CATALOG, seed
from inventory_service.stock import Item, RedisStock, load_stock_into_redis, stock_key

LAMP = CATALOG[-1]  # 10 in stock
BUYERS = 50
ROUNDS = 10


@pytest.fixture
def service(engine, redis_client):
    seed(engine)
    return Reservations(engine, RedisStock(redis_client), hold_ttl_seconds=900)


def reset_lamp(engine, redis_client):
    with engine.begin() as conn:
        conn.execute(delete(reservations))
        conn.execute(text("TRUNCATE processed_events"))
        conn.execute(
            update(stock).where(stock.c.product_id == LAMP.id).values(available=LAMP.stock)
        )
    load_stock_into_redis(engine, redis_client, overwrite=True)


def run_buyers(service: Reservations) -> list[Outcome]:
    start = threading.Barrier(BUYERS)

    def buy(_: int) -> Outcome:
        start.wait()  # release all buyers at the same moment
        return service.reserve(uuid.uuid4(), [Item(LAMP.id, 1)]).outcome

    with ThreadPoolExecutor(max_workers=BUYERS) as pool:
        return list(pool.map(buy, range(BUYERS)))


def test_50_parallel_buyers_get_exactly_10_lamps(service, engine, redis_client):
    for round_number in range(ROUNDS):
        reset_lamp(engine, redis_client)
        outcomes = run_buyers(service)

        sold = outcomes.count(Outcome.RESERVED)
        assert sold == LAMP.stock, f"round {round_number}: sold {sold}"
        assert outcomes.count(Outcome.REJECTED) == BUYERS - LAMP.stock
        with engine.connect() as conn:
            pg = conn.scalar(select(stock.c.available).where(stock.c.product_id == LAMP.id))
            held = conn.scalar(select(func.count()).select_from(reservations))
        assert pg == 0
        assert held == LAMP.stock
        assert int(redis_client.get(stock_key(LAMP.id))) == 0
