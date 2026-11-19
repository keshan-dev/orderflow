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
    """A throwaway topic plus its .retry and .dlq topics, like the real ones."""
    name = f"test.consumer.{uuid.uuid4().hex[:8]}"
    names = [name, f"{name}.retry", f"{name}.dlq"]
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP})
    created = admin.create_topics(
        [NewTopic(n, num_partitions=1, replication_factor=1) for n in names]
    )
    for future in created.values():
        future.result(10)
    yield name
    for future in admin.delete_topics(names).values():
        future.result(10)


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


def read_all(topic: str) -> list:
    """Every message on a topic, read from the start with a throwaway group."""
    from confluent_kafka import Consumer

    consumer = Consumer(
        {
            "bootstrap.servers": BOOTSTRAP,
            "group.id": f"r-{uuid.uuid4()}",
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([topic])
    messages, idle = [], 0
    while idle < 5:
        message = consumer.poll(1.0)
        if message is None or message.error():
            idle += 1
            continue
        messages.append(message)
    consumer.close()
    return messages


def headers_of(message) -> dict[str, str]:
    return {key: value.decode() for key, value in message.headers() or []}


def test_malformed_message_goes_to_the_dlq_and_does_not_block(topic):
    seen: list[str] = []
    group = f"g-{uuid.uuid4().hex[:6]}"
    produce(topic, b"not json", event_bytes("Good"))
    consumer = run(topic, group, lambda e: seen.append(e.event_type))
    wait_for(lambda: seen == ["Good"])
    assert consumer.healthy
    consumer.stop()
    [dead] = read_all(f"{topic}.dlq")
    assert dead.value() == b"not json"
    assert headers_of(dead)["x-consumer-group"] == group


def test_temporary_failure_is_retried_from_the_retry_topic(topic):
    calls: list[int] = []

    def fails_3_times_then_works(event: Event) -> None:
        calls.append(1)
        if len(calls) <= 3:  # the 3 quick in-memory attempts all fail
            raise ConnectionError("database down")

    produce(topic, event_bytes("Order"))
    consumer = run(topic, f"g-{uuid.uuid4().hex[:6]}", fails_3_times_then_works)
    wait_for(lambda: len(calls) == 4, seconds=30)  # 4th call comes from the retry topic
    consumer.stop()
    [retried] = read_all(f"{topic}.retry")
    assert headers_of(retried)["x-attempt"] == "1"
    assert read_all(f"{topic}.dlq") == []


def test_event_that_keeps_failing_ends_in_the_dlq(topic):
    from orderflow_common.kafka import EventConsumer

    def always_fails(event: Event) -> None:
        raise ConnectionError("database down")

    produce(topic, event_bytes("Order"))
    consumer = EventConsumer(
        BOOTSTRAP, f"g-{uuid.uuid4().hex[:6]}", [topic], always_fails, max_retry_attempts=1
    )
    consumer.start()
    wait_for(lambda: len(read_all(f"{topic}.dlq")) == 1, seconds=40)
    consumer.stop()
    [dead] = read_all(f"{topic}.dlq")
    assert headers_of(dead)["x-attempt"] == "1"


def test_retry_messages_of_another_group_are_ignored(topic):
    from orderflow_common.deadletter import DeadLetterPublisher

    seen: list[str] = []
    produce(topic, event_bytes("Mine"))
    first = read_all(topic)[0]
    DeadLetterPublisher(BOOTSTRAP).to_retry(topic, first, "some-other-group", 1, "boom")

    consumer = run(topic, f"g-{uuid.uuid4().hex[:6]}", lambda e: seen.append(e.event_type))
    wait_for(lambda: seen == ["Mine"])
    time.sleep(6)  # the other group's retry is due after 2 seconds
    consumer.stop()
    assert seen == ["Mine"]


def test_batch_consumer_gets_many_events_at_once_and_retries_failed_batches(topic):
    from orderflow_common.kafka import BatchEventConsumer

    batches: list[list[str]] = []
    failures = {"left": 4}  # more than the 3 quick attempts, so the batch is read again

    def handler(events):
        if failures["left"] > 0:
            failures["left"] -= 1
            raise ConnectionError("opensearch down")
        batches.append([e.event_type for e in events])

    produce(topic, *(event_bytes(f"E{i}") for i in range(5)))
    group = f"g-{uuid.uuid4().hex[:6]}"
    consumer = BatchEventConsumer(BOOTSTRAP, group, [topic], handler, max_backoff_seconds=1.0)
    consumer.start()
    wait_for(lambda: sum(len(b) for b in batches) >= 5)
    consumer.stop()
    assert [t for b in batches for t in b] == [f"E{i}" for i in range(5)]

    # Committed: a new consumer in the same group gets nothing old.
    again: list[str] = []
    produce(topic, event_bytes("NEW"))
    consumer = BatchEventConsumer(
        BOOTSTRAP, group, [topic], lambda evs: again.extend(e.event_type for e in evs)
    )
    consumer.start()
    wait_for(lambda: again == ["NEW"])
    consumer.stop()


def test_replay_sends_a_groups_dead_letters_back_through_the_retry_topic(topic):
    from orderflow_common.deadletter import DeadLetterPublisher
    from orderflow_common.replay_kafka_dlq import replay

    produce(topic, event_bytes("A"), event_bytes("B"))
    first, second = read_all(topic)
    publisher = DeadLetterPublisher(BOOTSTRAP)
    publisher.to_dlq(topic, first, "group-x", 5, "boom")
    publisher.to_dlq(topic, second, "group-y", 5, "boom")

    assert replay(BOOTSTRAP, topic, "group-x") == 1
    assert replay(BOOTSTRAP, topic, "group-x") == 0  # replayed once only
    [retried] = read_all(f"{topic}.retry")
    assert headers_of(retried)["x-consumer-group"] == "group-x"
    assert headers_of(retried)["x-attempt"] == "0"
    assert replay(BOOTSTRAP, topic, "group-y") == 1  # not skipped by group-x's run
