"""Uses the Compose OpenSearch (localhost:9200) with a throwaway index; skips when it is down."""

import json
import pathlib
import socket
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from orderflow_common.events import Event
from search_indexer.documents import to_document
from search_indexer.indexer import OrderIndexer, make_client

MAPPING = (
    pathlib.Path(__file__).resolve().parents[3] / "deploy/compose/opensearch/orders-mapping.json"
)


def opensearch_running() -> bool:
    try:
        with socket.create_connection(("localhost", 9200), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not opensearch_running(), reason="Compose OpenSearch is down")


@pytest.fixture
def index():
    client = make_client("http://localhost:9200")
    name = f"test-orders-{uuid.uuid4().hex[:8]}"
    client.indices.create(index=name, body=json.loads(MAPPING.read_text()))
    yield client, name
    client.indices.delete(index=name)


def order(status: str, order_id: str, total=None) -> dict:
    now = "2026-11-19T10:00:00+00:00"
    snapshot = {
        "order_id": order_id,
        "status": status,
        "customer_email": "buyer@example.com",
        "items": [{"product_id": "p1", "name": "Desk Lamp", "quantity": 1}],
        "created_at": now,
        "updated_at": now,
    }
    if total is not None:
        snapshot["total_cents"] = total
    return snapshot


def event(event_type: str, snapshot: dict, seconds: int) -> Event:
    at = datetime(2026, 11, 19, 10, 0, tzinfo=UTC) + timedelta(seconds=seconds)
    return Event(event_type, uuid.UUID(snapshot["order_id"]), {"order": snapshot}, occurred_at=at)


def stored(client, name, order_id):
    client.indices.refresh(index=name)
    return client.get(index=name, id=order_id)["_source"]


def test_document_keeps_only_present_fields():
    document = to_document(order("PENDING", str(uuid.uuid4())))
    assert "total" not in document and "cancel_reason" not in document
    assert document["product_names"] == ["Desk Lamp"]


def test_events_upsert_1_document_per_order(index):
    client, name = index
    order_id = str(uuid.uuid4())
    indexer = OrderIndexer(client, name)
    indexer.index_events(
        [
            event("OrderCreated", order("PENDING", order_id), 0),
            event("OrderConfirmed", order("CONFIRMED", order_id, 7999), 5),
        ]
    )
    document = stored(client, name, order_id)
    assert (document["status"], document["total"]) == ("CONFIRMED", 79.99)


def test_older_or_repeated_event_never_overwrites_newer_data(index):
    client, name = index
    order_id = str(uuid.uuid4())
    indexer = OrderIndexer(client, name)
    confirmed = event("OrderConfirmed", order("CONFIRMED", order_id, 100), 10)
    indexer.index_events([confirmed])
    indexer.index_events([event("OrderCreated", order("PENDING", order_id), 0)])  # late
    indexer.index_events([confirmed])  # repeated
    assert stored(client, name, order_id)["status"] == "CONFIRMED"


def test_search_by_product_name(index):
    client, name = index
    order_id = str(uuid.uuid4())
    OrderIndexer(client, name).index_events([event("OrderCreated", order("PENDING", order_id), 0)])
    client.indices.refresh(index=name)
    hits = client.search(index=name, body={"query": {"match": {"product_names": "lamp"}}})
    assert [h["_id"] for h in hits["hits"]["hits"]] == [order_id]
