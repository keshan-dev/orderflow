import uuid

import pytest
from fastapi.testclient import TestClient

from inventory_service.api import create_app
from inventory_service.config import Settings
from inventory_service.seed import CATALOG, seed

LAMP = CATALOG[-1]


@pytest.fixture
def client(engine, redis_client, database_url, redis_url):
    seed(engine)
    settings = Settings(database_url=database_url, redis_url=redis_url)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_reserve_then_release_through_http(client):
    order = str(uuid.uuid4())
    body = {"order_id": order, "items": [{"product_id": str(LAMP.id), "quantity": 2}]}
    reserved = client.post("/internal/reserve", json=body).json()
    assert reserved["outcome"] == "RESERVED"
    assert reserved["lines"][0]["name"] == LAMP.name
    released = client.post("/internal/release", json={"order_id": order}).json()
    assert released["outcome"] == "RELEASED"


def test_bad_items_return_400(client):
    body = {"order_id": str(uuid.uuid4()), "items": [{"product_id": "x", "quantity": 1}]}
    assert client.post("/internal/reserve", json=body).status_code == 400
