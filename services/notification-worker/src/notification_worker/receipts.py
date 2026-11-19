"""Receipt emails. Locally they go to Mailpit, so no real email ever leaves the machine."""

import logging
import smtplib
from email.message import EmailMessage
from typing import Any, Protocol

from notification_worker.dedupe import Claim, EmailDedupe
from notification_worker.worker import PermanentJobError

log = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 5


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailer:
    def __init__(self, host: str, port: int, sender: str) -> None:
        self._host = host
        self._port = port
        self._sender = sender

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self._host, self._port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
            smtp.send_message(message)


def money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def receipt(order: dict[str, Any]) -> tuple[str, str]:
    """Build the subject and plain text body of a receipt."""
    lines = [
        f"  {item['quantity']} x {item.get('name') or item['product_id']}"
        f"  {money(item['quantity'] * item.get('unit_price_cents', 0))}"
        for item in order.get("items", [])
    ]
    body = "\n".join(
        [
            "Thank you for your order.",
            "",
            f"Order: {order['order_id']}",
            *lines,
            "",
            f"Total: {money(order.get('total_cents') or 0)}",
        ]
    )
    return f"Your OrderFlow receipt ({order['order_id'][:8]})", body


class EmailBusyError(Exception):
    """Another worker is sending this email right now. Temporary: try again later."""


class EmailJob:
    def __init__(self, mailer: Mailer, dedupe: EmailDedupe) -> None:
        self._mailer = mailer
        self._dedupe = dedupe

    def __call__(self, job: dict[str, Any]) -> None:
        try:
            to = job["payload"]["to"]
            order = job["payload"]["order"]
            order_id = order["order_id"]
            subject, body = receipt(order)
        except (KeyError, TypeError) as exc:
            raise PermanentJobError(f"email job is missing data: {exc}") from exc

        claim = self._dedupe.claim(order_id)
        if claim is Claim.DONE:
            log.info("receipt already sent; skipping duplicate job")
            return
        if claim is Claim.BUSY:
            raise EmailBusyError(f"another worker is sending the receipt for {order_id}")
        try:
            self._mailer.send(to, subject, body)
        except Exception:
            self._dedupe.release(order_id)  # let the next try send it
            raise
        self._dedupe.mark_sent(order_id)
        log.info("receipt email sent")
