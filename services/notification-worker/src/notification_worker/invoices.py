"""PDF invoices stored in S3 (SeaweedFS locally, Amazon S3 in Phase 5).

The key is fixed per order (invoices/{yyyy}/{mm}/{order_id}.pdf), so writing the same
invoice again just replaces the same object.
"""

import logging
from datetime import datetime
from typing import Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fpdf import FPDF

from notification_worker.receipts import money
from notification_worker.worker import PermanentJobError

log = logging.getLogger(__name__)

S3_CONFIG = Config(
    connect_timeout=3,
    read_timeout=10,
    retries={"max_attempts": 3, "mode": "standard"},
)


class InvoiceStore(Protocol):
    def exists(self, key: str) -> bool: ...

    def put(self, key: str, data: bytes) -> None: ...


class S3InvoiceStore:
    def __init__(self, bucket: str, endpoint_url: str | None = None) -> None:
        self._bucket = bucket
        # Credentials come from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY locally, and from an
        # IAM role on AWS. endpoint_url points at the local S3 store and is unset on AWS.
        self._client = boto3.client(
            "s3", endpoint_url=endpoint_url, config=S3_CONFIG, region_name="us-east-1"
        )

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def put(self, key: str, data: bytes) -> None:
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType="application/pdf"
        )


def invoice_key(order: dict[str, Any]) -> str:
    created = datetime.fromisoformat(order["created_at"])
    return f"invoices/{created:%Y}/{created:%m}/{order['order_id']}.pdf"


def render_invoice(order: dict[str, Any]) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", style="B", size=16)
    pdf.cell(0, 10, "OrderFlow invoice", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 8, f"Order: {order['order_id']}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Customer: {order.get('customer_email', '')}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    for item in order.get("items", []):
        name = item.get("name") or item["product_id"]
        total = money(item["quantity"] * item.get("unit_price_cents", 0))
        pdf.cell(0, 8, f"{item['quantity']} x {name}   {total}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, f"Total: {money(order.get('total_cents') or 0)}")
    return bytes(pdf.output())


class InvoiceJob:
    def __init__(self, store: InvoiceStore) -> None:
        self._store = store

    def __call__(self, job: dict[str, Any]) -> None:
        try:
            order = job["payload"]["order"]
            key = invoice_key(order)
        except (KeyError, TypeError, ValueError) as exc:
            raise PermanentJobError(f"invoice job is missing data: {exc}") from exc
        if self._store.exists(key):
            log.info("invoice already stored; skipping duplicate job", extra={"key": key})
            return
        self._store.put(key, render_invoice(order))
        log.info("invoice stored", extra={"key": key})
