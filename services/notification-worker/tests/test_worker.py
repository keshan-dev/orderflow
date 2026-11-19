import json
import threading
import time
import uuid

import pika
import pytest

from notification_worker.worker import PermanentJobError, Worker
from orderflow_common import testing
from orderflow_common.rabbitmq import JOBS_EXCHANGE

EMAIL = "notifications.email"


@pytest.fixture(scope="module")
def rabbitmq_url():
    with testing.rabbitmq_container() as url:
        yield url


def publish(url: str, body: bytes) -> None:
    connection = pika.BlockingConnection(pika.URLParameters(url))
    connection.channel().basic_publish(JOBS_EXCHANGE, EMAIL, body)
    connection.close()


def job_body() -> bytes:
    return json.dumps({"job_id": str(uuid.uuid4()), "order_id": str(uuid.uuid4())}).encode()


def queue_depth(url: str, queue: str) -> int:
    connection = pika.BlockingConnection(pika.URLParameters(url))
    depth = connection.channel().queue_declare(queue, passive=True).method.message_count
    connection.close()
    return depth


def run_worker(url: str, handler) -> Worker:
    worker = Worker(url, {EMAIL: handler}, attempts=3)
    threading.Thread(target=worker.run, daemon=True).start()
    time.sleep(2)  # declares the queues and starts consuming
    return worker


def wait_until(condition, seconds: float = 20) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.2)
    raise AssertionError("timed out")


def test_job_that_fails_then_works_is_acked(rabbitmq_url):
    calls: list[int] = []

    def flaky(job):
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("smtp down")

    worker = run_worker(rabbitmq_url, flaky)
    publish(rabbitmq_url, job_body())
    wait_until(lambda: len(calls) == 3)
    time.sleep(1)
    worker.stop()
    assert queue_depth(rabbitmq_url, f"{EMAIL}.dlq") == 0


def test_job_that_keeps_failing_goes_to_the_dlq_after_limited_attempts(rabbitmq_url):
    calls: list[int] = []

    def broken(job):
        calls.append(1)
        raise ConnectionError("smtp down")

    before = queue_depth(rabbitmq_url, f"{EMAIL}.dlq")
    worker = run_worker(rabbitmq_url, broken)
    publish(rabbitmq_url, job_body())
    wait_until(lambda: queue_depth(rabbitmq_url, f"{EMAIL}.dlq") == before + 1)
    worker.stop()
    assert len(calls) == 3


def test_permanent_error_and_bad_json_skip_the_retries(rabbitmq_url):
    calls: list[int] = []

    def permanent(job):
        calls.append(1)
        raise PermanentJobError("bad job")

    before = queue_depth(rabbitmq_url, f"{EMAIL}.dlq")
    worker = run_worker(rabbitmq_url, permanent)
    publish(rabbitmq_url, job_body())
    publish(rabbitmq_url, b"not json")
    wait_until(lambda: queue_depth(rabbitmq_url, f"{EMAIL}.dlq") == before + 2)
    worker.stop()
    assert len(calls) == 1
