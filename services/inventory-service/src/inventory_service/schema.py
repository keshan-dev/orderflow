"""Table definitions used by queries. The migrations in migrations/versions create them."""

from sqlalchemy import Column, DateTime, Integer, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

products = Table(
    "products",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("sku", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("price_cents", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True)),
)

stock = Table(
    "stock",
    metadata,
    Column("product_id", UUID(as_uuid=True), primary_key=True),
    Column("available", Integer, nullable=False),
    Column("updated_at", DateTime(timezone=True)),
)

reservations = Table(
    "reservations",
    metadata,
    Column("order_id", UUID(as_uuid=True), primary_key=True),
    Column("items", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
