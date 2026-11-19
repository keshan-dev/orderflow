import json
import pathlib
import socket
import uuid

import pytest
from fastapi.testclient import TestClient
from opensearchpy import OpenSearch

from order_service.api import create_app

MAPPING = (
    pathlib.Path(__file__).resolve().parents[3] / "deploy/compose/opensearch/orders-mapping.json"
)


def opensearch_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 9200), timeout=1):
            return True
    except OSError:
        return False


def test_search_returns_503_when_opensearch_is_down(engine, redis_client, app_settings):
    with TestClient(create_app(app_settings)) as client:
        response = client.get("/api/orders/search", params={"q": "lamp"})
    assert response.status_code == 503


def test_search_needs_a_query(engine, redis_client, app_settings):
    with TestClient(create_app(app_settings)) as client:
        assert client.get("/api/orders/search").status_code == 422


@pytest.mark.skipif(not opensearch_running(), reason="Compose OpenSearch is down")
def test_search_finds_orders_by_product_name_and_status(engine, redis_client, app_settings):
    import dataclasses

    # Admin calls use a patient client: the app client gives up after 3 seconds and retries,
    # which can turn 1 slow "create index" into "index already exists".
    search = OpenSearch(hosts=["http://127.0.0.1:9200"], timeout=30, max_retries=0)
    index = f"test-orders-{uuid.uuid4().hex[:8]}"
    search.indices.create(index=index, body=json.loads(MAPPING.read_text()))
    try:
        order_id = str(uuid.uuid4())
        document = {
            "order_id": order_id,
            "status": "CONFIRMED",
            "customer_email": "buyer@example.com",
            "product_names": ["Limited Edition Desk Lamp"],
            "items": [],
            "total": 79.99,
            "created_at": "2026-11-19T10:00:00+00:00",
            "updated_at": "2026-11-19T10:00:00+00:00",
        }
        search.index(index=index, id=order_id, body=document, params={"refresh": "true"})
        settings = dataclasses.replace(
            app_settings, opensearch_url="http://127.0.0.1:9200", search_index=index
        )
        with TestClient(create_app(settings)) as client:
            by_name = client.get("/api/orders/search", params={"q": "desk lamp"}).json()
            by_status = client.get("/api/orders/search", params={"q": "confirmed"}).json()
        assert [r["order_id"] for r in by_name["results"]] == [order_id]
        assert [r["order_id"] for r in by_status["results"]] == [order_id]
    finally:
        search.indices.delete(index=index)
