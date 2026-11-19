import pytest

from notification_worker.receipts import EmailJob, receipt
from notification_worker.worker import PermanentJobError

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


def test_email_job_sends_to_the_customer():
    mailer = FakeMailer()
    EmailJob(mailer)({"job_id": "j", "payload": {"to": "buyer@example.com", "order": ORDER}})
    [(to, subject, _)] = mailer.sent
    assert to == "buyer@example.com"
    assert subject.startswith("Your OrderFlow receipt")


def test_job_without_a_recipient_is_permanent():
    with pytest.raises(PermanentJobError):
        EmailJob(FakeMailer())({"job_id": "j", "payload": {"order": ORDER}})
