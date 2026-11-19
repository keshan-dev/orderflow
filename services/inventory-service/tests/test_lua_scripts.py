import uuid

import pytest

from inventory_service.stock import (
    InvalidItemsError,
    Item,
    RedisReserve,
    RedisStock,
    hold_key,
    normalize_items,
    stock_key,
)

P1 = uuid.UUID("00000000-0000-0000-0000-000000000001")
P2 = uuid.UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture
def gate(redis_client):
    redis_client.set(stock_key(P1), 5)
    redis_client.set(stock_key(P2), 1)
    return RedisStock(redis_client)


def test_reserve_takes_all_items_and_writes_hold(gate, redis_client):
    order = uuid.uuid4()
    items = [Item(P1, 2), Item(P2, 1)]
    assert gate.try_reserve(order, items, ttl_seconds=900) is RedisReserve.RESERVED
    assert redis_client.get(stock_key(P1)) == "3"
    assert redis_client.get(stock_key(P2)) == "0"
    assert 0 < redis_client.ttl(hold_key(order)) <= 900


def test_reserve_takes_nothing_when_1_item_is_short(gate, redis_client):
    items = [Item(P1, 2), Item(P2, 2)]
    assert gate.try_reserve(uuid.uuid4(), items, ttl_seconds=900) is RedisReserve.SHORT
    assert redis_client.get(stock_key(P1)) == "5"
    assert redis_client.get(stock_key(P2)) == "1"


def test_unknown_product_counts_as_no_stock(gate):
    items = [Item(uuid.uuid4(), 1)]
    assert gate.try_reserve(uuid.uuid4(), items, ttl_seconds=900) is RedisReserve.SHORT


def test_same_order_twice_takes_stock_once(gate, redis_client):
    order = uuid.uuid4()
    assert gate.try_reserve(order, [Item(P1, 1)], 900) is RedisReserve.RESERVED
    assert gate.try_reserve(order, [Item(P1, 1)], 900) is RedisReserve.ALREADY_HELD
    assert redis_client.get(stock_key(P1)) == "4"


def test_give_back_returns_stock_and_removes_hold(gate, redis_client):
    order = uuid.uuid4()
    gate.try_reserve(order, [Item(P1, 3)], 900)
    gate.give_back(order, [Item(P1, 3)])
    assert redis_client.get(stock_key(P1)) == "5"
    assert not redis_client.exists(hold_key(order))


def test_normalize_merges_sorts_and_validates():
    raw = [
        {"product_id": str(P2), "quantity": 1},
        {"product_id": str(P1), "quantity": 1},
        {"product_id": str(P2), "quantity": 2},
    ]
    assert normalize_items(raw) == [Item(P1, 1), Item(P2, 3)]
    bad_inputs = [
        [],
        [{"product_id": "nope", "quantity": 1}],
        [{"product_id": str(P1), "quantity": 0}],
    ]
    for bad in bad_inputs:
        with pytest.raises(InvalidItemsError):
            normalize_items(bad)
