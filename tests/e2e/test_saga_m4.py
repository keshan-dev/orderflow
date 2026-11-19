"""M4 checks: payment success, failure, timeout and late payment refund, end to end."""

import json

import pytest
from helpers import (
    compose,
    db,
    is_e2e_enabled,
    kafka_messages,
    place_order,
    product_id,
    recreate,
    republish,
    wait_for_status,
    wait_until,
)

pytestmark = pytest.mark.skipif(not is_e2e_enabled(), reason="Compose stack is not running")


def redis_stock(product: str) -> int:
    import subprocess

    out = subprocess.run(
        ["docker", "exec", "orderflow-redis-1", "redis-cli", "get", f"stock:{product}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return int(out.stdout.strip())


def pg_stock(product: str) -> int:
    with db("inventory_db") as conn:
        return conn.execute(
            "SELECT available FROM stock WHERE product_id = %s", (product,)
        ).fetchone()[0]


def payments(order_id: str) -> list[str]:
    with db("payments_db") as conn:
        rows = conn.execute(
            "SELECT status FROM payments WHERE order_id = %s ORDER BY created_at", (order_id,)
        ).fetchall()
    return [row[0] for row in rows]


def reservation(order_id: str) -> str:
    with db("inventory_db") as conn:
        return conn.execute(
            "SELECT status FROM reservations WHERE order_id = %s", (order_id,)
        ).fetchone()[0]


@pytest.fixture(autouse=True)
def default_settings():
    yield
    recreate("payment-service")  # back to failure rate 0 and a short delay
    recreate("order-service-1")


def test_paid_order_is_confirmed_and_its_stock_is_sold():
    keyboard = product_id("KB-001")
    order_id = place_order(keyboard, 1)
    assert wait_for_status(order_id, "CONFIRMED", "CANCELLED")["status"] == "CONFIRMED"
    assert payments(order_id) == ["SUCCEEDED"]
    wait_until(lambda: reservation(order_id) == "COMMITTED", 30, "reservation committed")


def test_declined_payment_cancels_and_returns_the_stock():
    recreate("payment-service", PAYMENT_FAILURE_RATE="1")
    lamp = product_id("LT-ED1")
    before = (pg_stock(lamp), redis_stock(lamp))
    order_id = place_order(lamp, 2)
    order = wait_for_status(order_id, "CANCELLED", "CONFIRMED")
    assert (order["status"], order["cancel_reason"]) == (
        "CANCELLED",
        "payment_failed:card_declined",
    )
    assert payments(order_id) == ["FAILED"]
    wait_until(lambda: (pg_stock(lamp), redis_stock(lamp)) == before, 30, "stock returned")


def test_duplicate_charge_request_charges_once():
    mouse = product_id("MS-001")
    order_id = place_order(mouse, 1)
    wait_for_status(order_id, "CONFIRMED")
    [charge] = [
        m
        for m in kafka_messages("orders.events", order_id)
        if json.loads(m["value"])["event_type"] == "ChargePaymentRequested"
    ]
    republish("orders.events", order_id, charge["value"], charge["headers"])
    import time

    time.sleep(5)
    assert payments(order_id) == ["SUCCEEDED"]


def test_slow_provider_times_out_and_cancels():
    recreate("payment-service", PAYMENT_DELAY_MS="5000")  # each call deadline is 2 seconds
    order_id = place_order(product_id("WC-HD1"), 1)
    order = wait_for_status(order_id, "CANCELLED", "CONFIRMED", seconds=90)
    assert order["cancel_reason"] == "payment_failed:provider_timeout"
    assert payments(order_id) == ["FAILED"]


def test_payment_after_the_order_timed_out_is_refunded():
    recreate("order-service-1", PAYMENT_TIMEOUT_SECONDS="3", TIMEOUT_CHECK_SECONDS="1")
    compose("stop", "payment-service")
    try:
        order_id = place_order(product_id("ST-LAP"), 1)
        order = wait_for_status(order_id, "CANCELLED", seconds=90)
        assert order["cancel_reason"] == "payment_timeout"
    finally:
        compose("start", "payment-service")
    # The charge request is still in Kafka: payment-service charges it, order-service
    # sees the order is cancelled and asks for a refund.
    wait_until(lambda: payments(order_id) == ["REFUNDED"], 90, "late payment refunded")
    assert wait_for_status(order_id, "CANCELLED")["status"] == "CANCELLED"
