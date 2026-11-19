import json
import uuid

import pika
import pytest

from order_service.jobs import EMAIL_QUEUE, INVOICE_QUEUE, Job, make_job_publisher
from orderflow_common import testing
from orderflow_common.rabbitmq import JOB_QUEUES


@pytest.fixture(scope="module")
def rabbitmq_url():
    with testing.rabbitmq_container() as url:
        yield url


def take(url: str, queue: str):
    connection = pika.BlockingConnection(pika.URLParameters(url))
    method, properties, body = connection.channel().basic_get(queue, auto_ack=True)
    connection.close()
    return method, properties, body


def test_published_jobs_land_in_their_durable_queues(rabbitmq_url):
    publisher = make_job_publisher("rabbitmq", rabbitmq_url)
    order_id = uuid.uuid4()
    publisher.publish(Job("e1:email", EMAIL_QUEUE, order_id, {"to": "a@b.co"}))
    publisher.publish(Job("e1:invoice", INVOICE_QUEUE, order_id))
    publisher.close()

    method, properties, body = take(rabbitmq_url, EMAIL_QUEUE)
    assert method is not None
    assert properties.message_id == "e1:email"
    assert properties.delivery_mode == 2  # persistent: survives a broker restart
    assert json.loads(body)["payload"] == {"to": "a@b.co"}
    assert take(rabbitmq_url, INVOICE_QUEUE)[0] is not None


def test_rejected_message_goes_to_its_dead_letter_queue(rabbitmq_url):
    publisher = make_job_publisher("rabbitmq", rabbitmq_url)
    publisher.publish(Job("e2:email", EMAIL_QUEUE, uuid.uuid4()))
    publisher.close()

    connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    channel = connection.channel()
    method, _, _ = channel.basic_get(EMAIL_QUEUE)
    channel.basic_nack(method.delivery_tag, requeue=False)
    connection.close()

    method, properties, _ = take(rabbitmq_url, f"{EMAIL_QUEUE}.dlq")
    assert properties.message_id == "e2:email"
    assert set(JOB_QUEUES) == {EMAIL_QUEUE, INVOICE_QUEUE}
