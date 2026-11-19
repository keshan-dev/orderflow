"""Initial inventory tables, outbox and processed_events.

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


def _timestamp(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("sku", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("price_cents", sa.Integer, nullable=False),
        _timestamp("created_at"),
        sa.CheckConstraint("price_cents >= 0", name="price_not_negative"),
    )
    op.create_table(
        "stock",
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id"), primary_key=True),
        sa.Column("available", sa.Integer, nullable=False),
        _timestamp("updated_at"),
        # The database itself refuses negative stock, even if the code has a bug.
        sa.CheckConstraint("available >= 0", name="available_not_negative"),
    )
    op.create_table(
        "reservations",
        sa.Column("order_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("items", JSONB, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint("status IN ('HELD', 'RELEASED', 'COMMITTED')", name="status_known"),
    )
    op.create_index(
        "reservations_held_expiry",
        "reservations",
        ["expires_at"],
        postgresql_where=sa.text("status = 'HELD'"),
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
    # Debezium reads only the outbox table through this publication.
    op.execute("CREATE PUBLICATION dbz_outbox FOR TABLE outbox")


def downgrade() -> None:
    op.execute("DROP PUBLICATION IF EXISTS dbz_outbox")
    op.drop_table("processed_events")
    op.drop_table("outbox")
    op.drop_index("reservations_held_expiry", table_name="reservations")
    op.drop_table("reservations")
    op.drop_table("stock")
    op.drop_table("products")
