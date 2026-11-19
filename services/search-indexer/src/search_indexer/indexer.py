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

    def index_events(self, events: list[Event]) -> list[Event]:
        """Write 1 document per event. Returns the events OpenSearch rejected for good (for
        example a document that does not fit the mapping); the consumer sends those to the
        dead letter topic. Temporary errors (429, 5xx) raise, so the whole batch is retried."""
        body: list[dict[str, Any]] = []
        sent: list[Event] = []
        rejected: list[Event] = []
        for event in events:
            order = event.payload.get("order")
            if not order:
                continue
            try:
                document = to_document(order)
            except (KeyError, TypeError, ValueError):
                rejected.append(event)
                continue
            action = {
                "_index": self._index,
                "_id": order["order_id"],
                "version": version(event),
                "version_type": "external_gte",
            }
            body += [{"index": action}, document]
            sent.append(event)
        if not body:
            return rejected
        response = self._client.bulk(body=body)
        temporary = []
        for event, item in zip(sent, response["items"], strict=True):
            result = item["index"]
            status = result.get("status", 200)
            if not result.get("error") or status == VERSION_CONFLICT:
                continue
            if status == 429 or status >= 500:
                temporary.append(result)
            else:
                rejected.append(event)
        if temporary:
            raise BulkIndexError(f"{len(temporary)} documents failed, first: {temporary[0]}")
        log.info("orders indexed", extra={"documents": len(sent), "rejected": len(rejected)})
        return rejected
