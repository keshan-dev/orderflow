import json
import uuid

import pytest
from sqlalchemy import text

from orderflow_common import testing
from orderflow_common.connections import make_engine
from orderflow_common.events import Event, first_time, write_outbox


def test_envelope_has_every_field_and_round_trips():
    event = Event("StockReserved", uuid.uuid4(), {"lines": []})
    envelope = event.envelope()
    assert set(envelope) == {
        "event_id",
        "event_type",
        "order_id",
        "occurred_at",
        "version",
        "payload",
    }
    assert envelope["version"] == 1
    assert Event.from_envelope(json.loads(json.dumps(envelope))) == event


def test_malformed_envelope_raises():
    with pytest.raises((KeyError, ValueError)):
        Event.from_envelope({"event_type": "X", "order_id": "not-a-uuid"})


@pytest.fixture(scope="module")
def engine():
    with testing.postgres_container() as url:
        eng = make_engine(url)
        with eng.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE outbox (id uuid PRIMARY KEY, aggregatetype text NOT NULL,
                      aggregateid text NOT NULL, type text NOT NULL, payload jsonb NOT NULL,
                      traceparent text, created_at timestamptz NOT NULL DEFAULT now());
                    CREATE TABLE processed_events (event_id uuid PRIMARY KEY,
                      processed_at timestamptz NOT NULL DEFAULT now());
                    """
                )
            )
        yield eng
        eng.dispose()


def test_write_outbox_stores_the_envelope(engine):
    event = Event("OrderCreated", uuid.uuid4(), {"order": {"status": "PENDING"}})
    with engine.begin() as conn:
        write_outbox(conn, "orders", event)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM outbox WHERE id = :id"), {"id": event.event_id}
        ).one()
    assert (row.aggregatetype, row.aggregateid, row.type) == (
        "orders",
        str(event.order_id),
        "OrderCreated",
    )
    assert row.payload["event_id"] == str(event.event_id)


def test_first_time_is_true_once(engine):
    event_id = uuid.uuid4()
    with engine.begin() as conn:
        assert first_time(conn, event_id) is True
    with engine.begin() as conn:
        assert first_time(conn, event_id) is False


def test_rolled_back_work_is_not_marked_processed(engine):
    event_id = uuid.uuid4()
    with pytest.raises(RuntimeError), engine.begin() as conn:
        first_time(conn, event_id)
        raise RuntimeError("the work failed")
    with engine.begin() as conn:
        assert first_time(conn, event_id) is True
