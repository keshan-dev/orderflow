"""RabbitMQ connection settings and the job queue layout, shared by publisher and worker.

Layout:
  exchange orderflow.jobs (direct) --notifications.email--> queue notifications.email
                                   --invoices.generate----> queue invoices.generate
  A message that is rejected (nack, requeue=False) goes to the dead letter exchange
  orderflow.jobs.dlx, which routes it to <queue>.dlq for a person to look at.
"""

import pika
from pika.adapters.blocking_connection import BlockingChannel

JOBS_EXCHANGE = "orderflow.jobs"
DEAD_LETTER_EXCHANGE = "orderflow.jobs.dlx"
JOB_QUEUES = ("notifications.email", "invoices.generate")


def connection_parameters(url: str) -> pika.URLParameters:
    params = pika.URLParameters(url)
    params.connection_attempts = 3
    params.retry_delay = 1
    params.socket_timeout = 5
    params.blocked_connection_timeout = 10
    params.heartbeat = 30
    return params


def declare_topology(channel: BlockingChannel) -> None:
    """Create exchanges and queues if they are missing. Safe to call many times."""
    channel.exchange_declare(JOBS_EXCHANGE, exchange_type="direct", durable=True)
    channel.exchange_declare(DEAD_LETTER_EXCHANGE, exchange_type="direct", durable=True)
    for queue in JOB_QUEUES:
        dlq = f"{queue}.dlq"
        channel.queue_declare(dlq, durable=True)
        channel.queue_bind(dlq, DEAD_LETTER_EXCHANGE, routing_key=queue)
        channel.queue_declare(
            queue, durable=True, arguments={"x-dead-letter-exchange": DEAD_LETTER_EXCHANGE}
        )
        channel.queue_bind(queue, JOBS_EXCHANGE, routing_key=queue)
