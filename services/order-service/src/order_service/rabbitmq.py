"""Publish jobs to RabbitMQ with publisher confirms.

With confirms on, basic_publish returns only after RabbitMQ has stored the message, and
raises if it could not be stored or routed. Then the caller does not commit its Kafka
offset, and the job is published again later.
"""

import json
import logging

import pika
from pika.exceptions import AMQPError

from order_service.jobs import Job
from orderflow_common.rabbitmq import JOBS_EXCHANGE, connection_parameters, declare_topology

log = logging.getLogger(__name__)


class RabbitMQJobPublisher:
    """Not thread-safe: use it from 1 thread (the order-service-jobs consumer thread)."""

    def __init__(self, url: str) -> None:
        self._params = connection_parameters(url)
        self._connection: pika.BlockingConnection | None = None
        self._channel = None

    def publish(self, job: Job) -> None:
        try:
            self._publish(job)
        except AMQPError:
            self.close()  # reconnect on the next call
            raise

    def _publish(self, job: Job) -> None:
        channel = self._ensure_channel()
        channel.basic_publish(
            exchange=JOBS_EXCHANGE,
            routing_key=job.queue,
            body=json.dumps(job.body()).encode(),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
                message_id=job.job_id,
            ),
            mandatory=True,  # raise if no queue receives it
        )
        log.info("job published", extra={"job_id": job.job_id, "queue": job.queue})

    def _ensure_channel(self):
        if self._channel is None or self._channel.is_closed:
            self.close()
            self._connection = pika.BlockingConnection(self._params)
            self._channel = self._connection.channel()
            self._channel.confirm_delivery()
            declare_topology(self._channel)
        return self._channel

    def close(self) -> None:
        if self._connection is not None and self._connection.is_open:
            try:
                self._connection.close()
            except AMQPError:
                log.warning("closing the rabbitmq connection failed", exc_info=True)
        self._connection = None
        self._channel = None
