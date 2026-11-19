"""Turn OrderConfirmed events into jobs (receipt email, PDF invoice).

This runs in its own consumer group, order-service-jobs. The Kafka offset is committed only
after both jobs are stored (the publisher raises otherwise), so a crash can never lose a
job. It can publish a job twice, so the worker must be idempotent.
"""

import logging

from order_service.jobs import EMAIL_QUEUE, INVOICE_QUEUE, Job, JobPublisher
from orderflow_common.events import Event

log = logging.getLogger(__name__)


class JobsFromEvents:
    def __init__(self, publisher: JobPublisher) -> None:
        self._publisher = publisher

    def __call__(self, event: Event) -> None:
        if event.event_type != "OrderConfirmed":
            return
        order = event.payload["order"]
        jobs = [
            Job(
                f"{event.event_id}:email",
                EMAIL_QUEUE,
                event.order_id,
                {"to": order["customer_email"], "order": order},
            ),
            Job(f"{event.event_id}:invoice", INVOICE_QUEUE, event.order_id, {"order": order}),
        ]
        for job in jobs:
            self._publisher.publish(job)
        log.info("jobs created for confirmed order")
