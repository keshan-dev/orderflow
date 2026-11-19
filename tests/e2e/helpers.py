"""Helpers for end-to-end tests against the running Compose stack.

Start the stack first (see README.md). These tests talk to the real containers through
their published ports and use `docker compose` to stop and start services.
"""

import json
import os
import pathlib
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from typing import Any

import psycopg
from confluent_kafka import Consumer, Producer

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "deploy" / "compose" / "docker-compose.yml"
ORDER_API = "http://localhost:8080"  # through nginx
INVENTORY_API = "http://localhost:8080"  # through nginx
KAFKA = "localhost:29092"
HTTP_TIMEOUT = 10  # the dev machine is near its memory limit; short stalls happen


def stack_running() -> bool:
    try:
        with socket.create_connection(("localhost", 8080), timeout=1):
            return True
    except OSError:
        return False


def env_file() -> dict[str, str]:
    values = {}
    for line in (COMPOSE_FILE.parent / ".env").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def compose(*args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        check=True,
        capture_output=True,
        timeout=180,
        env={**os.environ, **(env or {})},
    )


def wait_for_api(seconds: float = 60) -> None:
    """After a restart, wait until both APIs answer through nginx again."""

    def ready() -> bool:
        try:
            return http("GET", f"{INVENTORY_API}/api/products")[0] == 200 and http(
                "GET", f"{ORDER_API}/api/orders/search?q=ready"
            )[0] in (200, 503)
        except OSError:
            return False

    wait_until(ready, seconds, "apis reachable through nginx")


def recreate(service: str, **env: str) -> None:
    """Restart 1 service with different settings and wait until it is healthy."""
    compose("up", "-d", "--no-deps", "--force-recreate", service, env=env)
    container = f"orderflow-{service}-1"

    def healthy() -> bool:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", container],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() == "healthy"

    wait_until(healthy, 120, f"{service} healthy")
    wait_for_api()


def http(method: str, url: str, body: Any = None, headers: dict | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return response.status, _body(response.read())
    except urllib.error.HTTPError as error:
        return error.code, _body(error.read())


def _body(raw: bytes) -> Any:
    """JSON from the services; plain text from nginx error pages (for example a 502)."""
    try:
        return json.loads(raw or b"null")
    except json.JSONDecodeError:
        return raw.decode(errors="replace")


def product_id(sku: str) -> str:
    _, products = http("GET", f"{INVENTORY_API}/api/products")
    return next(p["id"] for p in products if p["sku"] == sku)


def place_order(product: str, quantity: int = 1, key: str | None = None) -> str:
    body = {
        "customer_email": "e2e@example.com",
        "items": [{"product_id": product, "quantity": quantity}],
    }
    status, response = http(
        "POST", f"{ORDER_API}/api/orders", body, {"Idempotency-Key": key or str(uuid.uuid4())}
    )
    assert status == 202, response
    return response["order_id"]


def order(order_id: str) -> dict[str, Any]:
    return http("GET", f"{ORDER_API}/api/orders/{order_id}")[1]


def wait_until(condition: Callable[[], bool], seconds: float = 60, message: str = "") -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.5)
    raise AssertionError(f"timed out waiting: {message}")


def wait_for_status(order_id: str, *statuses: str, seconds: float = 60) -> dict[str, Any]:
    wait_until(lambda: order(order_id)["status"] in statuses, seconds, f"{order_id} -> {statuses}")
    return order(order_id)


def db(name: str) -> psycopg.Connection:
    password = env_file()["POSTGRES_PASSWORD"]
    return psycopg.connect(
        f"postgresql://postgres:{password}@localhost:15432/{name}", connect_timeout=5
    )


def kafka_messages(topic: str, key: str, seconds: float = 10) -> list[dict[str, Any]]:
    """All messages on `topic` with this key, read from the start with a throwaway group."""
    consumer = Consumer(
        {
            "bootstrap.servers": KAFKA,
            "group.id": f"e2e-{uuid.uuid4()}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([topic])
    found, deadline, idle = [], time.monotonic() + seconds, 0
    while time.monotonic() < deadline and idle < 6:
        message = consumer.poll(1.0)
        if message is None:
            idle += 1
            continue
        idle = 0
        if not message.error() and message.key() and message.key().decode() == key:
            found.append({"value": message.value(), "headers": message.headers()})
    consumer.close()
    return found


def republish(topic: str, key: str, value: bytes, headers: Any) -> None:
    producer = Producer({"bootstrap.servers": KAFKA, "message.timeout.ms": 10000})
    producer.produce(topic, key=key, value=value, headers=headers)
    assert producer.flush(10) == 0


def event_types(topic: str, key: str) -> list[str]:
    return [json.loads(m["value"])["event_type"] for m in kafka_messages(topic, key)]


def is_e2e_enabled() -> bool:
    return os.environ.get("E2E", "1") != "0" and stack_running()
