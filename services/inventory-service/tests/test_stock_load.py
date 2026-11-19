from inventory_service.seed import CATALOG, seed
from inventory_service.stock import load_stock_into_redis, stock_key


def test_load_copies_postgres_stock_into_redis(engine, redis_client):
    seed(engine)
    assert load_stock_into_redis(engine, redis_client) == len(CATALOG)
    for item in CATALOG:
        assert int(redis_client.get(stock_key(item.id))) == item.stock


def test_startup_load_keeps_existing_keys_but_resync_overwrites(engine, redis_client):
    seed(engine)
    load_stock_into_redis(engine, redis_client)
    lamp = CATALOG[-1]
    redis_client.set(stock_key(lamp.id), 3)  # as if 7 lamps are reserved right now

    assert load_stock_into_redis(engine, redis_client) == 0
    assert int(redis_client.get(stock_key(lamp.id))) == 3

    assert load_stock_into_redis(engine, redis_client, overwrite=True) == len(CATALOG)
    assert int(redis_client.get(stock_key(lamp.id))) == lamp.stock
