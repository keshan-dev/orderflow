"""Table definitions used by queries. The migrations in migrations/versions create them."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import UUID

metadata = MetaData()

orders = Table(
    "orders",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("idempotency_key", Text, nullable=False),
    Column("request_fingerprint", Text, nullable=False),
    Column("customer_email", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("cancel_reason", Text),
    Column("total_cents", Integer),
    Column("stock_reserved_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

order_items = Table(
    "order_items",
    metadata,
    Column("order_id", UUID(as_uuid=True), ForeignKey("orders.id"), primary_key=True),
    Column("product_id", UUID(as_uuid=True), primary_key=True),
    Column("quantity", Integer, nullable=False),
    Column("name", Text),
    Column("unit_price_cents", Integer),
)
