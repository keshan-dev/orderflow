"""M3 checks: duplicate events change nothing, and a stopped consumer catches up."""

import json
import time

import pytest
from helpers import (
    compose,
    db,
    event_types,
    is_e2e_enabled,
    kafka_messages,
    place_order,
    product_id,
    republish,
    wait_for_status,
)

pytestmark = pytest.mark.skipif(not is_e2e_enabled(), reason="Compose stack is not running")


def stock_available(product: str) -> int:
    with db("inventory_db") as conn:
        return conn.execute(
            "SELECT available FROM stock WHERE product_id = %s", (product,)
        ).fetchone()[0]


def test_duplicate_order_created_does_not_change_stock():
    keyboard = product_id("KB-001")
    order_id = place_order(keyboard, 2)
    wait_for_status(order_id, "STOCK_RESERVED")
    before = stock_available(keyboard)

    [original] = [
        m
        for m in kafka_messages("orders.events", order_id)
        if json.loads(m["value"])["event_type"] == "OrderCreated"
    ]
    republish("orders.events", order_id, original["value"], original["headers"])

    # Give inventory-service time to read the duplicate, then check nothing moved.
    time.sleep(5)
    assert stock_available(keyboard) == before
    assert event_types("inventory.events", order_id) == ["StockReserved"]


def test_stopped_inventory_service_processes_missed_orders_after_restart():
    mouse = product_id("MS-001")
    compose("stop", "inventory-service")
    try:
        orders = [place_order(mouse, 1) for _ in range(5)]
        assert all(wait_for_status(o, "PENDING")["status"] == "PENDING" for o in orders)
    finally:
        compose("start", "inventory-service")
    for order_id in orders:
        assert (
            wait_for_status(order_id, "STOCK_RESERVED", seconds=120)["status"] == "STOCK_RESERVED"
        )
