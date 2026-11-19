"""Retry and dead letter topics for Kafka consumers.

When a handler keeps failing, the message must not block its partition forever, and it must
not be lost:
- temporary failure: publish it to <topic>.retry with the attempt number and a time
  (next_try_at) before which it must not be tried again. A retry consumer picks it up.
- permanent failure (bad JSON, PermanentError) or too many attempts: publish it to
  <topic>.dlq for a person to look at, and replay it later after a fix.

Several consumer groups read the same topic (orders.events has 4), so every retry and
dead letter message carries the consumer group that failed it. Other groups skip it.
The original offset is committed only after the broker confirmed the new message.
"""

import time
from dataclasses import dataclass

from confluent_kafka import Message, Producer

RETRY_SUFFIX = ".retry"
DLQ_SUFFIX = ".dlq"
MAX_RETRY_ATTEMPTS = 5
MAX_ERROR_LENGTH = 500

H_ORIGINAL_TOPIC = "x-original-topic"
H_GROUP = "x-consumer-group"
H_ATTEMPT = "x-attempt"
H_ERROR = "x-error"
H_NEXT_TRY_AT = "x-next-try-at-ms"


class DeliveryError(Exception):
    """The broker did not confirm the retry or dead letter message."""


def retry_delay_seconds(attempt: int) -> int:
    """2, 4, 8, 16, 32 seconds, capped at 60."""
    return min(2**attempt, 60)


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class RetryInfo:
    original_topic: str
    group: str
    attempt: int
    next_try_at_ms: int


def retry_info(message: Message) -> RetryInfo | None:
    headers = {key: value.decode() for key, value in (message.headers() or []) if value is not None}
    if H_GROUP not in headers:
        return None
    return RetryInfo(
        original_topic=headers.get(H_ORIGINAL_TOPIC, message.topic().removesuffix(RETRY_SUFFIX)),
        group=headers[H_GROUP],
        attempt=int(headers.get(H_ATTEMPT, "0")),
        next_try_at_ms=int(headers.get(H_NEXT_TRY_AT, "0")),
    )


class DeadLetterPublisher:
    def __init__(self, bootstrap_servers: str) -> None:
        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "acks": "all",
                "enable.idempotence": True,
                "message.timeout.ms": 10000,
            }
        )

    def to_retry(
        self, original_topic: str, message: Message, group: str, attempt: int, error: str
    ) -> None:
        due = now_ms() + retry_delay_seconds(attempt) * 1000
        self._send(
            original_topic + RETRY_SUFFIX, original_topic, message, group, attempt, error, due
        )

    def to_dlq(
        self, original_topic: str, message: Message, group: str, attempt: int, error: str
    ) -> None:
        self._send(original_topic + DLQ_SUFFIX, original_topic, message, group, attempt, error, 0)

    def replay(self, original_topic: str, message: Message, group: str) -> None:
        """Send a dead letter back through the retry topic, due now, starting again at 0."""
        self._send(
            original_topic + RETRY_SUFFIX, original_topic, message, group, 0, "replayed", now_ms()
        )

    def _send(
        self,
        topic: str,
        original_topic: str,
        message: Message,
        group: str,
        attempt: int,
        error: str,
        next_try_at_ms: int,
    ) -> None:
        failures: list[str] = []

        def on_delivery(err, _msg) -> None:
            if err is not None:
                failures.append(str(err))

        headers = [
            (H_ORIGINAL_TOPIC, original_topic.encode()),
            (H_GROUP, group.encode()),
            (H_ATTEMPT, str(attempt).encode()),
            (H_ERROR, error[:MAX_ERROR_LENGTH].encode()),
            (H_NEXT_TRY_AT, str(next_try_at_ms).encode()),
        ]
        self._producer.produce(
            topic,
            key=message.key(),
            value=message.value(),
            headers=headers,
            on_delivery=on_delivery,
        )
        if self._producer.flush(15) != 0 or failures:
            raise DeliveryError(f"could not publish to {topic}: {failures or 'timed out'}")
