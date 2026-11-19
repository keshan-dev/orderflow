"""Initial order tables, outbox and processed_events.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STATUSES = "'PENDING', 'STOCK_RESERVED', 'CONFIRMED', 'CANCELLED'"


def _timestamp(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        # Unique, so even if Redis loses the Idempotency-Key, Postgres blocks a duplicate order.
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        sa.Column("request_fingerprint", sa.Text, nullable=False),
        sa.Column("customer_email", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("cancel_reason", sa.Text, nullable=True),
        sa.Column("total_cents", sa.Integer, nullable=True),
        sa.Column("stock_reserved_at", sa.DateTime(timezone=True), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="status_known"),
    )
    # Used by the saga timeout task to find orders waiting too long for payment.
    op.create_index(
        "orders_waiting_for_payment",
        "orders",
        ["stock_reserved_at"],
        postgresql_where=sa.text("status = 'STOCK_RESERVED'"),
    )
    op.create_table(
        "order_items",
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), primary_key=True),
        sa.Column("product_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        # Filled from StockReserved: inventory-service owns product names and prices.
        sa.Column("name", sa.Text, nullable=True),
        sa.Column("unit_price_cents", sa.Integer, nullable=True),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
    )
    op.create_table(
        "outbox",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("aggregatetype", sa.Text, nullable=False),
        sa.Column("aggregateid", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("traceparent", sa.Text, nullable=True),
        _timestamp("created_at"),
    )
    op.create_table(
        "processed_events",
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
        _timestamp("processed_at"),
    )
    op.execute("CREATE PUBLICATION dbz_outbox FOR TABLE outbox")


def downgrade() -> None:
    op.execute("DROP PUBLICATION IF EXISTS dbz_outbox")
    op.drop_table("processed_events")
    op.drop_table("outbox")
    op.drop_table("order_items")
    op.drop_index("orders_waiting_for_payment", table_name="orders")
    op.drop_table("orders")
