import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from order_service.api import create_app
from order_service.config import Settings
from order_service.schema import orders

BODY = {
    "customer_email": "buyer@example.com",
    "items": [{"product_id": str(uuid.uuid4()), "quantity": 1}],
}


@pytest.fixture
def client(engine, redis_client, database_url, redis_url):
    with TestClient(create_app(Settings(database_url=database_url, redis_url=redis_url))) as c:
        yield c


def order_count(engine):
    with engine.connect() as conn:
        return conn.scalar(select(func.count()).select_from(orders))


def test_same_key_twice_returns_same_response_and_1_order(client, engine):
    headers = {"Idempotency-Key": "abc-1"}
    first = client.post("/api/orders", json=BODY, headers=headers)
    second = client.post("/api/orders", json=BODY, headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert order_count(engine) == 1


def test_missing_key_returns_400(client, engine):
    assert client.post("/api/orders", json=BODY).status_code == 400
    assert order_count(engine) == 0


def test_same_key_with_a_different_body_returns_422(client):
    headers = {"Idempotency-Key": "abc-2"}
    client.post("/api/orders", json=BODY, headers=headers)
    other = {**BODY, "items": [{"product_id": str(uuid.uuid4()), "quantity": 2}]}
    assert client.post("/api/orders", json=other, headers=headers).status_code == 422


def test_request_still_running_returns_409(client, redis_client):
    from order_service.orders import NewOrder

    new = NewOrder.build(BODY["customer_email"], [(uuid.UUID(BODY["items"][0]["product_id"]), 1)])
    redis_client.set(
        "idem:abc-3", json.dumps({"state": "IN_PROGRESS", "fingerprint": new.fingerprint()})
    )
    response = client.post("/api/orders", json=BODY, headers={"Idempotency-Key": "abc-3"})
    assert response.status_code == 409
    assert response.headers["Retry-After"] == "1"


def test_postgres_still_blocks_duplicates_when_redis_lost_the_key(client, engine, redis_client):
    headers = {"Idempotency-Key": "abc-4"}
    first = client.post("/api/orders", json=BODY, headers=headers).json()
    redis_client.flushdb()  # as if Redis restarted without its data
    second = client.post("/api/orders", json=BODY, headers=headers)
    assert second.json() == first
    assert order_count(engine) == 1
