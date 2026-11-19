"""Rebuild the search index from Kafka alone, without downtime.

Run inside the container:
  docker compose -f deploy/compose/docker-compose.yml exec search-indexer \
    python -m search_indexer.rebuild orders-v3

Steps:
1. Create the new index with the same mapping and settings as the one behind the alias.
2. Read every event in orders.events from the start into the new index (bulk writes).
3. Move the alias to the new index in 1 atomic call.
4. Read again up to the newest offset, to pick up events that arrived during step 2.
External versions make every step safe to overlap with the running indexer.
"""

import argparse
import logging
import uuid
from typing import Any

from confluent_kafka import OFFSET_BEGINNING, Consumer, TopicPartition
from opensearchpy import OpenSearch

from orderflow_common.kafka import PermanentError, parse_event
from orderflow_common.logging import configure_logging
from orderflow_common.settings import env_str
from search_indexer.indexer import OrderIndexer, make_client

log = logging.getLogger("search_indexer.rebuild")

KEPT_SETTINGS = ("number_of_shards", "number_of_replicas", "analysis")
BATCH_SIZE = 500


def current_index(client: OpenSearch, alias: str) -> str:
    [index] = client.indices.get_alias(name=alias).keys()
    return index


def create_like(client: OpenSearch, source: str, target: str) -> None:
    mappings = client.indices.get_mapping(index=source)[source]["mappings"]
    settings = client.indices.get_settings(index=source)[source]["settings"]["index"]
    kept = {key: settings[key] for key in KEPT_SETTINGS if key in settings}
    client.indices.create(index=target, body={"settings": kept, "mappings": mappings})


def read_to_end(consumer: Consumer, topic: str, indexer: OrderIndexer) -> int:
    """Index every event up to the end offsets measured now. Returns how many were read."""
    partitions = consumer.assignment()
    ends = {p.partition: consumer.get_watermark_offsets(p, timeout=10)[1] for p in partitions}
    done = {p for p, end in ends.items() if _position(consumer, topic, p) >= end}
    read = 0
    while len(done) < len(ends):
        messages = consumer.consume(num_messages=BATCH_SIZE, timeout=2.0)
        events = []
        for message in messages:
            if message.error() or message.value() is None:
                continue
            try:
                events.append(parse_event(message))
            except PermanentError:
                log.warning("skipping a malformed event", extra={"offset": message.offset()})
        indexer.index_events(events)
        read += len(messages)
        done = {p for p, end in ends.items() if _position(consumer, topic, p) >= end}
    return read


def _position(consumer: Consumer, topic: str, partition: int) -> int:
    [position] = consumer.position([TopicPartition(topic, partition)])
    return position.offset if position.offset >= 0 else 0


def rebuild(
    client: OpenSearch,
    bootstrap: str,
    new_index: str,
    alias: str = "orders",
    topic: str = "orders.events",
) -> dict[str, Any]:
    old_index = current_index(client, alias)
    create_like(client, old_index, new_index)
    indexer = OrderIndexer(client, new_index)

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"search-rebuild-{uuid.uuid4()}",  # throwaway, never committed
            "enable.auto.commit": False,
        }
    )
    try:
        metadata = consumer.list_topics(topic, timeout=10)
        partitions = list(metadata.topics[topic].partitions)
        consumer.assign([TopicPartition(topic, p, OFFSET_BEGINNING) for p in partitions])
        first_pass = read_to_end(consumer, topic, indexer)
        client.indices.update_aliases(
            body={
                "actions": [
                    {"remove": {"index": old_index, "alias": alias}},
                    {"add": {"index": new_index, "alias": alias}},
                ]
            }
        )
        catch_up = read_to_end(consumer, topic, indexer)
    finally:
        consumer.close()
    client.indices.refresh(index=new_index)
    documents = client.count(index=new_index)["count"]
    return {
        "old_index": old_index,
        "new_index": new_index,
        "events_read": first_pass + catch_up,
        "documents": documents,
    }


def main() -> None:
    configure_logging("search-rebuild")
    parser = argparse.ArgumentParser(description="Rebuild the search index from Kafka.")
    parser.add_argument("new_index", help="name of the index to create, for example orders-v3")
    args = parser.parse_args()
    result = rebuild(
        make_client(env_str("OPENSEARCH_URL")),
        env_str("KAFKA_BOOTSTRAP_SERVERS"),
        args.new_index,
        env_str("INDEX_ALIAS", "orders"),
    )
    log.info("rebuild finished", extra=result)


if __name__ == "__main__":
    main()
