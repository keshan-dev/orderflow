"""Run the worker: python -m notification_worker"""

import logging
import signal

from notification_worker.config import Settings
from notification_worker.dedupe import EmailDedupe
from notification_worker.invoices import InvoiceJob, S3InvoiceStore
from notification_worker.receipts import EmailJob, SmtpMailer
from notification_worker.worker import Worker
from orderflow_common.connections import make_redis
from orderflow_common.logging import configure_logging

log = logging.getLogger("notification_worker")


def main() -> None:
    configure_logging("notification-worker")
    cfg = Settings.from_env()
    redis_client = make_redis(cfg.redis_url)
    worker = Worker(
        cfg.rabbitmq_url,
        {
            "notifications.email": EmailJob(
                SmtpMailer(cfg.smtp_host, cfg.smtp_port, cfg.mail_from), EmailDedupe(redis_client)
            ),
            "invoices.generate": InvoiceJob(S3InvoiceStore(cfg.s3_bucket, cfg.s3_endpoint_url)),
        },
        prefetch=cfg.prefetch,
        attempts=cfg.attempts,
        heartbeat_file=cfg.heartbeat_file,
    )
    signal.signal(signal.SIGTERM, lambda *_: worker.stop())
    log.info("notification-worker started")
    worker.run()
    redis_client.close()
    log.info("notification-worker stopped")


if __name__ == "__main__":
    main()
