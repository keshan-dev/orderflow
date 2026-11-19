"""Integration tests against the local Compose Kafka (localhost:29092).

Kafka needs a lot of memory, so these tests reuse the Compose broker instead of starting
another one. They are skipped when that broker is not running.
"""

import json
import socket
import threading
import time
import uuid

import pytest
from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

from orderflow_common.events import Event
from orderflow_common.kafka import EventConsumer

BOOTSTRAP = "localhost:29092"


def kafka_running() -> bool:
    try:
        with socket.create_connection(("localhost", 29092), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not kafka_running(), reason="Compose Kafka is not running")


@pytest.fixture
def topic():
    name = f"test.consumer.{uuid.uuid4().hex[:8]}"
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP})
    admin.create_topics([NewTopic(name, num_partitions=1, replication_factor=1)])[name].result(10)
    yield name
    admin.delete_topics([name])[name].result(10)


def produce(topic: str, *values: bytes) -> None:
    producer = Producer({"bootstrap.servers": BOOTSTRAP, "message.timeout.ms": 10000})
    for value in values:
        producer.produce(topic, value)
    assert producer.flush(10) == 0


def event_bytes(event_type: str = "Ping") -> bytes:
    return json.dumps(Event(event_type, uuid.uuid4(), {}).envelope()).encode()


def wait_for(condition, seconds: float = 20.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.2)
    raise AssertionError("condition not met in time")


def run(topic: str, group: str, handler) -> EventConsumer:
    consumer = EventConsumer(BOOTSTRAP, group, [topic], handler, max_backoff_seconds=1.0)
    consumer.start()
    return consumer


def test_each_event_is_handled_and_committed(topic):
    seen: list[str] = []
    group = f"g-{uuid.uuid4().hex[:6]}"
    produce(topic, event_bytes("A"), event_bytes("B"))
    consumer = run(topic, group, lambda e: seen.append(e.event_type))
    wait_for(lambda: seen == ["A", "B"])
    consumer.stop()

    # A new consumer in the same group starts after the committed offsets: nothing again.
    again: list[str] = []
    produce(topic, event_bytes("C"))
    consumer = run(topic, group, lambda e: again.append(e.event_type))
    wait_for(lambda: again == ["C"])
    consumer.stop()


def test_failing_handler_is_retried_until_it_works(topic):
    calls: list[int] = []
    lock = threading.Lock()

    def flaky(event: Event) -> None:
        with lock:
            calls.append(1)
            if len(calls) < 5:  # fails the 3 in-memory attempts, then once more
                raise ConnectionError("database down")

    produce(topic, event_bytes())
    consumer = run(topic, f"g-{uuid.uuid4().hex[:6]}", flaky)
    wait_for(lambda: len(calls) >= 5)
    consumer.stop()
    assert len(calls) == 5


def test_malformed_message_is_skipped(topic):
    seen: list[str] = []
    produce(topic, b"not json", event_bytes("Good"))
    consumer = run(topic, f"g-{uuid.uuid4().hex[:6]}", lambda e: seen.append(e.event_type))
    wait_for(lambda: seen == ["Good"])
    assert consumer.healthy
    consumer.stop()
