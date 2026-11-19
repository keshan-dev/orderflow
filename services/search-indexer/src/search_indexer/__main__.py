"""Run the indexer: python -m search_indexer"""

import logging
import signal
import threading

from orderflow_common.background import PeriodicTask
from orderflow_common.heartbeat import beat
from orderflow_common.kafka import BatchEventConsumer
from orderflow_common.logging import configure_logging
from orderflow_common.settings import env_int, env_str
from search_indexer.indexer import OrderIndexer, make_client

log = logging.getLogger("search_indexer")


def main() -> None:
    configure_logging("search-indexer")
    indexer = OrderIndexer(make_client(env_str("OPENSEARCH_URL")), env_str("INDEX_ALIAS", "orders"))
    consumer = BatchEventConsumer(
        env_str("KAFKA_BOOTSTRAP_SERVERS"),
        "search-indexer",
        ["orders.events"],
        indexer.index_events,
        batch_size=env_int("BATCH_SIZE", 200),
    )
    heartbeat_file = env_str("HEARTBEAT_FILE", "/tmp/heartbeat")
    # The health check passes only while the consumer loop keeps polling.
    heartbeat = PeriodicTask(
        "heartbeat", 5, lambda: beat(heartbeat_file) if consumer.healthy else None
    )
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())

    consumer.start()
    heartbeat.start()
    log.info("search-indexer started")
    stopped.wait()
    heartbeat.stop()
    consumer.stop()
    log.info("search-indexer stopped")


if __name__ == "__main__":
    main()
