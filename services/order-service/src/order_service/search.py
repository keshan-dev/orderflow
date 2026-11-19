"""Search orders in OpenSearch through the "orders" alias."""

from typing import Any

from opensearchpy import OpenSearch

FIELDS = ["order_id", "status", "customer_email", "product_names", "total", "created_at"]


def make_search_client(url: str) -> OpenSearch:
    return OpenSearch(hosts=[url], timeout=3, max_retries=2, retry_on_timeout=True)


def search_orders(client: OpenSearch, index: str, text: str, limit: int) -> list[dict[str, Any]]:
    """Match product names, or an exact order id, email or status."""
    query = {
        "bool": {
            "should": [
                {"match": {"product_names": {"query": text}}},
                {"term": {"order_id": text}},
                {"term": {"customer_email": text.lower()}},
                {"term": {"status": text.upper()}},
            ],
            "minimum_should_match": 1,
        }
    }
    response = client.search(
        index=index,
        body={"query": query, "size": limit, "sort": ["_score", {"created_at": "desc"}]},
        params={"_source_includes": ",".join(FIELDS)},
    )
    return [hit["_source"] for hit in response["hits"]["hits"]]
