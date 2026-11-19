import uuid

import pytest

from order_service.jobs import EMAIL_QUEUE, Job, UnsupportedJobBackendError, make_job_publisher


def test_unknown_backend_fails_with_a_clear_message():
    with pytest.raises(UnsupportedJobBackendError, match="only 'rabbitmq'"):
        make_job_publisher("sqs")


def test_rabbitmq_backend_needs_a_url():
    with pytest.raises(UnsupportedJobBackendError, match="RABBITMQ_URL"):
        make_job_publisher("rabbitmq", None)


def test_job_body_has_every_field():
    order_id = uuid.uuid4()
    job = Job("evt-1:email", EMAIL_QUEUE, order_id, {"to": "a@b.co"})
    assert job.body() == {
        "job_id": "evt-1:email",
        "queue": EMAIL_QUEUE,
        "order_id": str(order_id),
        "payload": {"to": "a@b.co"},
    }
