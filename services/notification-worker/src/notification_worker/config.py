from dataclasses import dataclass

from orderflow_common.settings import env_int, env_str


@dataclass(frozen=True)
class Settings:
    rabbitmq_url: str
    redis_url: str
    smtp_host: str
    smtp_port: int
    s3_bucket: str
    s3_endpoint_url: str | None = None
    mail_from: str = "orders@orderflow.local"
    prefetch: int = 10
    attempts: int = 3
    heartbeat_file: str = "/tmp/heartbeat"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            rabbitmq_url=env_str("RABBITMQ_URL"),
            redis_url=env_str("REDIS_URL"),
            smtp_host=env_str("SMTP_HOST"),
            smtp_port=env_int("SMTP_PORT", 25),
            s3_bucket=env_str("S3_BUCKET"),
            s3_endpoint_url=env_str("S3_ENDPOINT_URL", "") or None,
            mail_from=env_str("MAIL_FROM", "orders@orderflow.local"),
            prefetch=env_int("PREFETCH", 10),
            attempts=env_int("MAX_RETRIES", 3),
            heartbeat_file=env_str("HEARTBEAT_FILE", "/tmp/heartbeat"),
        )
