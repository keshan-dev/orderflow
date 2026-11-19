import pytest

from notification_worker.invoices import InvoiceJob, invoice_key, render_invoice
from notification_worker.worker import PermanentJobError

ORDER = {
    "order_id": "1df1af1b-236d-44b6-931b-8be8da28df2d",
    "customer_email": "buyer@example.com",
    "created_at": "2026-11-19T09:56:02.945114+00:00",
    "total_cents": 7999,
    "items": [{"product_id": "p", "name": "Desk Lamp", "quantity": 1, "unit_price_cents": 7999}],
}


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def exists(self, key: str) -> bool:
        return key in self.objects

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data


def test_key_uses_the_order_date_and_id():
    assert invoice_key(ORDER) == "invoices/2026/11/1df1af1b-236d-44b6-931b-8be8da28df2d.pdf"


def test_render_returns_a_pdf():
    data = render_invoice(ORDER)
    assert data.startswith(b"%PDF")
    assert len(data) > 500


def test_invoice_job_stores_the_pdf_under_its_key():
    store = FakeStore()
    InvoiceJob(store)({"job_id": "j", "payload": {"order": ORDER}})
    assert list(store.objects) == [invoice_key(ORDER)]


def test_job_without_an_order_is_permanent():
    with pytest.raises(PermanentJobError):
        InvoiceJob(FakeStore())({"job_id": "j", "payload": {}})
