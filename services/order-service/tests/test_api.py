import uuid

import pytest
from fastapi.testclient import TestClient

from order_service.api import create_app
from order_service.config import Settings


@pytest.fixture
def client(engine, redis_client, database_url, redis_url):
    with TestClient(create_app(Settings(database_url=database_url, redis_url=redis_url))) as c:
        yield c


def order_body(quantity=1):
    return {
        "customer_email": "buyer@example.com",
        "items": [{"product_id": str(uuid.uuid4()), "quantity": quantity}],
    }


def test_post_order_returns_202_and_location(client):
    response = client.post("/api/orders", json=order_body(), headers={"Idempotency-Key": "k-1"})
    assert response.status_code == 202
    order_id = response.json()["order_id"]
    assert response.headers["Location"] == f"/api/orders/{order_id}"
    assert response.json()["status"] == "PENDING"


@pytest.mark.parametrize(
    "body",
    [
        {
            "customer_email": "not-an-email",
            "items": [{"product_id": str(uuid.uuid4()), "quantity": 1}],
        },
        {"customer_email": "a@b.co", "items": []},
        {"customer_email": "a@b.co", "items": [{"product_id": str(uuid.uuid4()), "quantity": 0}]},
    ],
)
def test_invalid_body_is_rejected(client, body):
    response = client.post("/api/orders", json=body, headers={"Idempotency-Key": "k-2"})
    assert response.status_code == 422


def test_get_order_returns_the_snapshot(client):
    body = order_body(quantity=3)
    created = client.post("/api/orders", json=body, headers={"Idempotency-Key": "k-3"}).json()
    order = client.get(f"/api/orders/{created['order_id']}").json()
    assert order["status"] == "PENDING"
    assert order["items"][0]["quantity"] == 3
    assert order["total_cents"] is None  # known only after inventory reserves the stock


def test_unknown_order_returns_404(client):
    assert client.get(f"/api/orders/{uuid.uuid4()}").status_code == 404
