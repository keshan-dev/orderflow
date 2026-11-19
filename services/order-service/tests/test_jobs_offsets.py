"""The jobs consumer must not commit its Kafka offset until both jobs are stored.

Uses the Compose Kafka broker with a throwaway topic and group, and skips when it is down.
"""

import json
import socket
import threading
import time
import uuid

import pytest
from confluent_kafka import Consumer, Producer, TopicPartition
from confluent_kafka.admin import AdminClient, NewTopic

from order_service.job_events import JobsFromEvents
from order_service.jobs import Job
from orderflow_common.events import Event
from orderflow_common.kafka import EventConsumer

BOOTSTRAP = "127.0.0.1:29092"


def kafka_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 29092), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not kafka_running(), reason="Compose Kafka is not running")


class SwitchablePublisher:
    """Fails until `working` is set, like RabbitMQ being down and then coming back."""

    def __init__(self) -> None:
        self.working = threading.Event()
        self.published: list[Job] = []

    def publish(self, job: Job) -> None:
        if not self.working.is_set():
            raise ConnectionError("rabbitmq is down")
        self.published.append(job)

    def close(self) -> None:
        pass


def committed_offset(topic: str, group: str) -> int:
    probe = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": group})
    [partition] = probe.committed([TopicPartition(topic, 0)], timeout=10)
    probe.close()
    return partition.offset


def test_offset_is_committed_only_after_the_jobs_are_stored():
    topic, group = f"test.jobs.{uuid.uuid4().hex[:8]}", f"g-{uuid.uuid4().hex[:8]}"
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP})
    admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])[topic].result(10)
    try:
        event = Event("OrderConfirmed", uuid.uuid4(), {"order": {"customer_email": "a@b.co"}})
        producer = Producer({"bootstrap.servers": BOOTSTRAP, "message.timeout.ms": 10000})
        producer.produce(topic, json.dumps(event.envelope()).encode())
        assert producer.flush(10) == 0

        publisher = SwitchablePublisher()
        consumer = EventConsumer(
            BOOTSTRAP, group, [topic], JobsFromEvents(publisher), max_backoff_seconds=1.0
        )
        consumer.start()
        time.sleep(6)  # several failed attempts
        assert committed_offset(topic, group) < 0, "offset committed while RabbitMQ was down"

        publisher.working.set()
        deadline = time.monotonic() + 20
        while committed_offset(topic, group) != 1 and time.monotonic() < deadline:
            time.sleep(0.5)
        consumer.stop()
        assert committed_offset(topic, group) == 1
        assert len(publisher.published) == 2
    finally:
        admin.delete_topics([topic])[topic].result(10)
