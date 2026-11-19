"""Consume events from Kafka with manual offset commits.

The offset is committed only AFTER the handler finished, which means its database
transaction is committed. If the service crashes in between, Kafka delivers the message
again, and the processed_events check inside the handler skips it. Nothing is lost and
nothing is done twice.

When a handler keeps failing (see deadletter.py):
- a temporary failure goes to <topic>.retry and is tried again later by a second consumer
  thread (group "<group>.retry"), with a growing delay, up to MAX_RETRY_ATTEMPTS times;
- a permanent failure, or too many attempts, goes to <topic>.dlq.
So 1 bad message never blocks its partition. If even the retry or dead letter topic cannot
be written, the consumer falls back to reading the same message again later: it is never
skipped.
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from confluent_kafka import Consumer, KafkaException, Message, TopicPartition
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from orderflow_common.deadletter import (
    MAX_RETRY_ATTEMPTS,
    RETRY_SUFFIX,
    DeadLetterPublisher,
    DeliveryError,
    now_ms,
    retry_info,
)
from orderflow_common.events import Event
from orderflow_common.logging import log_context

log = logging.getLogger(__name__)

Handler = Callable[[Event], None]

# A poll older than this means the consumer loop is stuck.
STALE_POLL_SECONDS = 30.0
# The retry thread sleeps until a message is due, at most this long at a time.
MAX_RETRY_SLEEP_SECONDS = 5.0


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


def _where(message: Message) -> dict[str, Any]:
    return {"topic": message.topic(), "partition": message.partition(), "offset": message.offset()}


class _PollLoop:
    """1 Kafka consumer in 1 background thread."""

    def __init__(
        self, config: dict[str, Any], topics: list[str], on_message: Callable, stop: threading.Event
    ) -> None:
        self._config = config
        self._topics = topics
        self._on_message = on_message
        self._stop = stop
        self._thread = threading.Thread(
            target=self._run, name=f"consumer-{config['group.id']}", daemon=True
        )
        self.last_poll = 0.0

    def start(self) -> None:
        self.last_poll = time.monotonic()
        self._thread.start()

    def join(self, timeout: float) -> None:
        self._thread.join(timeout)

    @property
    def healthy(self) -> bool:
        return self._thread.is_alive() and time.monotonic() - self.last_poll < STALE_POLL_SECONDS

    def _run(self) -> None:
        consumer = Consumer(self._config)
        consumer.subscribe(self._topics)
        log.info(
            "consumer started", extra={"group": self._config["group.id"], "topics": self._topics}
        )
        try:
            while not self._stop.is_set():
                message = consumer.poll(1.0)
                self.last_poll = time.monotonic()
                if message is None:
                    continue
                if message.error():
                    log.warning("kafka poll error", extra={"error": str(message.error())})
                    continue
                self._on_message(consumer, message)
        finally:
            consumer.close()
            log.info("consumer stopped", extra={"group": self._config["group.id"]})


class EventConsumer:
    """Calls handler(event) for every message on `topics`, with retry and dead letter topics."""

    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        topics: list[str],
        handler: Handler,
        *,
        attempts: int = 3,
        max_backoff_seconds: float = 30.0,
        max_retry_attempts: int = MAX_RETRY_ATTEMPTS,
    ) -> None:
        self._group_id = group_id
        self._handler = handler
        self._attempts = attempts
        self._max_backoff = max_backoff_seconds
        self._max_retry_attempts = max_retry_attempts
        self._backoff: dict[tuple[str, int, int], float] = {}
        self._dead_letters = DeadLetterPublisher(bootstrap_servers)
        self._stop = threading.Event()
        self._main = _PollLoop(
            consumer_config(bootstrap_servers, group_id), topics, self._on_main, self._stop
        )
        self._retry = _PollLoop(
            consumer_config(bootstrap_servers, f"{group_id}{RETRY_SUFFIX}"),
            [topic + RETRY_SUFFIX for topic in topics],
            self._on_retry,
            self._stop,
        )

    def start(self) -> None:
        self._main.start()
        self._retry.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._main.join(timeout)
        self._retry.join(timeout)

    @property
    def healthy(self) -> bool:
        return self._main.healthy and self._retry.healthy

    def _on_main(self, consumer: Consumer, message: Message) -> None:
        self._process(consumer, message, message.topic(), attempt=0)

    def _on_retry(self, consumer: Consumer, message: Message) -> None:
        info = retry_info(message)
        if info is None or info.group != self._group_id:
            self._commit(consumer, message)  # another group's retry: not ours
            return
        # Wait until the message is due. Only this retry thread waits; the main topic
        # keeps flowing in the other thread.
        while not self._stop.is_set() and now_ms() < info.next_try_at_ms:
            self._retry.last_poll = time.monotonic()
            self._stop.wait(min(MAX_RETRY_SLEEP_SECONDS, (info.next_try_at_ms - now_ms()) / 1000))
        if self._stop.is_set():
            return  # not committed: read again after restart
        self._process(consumer, message, info.original_topic, attempt=info.attempt)

    def _process(self, consumer: Consumer, message: Message, topic: str, attempt: int) -> None:
        if message.value() is None:
            self._commit(consumer, message)
            return
        try:
            event = parse_event(message)
        except PermanentError as exc:
            log.error("not a valid event", extra=_where(message))
            self._to_dlq(consumer, message, topic, attempt, str(exc))
            return

        with log_context(event_id=str(event.event_id), order_id=str(event.order_id)):
            try:
                self._call_handler(event)
            except PermanentError as exc:
                log.error("event can never be handled", exc_info=True)
                self._to_dlq(consumer, message, topic, attempt, str(exc))
                return
            except Exception as exc:
                if attempt + 1 > self._max_retry_attempts:
                    log.error(
                        "event failed too many times", extra={"attempt": attempt}, exc_info=True
                    )
                    self._to_dlq(consumer, message, topic, attempt, repr(exc))
                else:
                    log.warning(
                        "event failed; will retry", extra={"attempt": attempt + 1}, exc_info=True
                    )
                    self._to_retry(consumer, message, topic, attempt + 1, repr(exc))
                return
            self._backoff.pop(_position(message), None)
            self._commit(consumer, message)

    def _to_dlq(
        self, consumer: Consumer, message: Message, topic: str, attempt: int, error: str
    ) -> None:
        def publish() -> None:
            self._dead_letters.to_dlq(topic, message, self._group_id, attempt, error)

        log.error("sending the message to the dead letter topic", extra={"topic": topic + ".dlq"})
        self._send(consumer, message, publish)

    def _to_retry(
        self, consumer: Consumer, message: Message, topic: str, attempt: int, error: str
    ) -> None:
        def publish() -> None:
            self._dead_letters.to_retry(topic, message, self._group_id, attempt, error)

        self._send(consumer, message, publish)

    def _send(self, consumer: Consumer, message: Message, publish: Callable[[], None]) -> None:
        """Publish to the retry or dead letter topic, then commit. If publishing fails, keep
        the message: read it again later instead of losing it."""
        try:
            publish()
        except (DeliveryError, KafkaException):
            self._read_again_later(consumer, message)
            return
        self._commit(consumer, message)

    def _call_handler(self, event: Event) -> None:
        """Short retries in memory for quick blips (for example a database reconnect)."""
        retrying = retry(
            stop=stop_after_attempt(self._attempts),
            wait=wait_exponential(multiplier=0.2, max=2),
            retry=retry_if_not_exception_type(PermanentError),
            reraise=True,
        )
        retrying(self._handler)(event)

    def _read_again_later(self, consumer: Consumer, message: Message) -> None:
        position = _position(message)
        wait = self._backoff.get(position, 1.0)
        log.error(
            "could not move the message aside; will read it again",
            extra={**_where(message), "retry_in_seconds": wait},
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


BatchHandler = Callable[[list[Event]], list[Event] | None]


class BatchEventConsumer:
    """Like EventConsumer, but hands the handler up to batch_size events at once.

    Used where 1 bulk write is much cheaper than many single writes (search-indexer).
    Offsets are committed only after the whole batch succeeded. If the batch fails, every
    partition is moved back to its first offset in the batch and the batch is read again,
    so the handler must be idempotent for the whole batch. Events the handler returns as
    permanently failed, and messages that are not valid events, go to <topic>.dlq.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        topics: list[str],
        handler: BatchHandler,
        *,
        batch_size: int = 200,
        attempts: int = 3,
        max_backoff_seconds: float = 30.0,
    ) -> None:
        self._config = consumer_config(bootstrap_servers, group_id)
        self._group_id = group_id
        self._topics = topics
        self._handler = handler
        self._batch_size = batch_size
        self._attempts = attempts
        self._max_backoff = max_backoff_seconds
        self._dead_letters = DeadLetterPublisher(bootstrap_servers)
        self._wait = 1.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"consumer-{group_id}", daemon=True)
        self._last_poll = 0.0

    def start(self) -> None:
        self._last_poll = time.monotonic()
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
        log.info("batch consumer started", extra={"group": self._group_id, "topics": self._topics})
        try:
            while not self._stop.is_set():
                messages = consumer.consume(num_messages=self._batch_size, timeout=1.0)
                self._last_poll = time.monotonic()
                if messages:
                    self._handle_batch(consumer, messages)
        finally:
            consumer.close()
            log.info("batch consumer stopped", extra={"group": self._group_id})

    def _handle_batch(self, consumer: Consumer, messages: list[Message]) -> None:
        events: list[Event] = []
        by_event: dict[str, Message] = {}
        malformed: list[tuple[Message, str]] = []
        first_offsets: dict[tuple[str, int], int] = {}
        for message in messages:
            if message.error():
                log.warning("kafka consume error", extra={"error": str(message.error())})
                continue
            first_offsets.setdefault((message.topic(), message.partition()), message.offset())
            if message.value() is None:
                continue
            try:
                event = parse_event(message)
            except PermanentError as exc:
                malformed.append((message, str(exc)))
                continue
            events.append(event)
            by_event[str(event.event_id)] = message

        try:
            failed = self._run_handler(events) if events else []
            for message, error in malformed:
                self._dead_letters.to_dlq(message.topic(), message, self._group_id, 0, error)
            for event in failed:
                message = by_event[str(event.event_id)]
                self._dead_letters.to_dlq(
                    message.topic(), message, self._group_id, 0, "rejected by handler"
                )
        except Exception:
            log.error(
                "batch failed; will read it again",
                extra={"events": len(events), "retry_in_seconds": self._wait},
                exc_info=True,
            )
            self._stop.wait(self._wait)
            self._wait = min(self._wait * 2, self._max_backoff)
            for (topic, partition), offset in first_offsets.items():
                consumer.seek(TopicPartition(topic, partition, offset))
            return

        if malformed or failed:
            log.error(
                "messages sent to the dead letter topic",
                extra={"malformed": len(malformed), "rejected": len(failed)},
            )
        self._wait = 1.0
        try:
            consumer.commit(asynchronous=False)
        except KafkaException:
            log.warning("offset commit failed", exc_info=True)

    def _run_handler(self, events: list[Event]) -> list[Event]:
        retrying = retry(
            stop=stop_after_attempt(self._attempts),
            wait=wait_exponential(multiplier=0.2, max=2),
            reraise=True,
        )
        return retrying(self._handler)(events) or []
