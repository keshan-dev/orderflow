"""Consume events from Kafka with manual offset commits.

The offset is committed only AFTER the handler finished, which means its database
transaction is committed. If the service crashes in between, Kafka delivers the message
again, and the processed_events check inside the handler skips it. Nothing is lost and
nothing is done twice.
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from confluent_kafka import Consumer, KafkaException, Message, TopicPartition
from tenacity import retry, stop_after_attempt, wait_exponential

from orderflow_common.events import Event
from orderflow_common.logging import log_context

log = logging.getLogger(__name__)

Handler = Callable[[Event], None]

# A poll older than this means the consumer loop is stuck.
STALE_POLL_SECONDS = 30.0


class PermanentError(Exception):
    """This message can never be processed, so retrying is pointless (for example bad JSON)."""


def consumer_config(bootstrap_servers: str, group_id: str) -> dict[str, Any]:
    return {
        "bootstrap.servers": bootstrap_servers,
        "group.id": group_id,
        "enable.auto.commit": False,  # we commit after the work is saved
        "auto.offset.reset": "earliest",
        "session.timeout.ms": 15000,
        "socket.timeout.ms": 10000,
        "partition.assignment.strategy": "cooperative-sticky",
    }


def parse_event(message: Message) -> Event:
    try:
        return Event.from_envelope(json.loads(message.value()))
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        raise PermanentError(f"not a valid event envelope: {exc}") from exc


class EventConsumer:
    """Runs 1 Kafka consumer in a background thread and calls handler(event) per message."""

    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        topics: list[str],
        handler: Handler,
        *,
        attempts: int = 3,
        max_backoff_seconds: float = 30.0,
    ) -> None:
        self._config = consumer_config(bootstrap_servers, group_id)
        self._group_id = group_id
        self._topics = topics
        self._handler = handler
        self._attempts = attempts
        self._max_backoff = max_backoff_seconds
        self._backoff: dict[tuple[str, int, int], float] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"consumer-{group_id}", daemon=True)
        self._last_poll = 0.0

    def start(self) -> None:
        self._last_poll = time.monotonic()  # healthy from the start, until polling stalls
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._thread.join(timeout)

    @property
    def healthy(self) -> bool:
        return self._thread.is_alive() and time.monotonic() - self._last_poll < STALE_POLL_SECONDS

    def _run(self) -> None:
        consumer = Consumer(self._config)
        consumer.subscribe(self._topics)
        log.info("consumer started", extra={"group": self._group_id, "topics": self._topics})
        try:
            while not self._stop.is_set():
                message = consumer.poll(1.0)
                self._last_poll = time.monotonic()
                if message is None:
                    continue
                if message.error():
                    log.warning("kafka poll error", extra={"error": str(message.error())})
                    continue
                self._handle(consumer, message)
        finally:
            consumer.close()
            log.info("consumer stopped", extra={"group": self._group_id})

    def _handle(self, consumer: Consumer, message: Message) -> None:
        where = {
            "topic": message.topic(),
            "partition": message.partition(),
            "offset": message.offset(),
        }
        if message.value() is None:
            self._commit(consumer, message)
            return
        try:
            event = parse_event(message)
        except PermanentError:
            # M8 sends these to the .dlq topic. Until then: log loudly and move on.
            log.error("skipping a message that is not a valid event", extra=where, exc_info=True)
            self._commit(consumer, message)
            return

        with log_context(event_id=str(event.event_id), order_id=str(event.order_id)):
            try:
                self._call_handler(event)
            except Exception:
                self._retry_later(consumer, message, where)
                return
            self._backoff.pop(_position(message), None)
            self._commit(consumer, message)

    def _call_handler(self, event: Event) -> None:
        """Short retries in memory for quick blips (for example a database reconnect)."""
        retrying = retry(
            stop=stop_after_attempt(self._attempts),
            wait=wait_exponential(multiplier=0.2, max=2),
            reraise=True,
        )
        retrying(self._handler)(event)

    def _retry_later(self, consumer: Consumer, message: Message, where: dict[str, Any]) -> None:
        """Wait longer each time, then read the same message again. It is never skipped."""
        position = _position(message)
        wait = self._backoff.get(position, 1.0)
        log.error(
            "handling failed; will read the message again",
            extra={**where, "retry_in_seconds": wait},
            exc_info=True,
        )
        self._backoff[position] = min(wait * 2, self._max_backoff)
        self._stop.wait(wait)
        consumer.seek(TopicPartition(message.topic(), message.partition(), message.offset()))

    @staticmethod
    def _commit(consumer: Consumer, message: Message) -> None:
        try:
            consumer.commit(message=message, asynchronous=False)
        except KafkaException:
            # The message may be delivered again; the handler's duplicate check makes that safe.
            log.warning("offset commit failed", exc_info=True)


def _position(message: Message) -> tuple[str, int, int]:
    return (message.topic(), message.partition(), message.offset())
