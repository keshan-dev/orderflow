from fastapi.testclient import TestClient

from inventory_service.api import create_app
from inventory_service.config import Settings

UNREACHABLE = Settings(
    database_url="postgresql://x:y@127.0.0.1:1/none",
    redis_url="redis://127.0.0.1:1/0",
    kafka_bootstrap_servers="127.0.0.1:1",
)


def test_healthz_does_not_depend_on_other_services():
    with TestClient(create_app(UNREACHABLE)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_is_503_when_dependencies_are_down():
    with TestClient(create_app(UNREACHABLE)) as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {
        "postgres": False,
        "redis": False,
        "stock_loaded": False,
        "consumer": True,
    }


def test_readyz_is_200_with_real_dependencies(database_url, redis_url):
    settings = Settings(database_url=database_url, redis_url=redis_url)
    with TestClient(create_app(settings)) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {
        "postgres": True,
        "redis": True,
        "stock_loaded": True,
        "consumer": True,
    }
