"""M7 checks: nginx keeps serving when 1 order-service copy dies, and the rate limit is shared."""

import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from helpers import ORDER_API, http, is_e2e_enabled, product_id, recreate

pytestmark = pytest.mark.skipif(not is_e2e_enabled(), reason="Compose stack is not running")


def docker(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, capture_output=True, timeout=60)


def test_requests_keep_working_while_1_copy_is_down():
    docker("kill", "orderflow-order-service-1-1")
    try:
        codes = [http("GET", f"{ORDER_API}/api/orders/search?q=lamp")[0] for _ in range(30)]
    finally:
        docker("start", "orderflow-order-service-1-1")
        recreate("order-service-1")
    assert codes == [200] * 30


def test_rate_limit_is_shared_by_both_copies():
    cable = product_id("CB-USB")
    body = {"customer_email": "rl@example.com", "items": [{"product_id": cable, "quantity": 1}]}
    client = f"e2e-{uuid.uuid4()}"

    def post(_: int) -> int:
        headers = {"Idempotency-Key": str(uuid.uuid4()), "X-Client-Id": client}
        return http("POST", f"{ORDER_API}/api/orders", body, headers)[0]

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(post, range(40)))
    assert set(codes) <= {202, 429}
    assert 20 <= codes.count(202) < 40  # the burst is allowed, the rest is limited
    assert codes.count(429) > 0
