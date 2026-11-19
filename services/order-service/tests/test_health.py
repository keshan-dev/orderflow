from fastapi.testclient import TestClient

from order_service.api import create_app
from order_service.config import Settings

UNREACHABLE = Settings(
    database_url="postgresql://x:y@127.0.0.1:1/none",
    redis_url="redis://127.0.0.1:1/0",
)


def test_healthz_does_not_depend_on_other_services():
    with TestClient(create_app(UNREACHABLE)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_is_503_when_dependencies_are_down():
    with TestClient(create_app(UNREACHABLE)) as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"postgres": False, "redis": False}
