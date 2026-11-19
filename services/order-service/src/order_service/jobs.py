"""Background jobs (receipt email, PDF invoice) behind a small interface.

order-service never talks to a queue directly. JOB_BACKEND picks the implementation:
"rabbitmq" in Phase 1; Phase 5 adds "sqs" without touching the saga or the consumer.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

EMAIL_QUEUE = "notifications.email"
INVOICE_QUEUE = "invoices.generate"


@dataclass(frozen=True)
class Job:
    job_id: str  # stable for the same event, so workers can spot duplicates
    queue: str
    order_id: uuid.UUID
    payload: dict[str, Any] = field(default_factory=dict)

    def body(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "queue": self.queue,
            "order_id": str(self.order_id),
            "payload": self.payload,
        }


class JobPublisher(Protocol):
    def publish(self, job: Job) -> None:
        """Store the job durably. Raises if it cannot; the caller must then retry."""
        ...

    def close(self) -> None: ...


class UnsupportedJobBackendError(ValueError):
    pass


def make_job_publisher(backend: str, rabbitmq_url: str | None = None) -> JobPublisher:
    if backend == "rabbitmq":
        if not rabbitmq_url:
            raise UnsupportedJobBackendError("JOB_BACKEND=rabbitmq needs RABBITMQ_URL")
        from order_service.rabbitmq import RabbitMQJobPublisher

        return RabbitMQJobPublisher(rabbitmq_url)
    raise UnsupportedJobBackendError(
        f"unsupported JOB_BACKEND {backend!r}: Phase 1 supports only 'rabbitmq'"
    )
