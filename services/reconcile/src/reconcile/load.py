"""Read a snapshot of every service's data. Read-only: it never changes anything."""

import uuid
from datetime import UTC, datetime

import boto3
import redis
from botocore.config import Config
from sqlalchemy import Engine, text

from inventory_service.seed import CATALOG
from reconcile.checks import Order, Payment, Reservation, Snapshot

S3_CONFIG = Config(connect_timeout=3, read_timeout=10, retries={"max_attempts": 3})


def load_snapshot(
    orders_db: Engine,
    inventory_db: Engine,
    payments_db: Engine,
    cache: redis.Redis,
    s3_bucket: str,
    s3_endpoint_url: str | None,
) -> Snapshot:
    with orders_db.connect() as conn:
        orders = [
            Order(row.id, row.status, row.total_cents, row.updated_at)
            for row in conn.execute(text("SELECT id, status, total_cents, updated_at FROM orders"))
        ]
    with payments_db.connect() as conn:
        payments = [
            Payment(row.order_id, row.status, row.amount_cents)
            for row in conn.execute(text("SELECT order_id, status, amount_cents FROM payments"))
        ]
    with inventory_db.connect() as conn:
        reservations = [
            Reservation(
                row.order_id,
                row.status,
                {uuid.UUID(i["product_id"]): int(i["quantity"]) for i in row.items},
            )
            for row in conn.execute(text("SELECT order_id, status, items FROM reservations"))
        ]
        stock = {
            row.product_id: row.available
            for row in conn.execute(text("SELECT product_id, available FROM stock"))
        }
    redis_stock = {
        product_id: (int(value) if value is not None else None)
        for product_id, value in zip(
            stock, cache.mget([f"stock:{pid}" for pid in stock]) if stock else [], strict=True
        )
    }
    return Snapshot(
        orders=orders,
        payments=payments,
        reservations=reservations,
        stock=stock,
        initial_stock={item.id: item.stock for item in CATALOG},
        redis_stock=redis_stock,
        invoice_order_ids=_invoice_order_ids(s3_bucket, s3_endpoint_url),
        now=datetime.now(UTC),
    )


def _invoice_order_ids(bucket: str, endpoint_url: str | None) -> set[uuid.UUID]:
    s3 = boto3.client("s3", endpoint_url=endpoint_url, config=S3_CONFIG, region_name="us-east-1")
    ids: set[uuid.UUID] = set()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="invoices/"):
        for obj in page.get("Contents", []):
            name = obj["Key"].rsplit("/", 1)[-1].removesuffix(".pdf")
            try:
                ids.add(uuid.UUID(name))
            except ValueError:
                continue
    return ids
