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
    assert {"orders", "order_items", "outbox", "processed_events"} <= tables
    engine.dispose()


def test_idempotency_key_is_unique(engine):
    insert = text(
        "INSERT INTO orders (id, idempotency_key, request_fingerprint, customer_email, status)"
        " VALUES (:id, 'k-1', 'f', 'a@b.c', 'PENDING')"
    )
    with engine.begin() as conn:
        conn.execute(insert, {"id": uuid.uuid4()})
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert, {"id": uuid.uuid4()})
