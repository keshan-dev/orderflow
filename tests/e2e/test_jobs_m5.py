"""M5 checks: 1 confirmed order gives exactly 1 email and 1 PDF, even with duplicates and a
broken email server."""

import base64
import json
import time
import urllib.request
import uuid

import boto3
import pytest
from helpers import (
    ORDER_API,
    compose,
    env_file,
    http,
    is_e2e_enabled,
    product_id,
    wait_for_api,
    wait_for_status,
    wait_until,
)

pytestmark = pytest.mark.skipif(not is_e2e_enabled(), reason="Compose stack is not running")

MAILPIT = "http://127.0.0.1:8025/api/v1"
RABBITMQ_API = "http://127.0.0.1:15672/api"


def emails_to(address: str) -> int:
    url = f"{MAILPIT}/search?query=to:{address}"
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)["messages_count"]


def queue_depth(queue: str) -> int:
    env = env_file()
    request = urllib.request.Request(f"{RABBITMQ_API}/queues/%2F/{queue}")
    token = base64.b64encode(f"{env['RABBITMQ_USER']}:{env['RABBITMQ_PASSWORD']}".encode())
    request.add_header("Authorization", f"Basic {token.decode()}")
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response).get("messages", 0)


def invoice_exists(order_id: str) -> bool:
    env = env_file()
    s3 = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:7333",
        region_name="us-east-1",
        aws_access_key_id=env["S3_ACCESS_KEY"],
        aws_secret_access_key=env["S3_SECRET_KEY"],
    )
    listing = s3.list_objects_v2(Bucket="orderflow-invoices", Prefix="invoices/")
    return any(order_id in obj["Key"] for obj in listing.get("Contents", []))


def worker_exec(*args: str) -> None:
    compose("exec", "-T", "notification-worker", *args)


def unique_email() -> str:
    return f"e2e-{time.time_ns()}@example.com"


def place_for(email: str) -> str:
    body = {"customer_email": email, "items": [{"product_id": product_id("CB-USB"), "quantity": 1}]}
    status, response = http(
        "POST", f"{ORDER_API}/api/orders", body, {"Idempotency-Key": str(uuid.uuid4())}
    )
    assert status == 202
    return response["order_id"]


def test_confirmed_order_gets_1_email_and_1_invoice():
    email = unique_email()
    order_id = place_for(email)
    wait_for_status(order_id, "CONFIRMED")
    wait_until(lambda: emails_to(email) == 1 and invoice_exists(order_id), 60, "email and pdf")
    time.sleep(3)
    assert emails_to(email) == 1


def test_broken_email_server_sends_job_to_dlq_then_replay_sends_once():
    dlq_before = queue_depth("notifications.email.dlq")
    compose("stop", "mailpit")
    try:
        email = unique_email()
        order_id = place_for(email)
        wait_for_status(order_id, "CONFIRMED")
        wait_until(lambda: queue_depth("notifications.email.dlq") == dlq_before + 1, 90, "dlq")
    finally:
        compose("start", "mailpit")
        wait_for_api()
    wait_until(lambda: _mailpit_up(), 60, "mailpit back")
    worker_exec("python", "-m", "notification_worker.replay_dlq", "notifications.email")
    wait_until(lambda: emails_to(email) == 1, 60, "email after replay")
    # The management API refreshes queue statistics every few seconds.
    wait_until(lambda: queue_depth("notifications.email.dlq") == dlq_before, 30, "dlq empty")
    time.sleep(3)
    assert emails_to(email) == 1


def test_duplicate_jobs_send_1_email():
    email = unique_email()
    order_id = place_for(email)
    wait_for_status(order_id, "CONFIRMED")
    wait_until(lambda: emails_to(email) == 1, 60, "first email")
    # Publish the same kind of job again, as a crash between publish and commit would.
    job = {
        "job_id": "duplicate-test",
        "queue": "notifications.email",
        "order_id": order_id,
        "payload": {"to": email, "order": {"order_id": order_id, "items": [], "total_cents": 0}},
    }
    worker_exec(
        "python",
        "-c",
        "import json,os,pika;"
        "from orderflow_common.rabbitmq import JOBS_EXCHANGE;"
        "c=pika.BlockingConnection(pika.URLParameters(os.environ['RABBITMQ_URL']));"
        f"c.channel().basic_publish(JOBS_EXCHANGE,'notifications.email',{json.dumps(json.dumps(job))});"
        "c.close()",
    )
    time.sleep(5)
    assert emails_to(email) == 1


def _mailpit_up() -> bool:
    try:
        with urllib.request.urlopen(f"{MAILPIT}/messages?limit=1", timeout=2):
            return True
    except OSError:
        return False
