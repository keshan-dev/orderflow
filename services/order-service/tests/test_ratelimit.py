import dataclasses
import uuid

import redis
from fastapi.testclient import TestClient

from order_service.api import create_app
from order_service.ratelimit import RateLimiter, client_id


def test_burst_is_allowed_up_to_capacity_then_limited(redis_client):
    limiter = RateLimiter(redis_client, capacity=5, per_second=1)
    decisions = [limiter.check("ip:1.2.3.4") for _ in range(7)]
    assert [d.allowed for d in decisions] == [True] * 5 + [False] * 2
    assert decisions[-1].retry_after_seconds >= 1


def test_2_copies_share_1_bucket(redis_client):
    copy_1 = RateLimiter(redis_client, capacity=4, per_second=1)
    copy_2 = RateLimiter(redis_client, capacity=4, per_second=1)
    allowed = [(copy_1 if i % 2 else copy_2).check("id:k6").allowed for i in range(6)]
    assert allowed.count(True) == 4


def test_clients_have_separate_buckets(redis_client):
    limiter = RateLimiter(redis_client, capacity=1, per_second=1)
    assert limiter.check("ip:a").allowed
    assert limiter.check("ip:b").allowed
    assert not limiter.check("ip:a").allowed


def test_client_id_prefers_header_then_forwarded_ip():
    assert client_id({"x-client-id": "app-7"}, "10.0.0.1") == "id:app-7"
    assert client_id({"x-forwarded-for": "203.0.113.5, 10.0.0.2"}, "10.0.0.1") == "ip:203.0.113.5"
    assert client_id({}, "10.0.0.1") == "ip:10.0.0.1"


def test_api_returns_429_with_retry_after(engine, redis_client, app_settings):
    settings = dataclasses.replace(app_settings, rate_limit_capacity=2, rate_limit_per_second=0.5)
    body = {
        "customer_email": "a@b.co",
        "items": [{"product_id": str(uuid.uuid4()), "quantity": 1}],
    }
    with TestClient(create_app(settings)) as client:
        responses = [
            client.post(
                "/api/orders",
                json=body,
                headers={"Idempotency-Key": str(uuid.uuid4()), "X-Client-Id": "burst"},
            )
            for _ in range(3)
        ]
    assert [r.status_code for r in responses] == [202, 202, 429]
    assert int(responses[-1].headers["Retry-After"]) >= 1


def test_broken_redis_fails_open():
    limiter = RateLimiter(redis.Redis(port=1, socket_connect_timeout=0.2), 1, 1)
    assert limiter.check("ip:x").allowed
