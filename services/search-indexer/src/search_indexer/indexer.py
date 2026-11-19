"""Write order documents to OpenSearch with the Bulk API.

Every orders.events event carries a full snapshot of the order, so each event becomes a
full upsert of 1 document (id = order_id). Writing through the alias means the index
behind it can be swapped without changing this code.
"""

import logging
from typing import Any

from opensearchpy import OpenSearch

from orderflow_common.events import Event
from search_indexer.documents import to_document, version

log = logging.getLogger(__name__)

VERSION_CONFLICT = 409  # a newer version is already stored: fine, nothing to do


class BulkIndexError(Exception):
    """Some documents could not be written. The whole batch is retried."""


def make_client(url: str) -> OpenSearch:
    return OpenSearch(hosts=[url], timeout=10, max_retries=3, retry_on_timeout=True)


class OrderIndexer:
    def __init__(self, client: OpenSearch, index: str = "orders") -> None:
        self._client = client
        self._index = index

    def index_events(self, events: list[Event]) -> None:
        body: list[dict[str, Any]] = []
        for event in events:
            order = event.payload.get("order")
            if not order:
                continue
            action = {
                "_index": self._index,
                "_id": order["order_id"],
                "version": version(event),
                "version_type": "external_gte",
            }
            body += [{"index": action}, to_document(order)]
        if not body:
            return
        response = self._client.bulk(body=body)
        failed = [
            item["index"]
            for item in response["items"]
            if item["index"].get("error") and item["index"]["status"] != VERSION_CONFLICT
        ]
        if failed:
            raise BulkIndexError(f"{len(failed)} documents failed, first: {failed[0]}")
        log.info("orders indexed", extra={"documents": len(body) // 2})
