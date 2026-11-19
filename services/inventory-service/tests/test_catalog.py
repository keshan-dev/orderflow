from sqlalchemy import update

from inventory_service.catalog import CACHE_KEY, list_products
from inventory_service.schema import stock
from inventory_service.seed import CATALOG, seed


def test_second_call_is_served_from_cache(engine, redis_client):
    seed(engine)
    first = list_products(engine, redis_client, ttl_seconds=60)
    assert len(first) == len(CATALOG)
    assert 0 < redis_client.ttl(CACHE_KEY) <= 60

    with engine.begin() as conn:
        conn.execute(update(stock).values(available=0))
    cached = list_products(engine, redis_client, ttl_seconds=60)
    assert cached == first  # Postgres changed, but the cached copy is returned

    redis_client.delete(CACHE_KEY)
    fresh = list_products(engine, redis_client, ttl_seconds=60)
    assert {p["available"] for p in fresh} == {0}
