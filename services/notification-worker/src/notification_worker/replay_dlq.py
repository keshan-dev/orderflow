"""Move jobs from a dead letter queue back to their queue, after the cause is fixed.

Run inside the worker container:
  docker compose -f deploy/compose/docker-compose.yml exec notification-worker \
    python -m notification_worker.replay_dlq notifications.email [--limit 10]

Each job is published again with confirms on, and only then removed from the .dlq queue,
so a crash in the middle can duplicate a job but never lose one (the worker is idempotent).
"""

import argparse
import logging

import pika

from orderflow_common.logging import configure_logging
from orderflow_common.rabbitmq import JOB_QUEUES, JOBS_EXCHANGE, connection_parameters
from orderflow_common.settings import env_str

log = logging.getLogger("replay_dlq")


def replay(url: str, queue: str, limit: int) -> int:
    connection = pika.BlockingConnection(connection_parameters(url))
    try:
        channel = connection.channel()
        channel.confirm_delivery()
        moved = 0
        while moved < limit:
            method, properties, body = channel.basic_get(f"{queue}.dlq")
            if method is None:
                break
            channel.basic_publish(JOBS_EXCHANGE, queue, body, properties, mandatory=True)
            channel.basic_ack(method.delivery_tag)
            moved += 1
            log.info("job replayed", extra={"queue": queue, "job_id": properties.message_id})
        return moved
    finally:
        connection.close()


def main() -> None:
    configure_logging("replay-dlq")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("queue", choices=JOB_QUEUES)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    moved = replay(env_str("RABBITMQ_URL"), args.queue, args.limit)
    log.info("replay finished", extra={"queue": args.queue, "moved": moved})


if __name__ == "__main__":
    main()
