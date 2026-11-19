"""Consistency checks across services. Pure functions over a snapshot of the data.

Each check returns a CheckResult with the number of problems and a few examples, so a
person can start digging from a concrete order id.
"""

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

MAX_EXAMPLES = 5


@dataclass(frozen=True)
class Order:
    id: uuid.UUID
    status: str
    total_cents: int | None
    updated_at: datetime


@dataclass(frozen=True)
class Payment:
    order_id: uuid.UUID
    status: str
    amount_cents: int


@dataclass(frozen=True)
class Reservation:
    order_id: uuid.UUID
    status: str
    items: dict[uuid.UUID, int]  # product id -> quantity


@dataclass(frozen=True)
class Snapshot:
    orders: list[Order]
    payments: list[Payment]
    reservations: list[Reservation]
    stock: dict[uuid.UUID, int]  # Postgres available, per product
    initial_stock: dict[uuid.UUID, int]  # what the seed put in
    redis_stock: dict[uuid.UUID, int | None]
    invoice_order_ids: set[uuid.UUID]
    now: datetime


@dataclass
class CheckResult:
    name: str
    checked: int
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "checked": self.checked,
            "problems": len(self.problems),
            "examples": self.problems[:MAX_EXAMPLES],
        }


def _charges(payments: list[Payment]) -> dict[uuid.UUID, Counter]:
    by_order: dict[uuid.UUID, Counter] = defaultdict(Counter)
    for payment in payments:
        by_order[payment.order_id][payment.status] += 1
    return by_order


def confirmed_orders_are_paid_once(s: Snapshot) -> CheckResult:
    """Every CONFIRMED order has exactly 1 successful payment, for its total."""
    charges = _charges(s.payments)
    amounts = {p.order_id: p.amount_cents for p in s.payments if p.status == "SUCCEEDED"}
    confirmed = [o for o in s.orders if o.status == "CONFIRMED"]
    result = CheckResult("confirmed orders are paid exactly once", len(confirmed))
    for order in confirmed:
        succeeded = charges[order.id]["SUCCEEDED"]
        if succeeded != 1:
            result.problems.append(f"{order.id}: {succeeded} successful payments")
        elif amounts[order.id] != order.total_cents:
            result.problems.append(
                f"{order.id}: paid {amounts[order.id]}, total {order.total_cents}"
            )
    return result


def no_order_is_charged_twice(s: Snapshot) -> CheckResult:
    charges = _charges(s.payments)
    result = CheckResult("no order is charged twice", len(charges))
    for order_id, counts in charges.items():
        if counts["SUCCEEDED"] + counts["REFUNDED"] > 1:
            result.problems.append(f"{order_id}: {dict(counts)}")
    return result


def cancelled_orders_keep_no_money(s: Snapshot) -> CheckResult:
    """A CANCELLED order has no successful payment left (none, or it was refunded)."""
    charges = _charges(s.payments)
    cancelled = [o for o in s.orders if o.status == "CANCELLED"]
    result = CheckResult("cancelled orders keep no money", len(cancelled))
    for order in cancelled:
        if charges[order.id]["SUCCEEDED"]:
            result.problems.append(f"{order.id}: still has a successful payment")
    return result


def no_order_is_stuck(s: Snapshot, stuck_after: timedelta) -> CheckResult:
    waiting = [o for o in s.orders if o.status in ("PENDING", "STOCK_RESERVED")]
    result = CheckResult("no order is stuck", len(s.orders))
    for order in waiting:
        if s.now - order.updated_at > stuck_after:
            result.problems.append(
                f"{order.id}: {order.status} since {order.updated_at.isoformat()}"
            )
    return result


def reservations_match_orders(s: Snapshot) -> CheckResult:
    """Sold stock belongs to confirmed orders; cancelled orders hold no stock."""
    status = {o.id: o.status for o in s.orders}
    result = CheckResult("reservations match orders", len(s.reservations))
    for reservation in s.reservations:
        order_status = status.get(reservation.order_id)
        if reservation.status == "COMMITTED" and order_status != "CONFIRMED":
            result.problems.append(f"{reservation.order_id}: COMMITTED but order is {order_status}")
        if reservation.status == "HELD" and order_status == "CANCELLED":
            result.problems.append(f"{reservation.order_id}: HELD but order is CANCELLED")
        if order_status == "CONFIRMED" and reservation.status != "COMMITTED":
            result.problems.append(
                f"{reservation.order_id}: order CONFIRMED, stock {reservation.status}"
            )
    return result


def stock_adds_up(s: Snapshot) -> CheckResult:
    """For every product: available + held + sold == what the seed put in."""
    taken: Counter = Counter()
    for reservation in s.reservations:
        if reservation.status in ("HELD", "COMMITTED"):
            for product_id, quantity in reservation.items.items():
                taken[product_id] += quantity
    result = CheckResult("stock adds up", len(s.initial_stock))
    for product_id, initial in s.initial_stock.items():
        available = s.stock.get(product_id)
        if available is None or available + taken[product_id] != initial:
            result.problems.append(
                f"{product_id}: available {available} + taken {taken[product_id]} != {initial}"
            )
    return result


def redis_matches_postgres(s: Snapshot) -> CheckResult:
    result = CheckResult("redis stock matches postgres", len(s.stock))
    for product_id, available in s.stock.items():
        cached = s.redis_stock.get(product_id)
        if cached != available:
            result.problems.append(f"{product_id}: redis {cached}, postgres {available}")
    return result


def confirmed_orders_have_invoices(s: Snapshot) -> CheckResult:
    confirmed = [o for o in s.orders if o.status == "CONFIRMED"]
    result = CheckResult("confirmed orders have an invoice", len(confirmed))
    for order in confirmed:
        if order.id not in s.invoice_order_ids:
            result.problems.append(f"{order.id}: no invoice in S3")
    return result


def run_all(s: Snapshot, stuck_after: timedelta) -> list[CheckResult]:
    return [
        confirmed_orders_are_paid_once(s),
        no_order_is_charged_twice(s),
        cancelled_orders_keep_no_money(s),
        no_order_is_stuck(s, stuck_after),
        reservations_match_orders(s),
        stock_adds_up(s),
        redis_matches_postgres(s),
        confirmed_orders_have_invoices(s),
    ]
