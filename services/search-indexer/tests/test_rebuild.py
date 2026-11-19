"""Rebuild from Kafka against the Compose broker and OpenSearch, with throwaway names."""

import json
import pathlib
import socket
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

from orderflow_common.events import Event
from search_indexer.indexer import make_client
from search_indexer.rebuild import rebuild

MAPPING = (
    pathlib.Path(__file__).resolve().parents[3] / "deploy/compose/opensearch/orders-mapping.json"
)
KAFKA = "localhost:29092"


def up(port: int) -> bool:
    try:
        with socket.create_connection(("localhost", port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not (up(9200) and up(29092)), reason="Compose stack is down")


def snapshot(order_id: str, status: str) -> dict:
    now = "2026-11-19T10:00:00+00:00"
    return {
        "order_id": order_id,
        "status": status,
        "customer_email": "a@b.co",
        "items": [{"product_id": "p", "name": "Lamp", "quantity": 1}],
        "created_at": now,
        "updated_at": now,
    }


def test_rebuild_fills_a_new_index_from_kafka_and_moves_the_alias():
    suffix = uuid.uuid4().hex[:8]
    topic, alias, old = f"test.rebuild.{suffix}", f"test-alias-{suffix}", f"test-old-{suffix}"
    new = f"test-new-{suffix}"
    admin = AdminClient({"bootstrap.servers": KAFKA})
    admin.create_topics([NewTopic(topic, num_partitions=2, replication_factor=1)])[topic].result(10)
    client = make_client("http://localhost:9200")
    client.indices.create(index=old, body=json.loads(MAPPING.read_text()))
    client.indices.put_alias(index=old, name=alias)
    try:
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        start = datetime(2026, 11, 19, 10, tzinfo=UTC)
        events = [
            Event(
                "OrderCreated", uuid.UUID(a), {"order": snapshot(a, "PENDING")}, occurred_at=start
            ),
            Event(
                "OrderCreated", uuid.UUID(b), {"order": snapshot(b, "PENDING")}, occurred_at=start
            ),
            Event(
                "OrderConfirmed",
                uuid.UUID(a),
                {"order": snapshot(a, "CONFIRMED")},
                occurred_at=start + timedelta(seconds=5),
            ),
        ]
        producer = Producer({"bootstrap.servers": KAFKA, "message.timeout.ms": 10000})
        for event in events:
            producer.produce(topic, key=str(event.order_id), value=json.dumps(event.envelope()))
        assert producer.flush(10) == 0

        result = rebuild(client, KAFKA, new, alias=alias, topic=topic)

        assert result["documents"] == 2
        assert list(client.indices.get_alias(name=alias)) == [new]
        assert client.get(index=new, id=a)["_source"]["status"] == "CONFIRMED"
    finally:
        admin.delete_topics([topic])[topic].result(10)
        for index in (old, new):
            if client.indices.exists(index=index):
                client.indices.delete(index=index)
