import uuid

from order_service.job_events import JobsFromEvents
from order_service.jobs import EMAIL_QUEUE, INVOICE_QUEUE, Job
from orderflow_common.events import Event


class RecordingPublisher:
    def __init__(self, fail_on: str | None = None) -> None:
        self.published: list[Job] = []
        self._fail_on = fail_on

    def publish(self, job: Job) -> None:
        if job.queue == self._fail_on:
            raise ConnectionError("rabbitmq is down")
        self.published.append(job)

    def close(self) -> None:
        pass


def confirmed() -> Event:
    order = {"order_id": "x", "customer_email": "buyer@example.com", "total_cents": 7999}
    return Event("OrderConfirmed", uuid.uuid4(), {"order": order})


def test_order_confirmed_creates_email_and_invoice_jobs():
    publisher = RecordingPublisher()
    event = confirmed()
    JobsFromEvents(publisher)(event)
    assert [(j.queue, j.job_id) for j in publisher.published] == [
        (EMAIL_QUEUE, f"{event.event_id}:email"),
        (INVOICE_QUEUE, f"{event.event_id}:invoice"),
    ]
    assert publisher.published[0].payload["to"] == "buyer@example.com"


def test_other_events_create_no_jobs():
    publisher = RecordingPublisher()
    JobsFromEvents(publisher)(Event("OrderCreated", uuid.uuid4(), {}))
    assert publisher.published == []
