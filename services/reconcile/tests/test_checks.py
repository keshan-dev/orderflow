import uuid
from datetime import UTC, datetime, timedelta

from reconcile.checks import Order, Payment, Reservation, Snapshot, run_all

NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)
LAMP = uuid.uuid4()


def snapshot(**changes) -> Snapshot:
    """A small, fully consistent world: 1 confirmed and 1 cancelled order."""
    paid, cancelled = uuid.UUID(int=1), uuid.UUID(int=2)
    base = {
        "orders": [
            Order(paid, "CONFIRMED", 1000, NOW),
            Order(cancelled, "CANCELLED", 1000, NOW),
        ],
        "payments": [
            Payment(paid, "SUCCEEDED", 1000),
            Payment(cancelled, "FAILED", 1000),
        ],
        "reservations": [
            Reservation(paid, "COMMITTED", {LAMP: 1}),
            Reservation(cancelled, "RELEASED", {LAMP: 1}),
        ],
        "stock": {LAMP: 9},
        "initial_stock": {LAMP: 10},
        "redis_stock": {LAMP: 9},
        "invoice_order_ids": {paid},
        "now": NOW,
    }
    return Snapshot(**{**base, **changes})


def failed(s: Snapshot) -> list[str]:
    return [r.name for r in run_all(s, timedelta(minutes=5)) if not r.ok]


def test_consistent_world_passes_every_check():
    assert failed(snapshot()) == []


def test_double_charge_is_found():
    s = snapshot()
    s.payments.append(Payment(uuid.UUID(int=1), "SUCCEEDED", 1000))
    assert "no order is charged twice" in failed(s)
    assert "confirmed orders are paid exactly once" in failed(s)


def test_cancelled_order_that_kept_the_money_is_found():
    s = snapshot(
        payments=[
            Payment(uuid.UUID(int=1), "SUCCEEDED", 1000),
            Payment(uuid.UUID(int=2), "SUCCEEDED", 1000),
        ]
    )
    assert "cancelled orders keep no money" in failed(s)


def test_refunded_cancelled_order_is_fine():
    s = snapshot(
        payments=[
            Payment(uuid.UUID(int=1), "SUCCEEDED", 1000),
            Payment(uuid.UUID(int=2), "REFUNDED", 1000),
        ]
    )
    assert failed(s) == []


def test_stuck_order_is_found():
    s = snapshot()
    s.orders.append(Order(uuid.uuid4(), "STOCK_RESERVED", None, NOW - timedelta(minutes=10)))
    assert failed(s) == ["no order is stuck"]


def test_lost_or_extra_stock_is_found():
    assert "stock adds up" in failed(snapshot(stock={LAMP: 10}, redis_stock={LAMP: 10}))
    assert failed(snapshot(redis_stock={LAMP: 8})) == ["redis stock matches postgres"]


def test_missing_invoice_is_found():
    assert failed(snapshot(invoice_order_ids=set())) == ["confirmed orders have an invoice"]


def test_wrong_amount_is_found():
    s = snapshot(
        payments=[
            Payment(uuid.UUID(int=1), "SUCCEEDED", 999),
            Payment(uuid.UUID(int=2), "FAILED", 1000),
        ]
    )
    assert failed(s) == ["confirmed orders are paid exactly once"]
