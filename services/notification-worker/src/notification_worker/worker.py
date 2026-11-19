"""Consume jobs from RabbitMQ with manual acknowledgements.

- prefetch: RabbitMQ sends at most this many unacknowledged jobs at a time.
- success: ack.
- temporary failure: retried a few times in this process (tenacity, limited attempts).
- gave up, or a permanent problem (bad JSON, PermanentJobError): nack with requeue=False.
  RabbitMQ then moves the job to <queue>.dlq through the dead letter exchange.
"""

import json
import logging
import time
from collections.abc import Callable
from typing import Any

import pika
from pika.exceptions import AMQPError
from tenacity import Retrying, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from orderflow_common.heartbeat import beat
from orderflow_common.logging import log_context
from orderflow_common.rabbitmq import JOB_QUEUES, connection_parameters, declare_topology

log = logging.getLogger(__name__)

JobHandler = Callable[[dict[str, Any]], None]

MAX_RECONNECT_WAIT_SECONDS = 30


class PermanentJobError(Exception):
    """Retrying will never help (for example a malformed job). Send it to the DLQ now."""


class Worker:
    def __init__(
        self,
        rabbitmq_url: str,
        handlers: dict[str, JobHandler],
        *,
        prefetch: int = 10,
        attempts: int = 3,
        heartbeat_file: str | None = None,
    ) -> None:
        unknown = set(handlers) - set(JOB_QUEUES)
        if unknown:
            raise ValueError(f"no such job queues: {sorted(unknown)}")
        self._params = connection_parameters(rabbitmq_url)
        self._handlers = handlers
        self._prefetch = prefetch
        self._attempts = attempts
        self._heartbeat_file = heartbeat_file
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True

    def run(self) -> None:
        """Consume until stop() is called. Reconnects after connection errors."""
        wait = 1.0
        while not self._stopping:
            try:
                self._consume()
                wait = 1.0
            except AMQPError:
                log.error("rabbitmq connection lost; reconnecting", extra={"in_seconds": wait})
                time.sleep(wait)
                wait = min(wait * 2, MAX_RECONNECT_WAIT_SECONDS)

    def _consume(self) -> None:
        connection = pika.BlockingConnection(self._params)
        try:
            channel = connection.channel()
            declare_topology(channel)
            channel.basic_qos(prefetch_count=self._prefetch)
            for queue in self._handlers:
                channel.basic_consume(queue, self._on_message)
            log.info("worker consuming", extra={"queues": list(self._handlers)})
            while not self._stopping:
                connection.process_data_events(time_limit=1)
                self._beat()
        finally:
            if connection.is_open:
                connection.close()

    def _on_message(self, channel, method, properties, body: bytes) -> None:
        queue = method.routing_key
        try:
            job = json.loads(body)
            job_id = str(job["job_id"])
        except (json.JSONDecodeError, KeyError, TypeError):
            log.error("malformed job; sending it to the dead letter queue", extra={"queue": queue})
            channel.basic_nack(method.delivery_tag, requeue=False)
            return

        with log_context(job_id=job_id, order_id=job.get("order_id"), queue=queue):
            try:
                self._run_with_retries(self._handlers[queue], job)
            except Exception:
                log.error("job failed; sending it to the dead letter queue", exc_info=True)
                channel.basic_nack(method.delivery_tag, requeue=False)
                return
            channel.basic_ack(method.delivery_tag)
            log.info("job done")

    def _run_with_retries(self, handler: JobHandler, job: dict[str, Any]) -> None:
        for attempt in Retrying(
            stop=stop_after_attempt(self._attempts),
            wait=wait_exponential(multiplier=0.5, max=5),
            retry=retry_if_not_exception_type(PermanentJobError),
            reraise=True,
        ):
            with attempt:
                number = attempt.retry_state.attempt_number
                if number > 1:
                    log.warning("retrying job", extra={"attempt": number})
                handler(job)

    def _beat(self) -> None:
        if self._heartbeat_file is not None:
            beat(self._heartbeat_file)
