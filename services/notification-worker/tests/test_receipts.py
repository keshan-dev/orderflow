import pytest

from notification_worker.dedupe import EmailDedupe
from notification_worker.receipts import EmailBusyError, EmailJob, receipt
from notification_worker.worker import PermanentJobError
from orderflow_common import testing
from orderflow_common.connections import make_redis

ORDER = {
    "order_id": "1df1af1b-236d-44b6-931b-8be8da28df2d",
    "total_cents": 18997,
    "items": [
        {"product_id": "p1", "name": "Wireless Mouse", "quantity": 1, "unit_price_cents": 2999},
        {"product_id": "p2", "name": "Desk Lamp", "quantity": 2, "unit_price_cents": 7999},
    ],
}


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


def test_receipt_lists_items_and_total():
    subject, body = receipt(ORDER)
    assert "1df1af1b" in subject
    assert "2 x Desk Lamp  159.98" in body
    assert "Total: 189.97" in body


@pytest.fixture(scope="module")
def redis_url():
    with testing.redis_container() as url:
        yield url


@pytest.fixture
def dedupe(redis_url):
    client = make_redis(redis_url)
    client.flushdb()
    yield EmailDedupe(client)
    client.close()


def email_job(order=ORDER):
    return {"job_id": "j", "payload": {"to": "buyer@example.com", "order": order}}


def test_email_job_sends_to_the_customer(dedupe):
    mailer = FakeMailer()
    EmailJob(mailer, dedupe)(email_job())
    [(to, subject, _)] = mailer.sent
    assert to == "buyer@example.com"
    assert subject.startswith("Your OrderFlow receipt")


def test_job_without_a_recipient_is_permanent(dedupe):
    with pytest.raises(PermanentJobError):
        EmailJob(FakeMailer(), dedupe)({"job_id": "j", "payload": {"order": ORDER}})


def test_same_job_twice_sends_1_email(dedupe):
    mailer = FakeMailer()
    job = EmailJob(mailer, dedupe)
    job(email_job())
    job(email_job())
    assert len(mailer.sent) == 1


def test_failed_send_releases_the_claim_so_a_retry_can_send(dedupe):
    class BrokenMailer(FakeMailer):
        def send(self, to, subject, body):
            raise ConnectionError("smtp down")

    with pytest.raises(ConnectionError):
        EmailJob(BrokenMailer(), dedupe)(email_job())
    mailer = FakeMailer()
    EmailJob(mailer, dedupe)(email_job())
    assert len(mailer.sent) == 1


def test_email_being_sent_by_another_worker_is_retried_later(dedupe):
    dedupe.claim(ORDER["order_id"])  # another worker holds the claim
    with pytest.raises(EmailBusyError):
        EmailJob(FakeMailer(), dedupe)(email_job())
