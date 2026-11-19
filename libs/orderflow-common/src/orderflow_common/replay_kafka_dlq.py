"""Replay messages from <topic>.dlq after the cause is fixed.

Each message goes back through <topic>.retry with attempt 0 and the consumer group that
failed it, so only that group handles it again (other groups that read the same topic
already did their part). Each failing group has its own replay position
(consumer group "dlq-replay.<group>"), so a message is replayed once, and dead letters of
other groups are never skipped for them.

Run inside any Python service container, for example:
  docker compose -f deploy/compose/docker-compose.yml exec order-service-1 \
    python -m orderflow_common.replay_kafka_dlq orders.events --group inventory-service
"""

import argparse
import logging

from confluent_kafka import Consumer

from orderflow_common.deadletter import DLQ_SUFFIX, DeadLetterPublisher, retry_info
from orderflow_common.logging import configure_logging
from orderflow_common.settings import env_str

log = logging.getLogger("replay_kafka_dlq")

REPLAY_GROUP_PREFIX = "dlq-replay."
IDLE_POLLS_BEFORE_DONE = 5


def replay(bootstrap: str, topic: str, group: str, limit: int = 100) -> int:
    """Replay up to `limit` dead letters of `topic` that consumer group `group` failed."""
    publisher = DeadLetterPublisher(bootstrap)
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": REPLAY_GROUP_PREFIX + group,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([topic + DLQ_SUFFIX])
    replayed, idle = 0, 0
    try:
        while replayed < limit and idle < IDLE_POLLS_BEFORE_DONE:
            message = consumer.poll(1.0)
            if message is None or message.error():
                idle += 1
                continue
            idle = 0
            info = retry_info(message)
            if info is not None and info.group == group:
                publisher.replay(topic, message, group)
                replayed += 1
                log.info("dead letter replayed", extra={"group": group, "offset": message.offset()})
            # Another group's dead letter: it has its own replay position, so moving past it
            # here is safe.
            consumer.commit(message=message, asynchronous=False)
    finally:
        consumer.close()
    return replayed


def main() -> None:
    configure_logging("replay-kafka-dlq")
    parser = argparse.ArgumentParser(
        description="Replay Kafka dead letters through the retry topic."
    )
    parser.add_argument("topic", help="the main topic, for example orders.events")
    parser.add_argument("--group", required=True, help="the consumer group that failed them")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    count = replay(env_str("KAFKA_BOOTSTRAP_SERVERS"), args.topic, args.group, args.limit)
    log.info("replay finished", extra={"topic": args.topic, "replayed": count})


if __name__ == "__main__":
    main()
