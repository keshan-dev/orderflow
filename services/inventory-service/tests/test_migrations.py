import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from conftest import run_migrations
from orderflow_common.connections import make_engine


def test_migrations_go_down_and_up_again(database_url):
    run_migrations(database_url, "base", downgrade=True)
    run_migrations(database_url)
    engine = make_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert {"products", "stock", "reservations", "outbox", "processed_events"} <= tables
    with engine.connect() as conn:
        published = (
            conn.execute(
                text("SELECT tablename FROM pg_publication_tables WHERE pubname = 'dbz_outbox'")
            )
            .scalars()
            .all()
        )
    assert published == ["outbox"]
    engine.dispose()


def test_stock_can_never_go_negative(engine):
    pid = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO products (id, sku, name, price_cents) VALUES (:id, 'S1', 'x', 100)"),
            {"id": pid},
        )
        conn.execute(text("INSERT INTO stock (product_id, available) VALUES (:id, 1)"), {"id": pid})
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text("UPDATE stock SET available = available - 2 WHERE product_id = :id"), {"id": pid}
        )
