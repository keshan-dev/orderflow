from dataclasses import dataclass

from orderflow_common.settings import env_float, env_int, env_str


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    kafka_bootstrap_servers: str
    opensearch_url: str = "http://127.0.0.1:1"
    search_index: str = "orders"
    job_backend: str = "rabbitmq"
    rabbitmq_url: str | None = None
    # Keep shorter than inventory-service HOLD_TTL_SECONDS (900 by default).
    payment_timeout_seconds: int = 120
    timeout_check_seconds: int = 10
    # Per client: a burst of up to `capacity` orders, then `per_second` orders per second.
    rate_limit_capacity: int = 20
    rate_limit_per_second: float = 10.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=env_str("DATABASE_URL"),
            redis_url=env_str("REDIS_URL"),
            kafka_bootstrap_servers=env_str("KAFKA_BOOTSTRAP_SERVERS"),
            opensearch_url=env_str("OPENSEARCH_URL"),
            search_index=env_str("SEARCH_INDEX", "orders"),
            job_backend=env_str("JOB_BACKEND", "rabbitmq"),
            rabbitmq_url=env_str("RABBITMQ_URL"),
            payment_timeout_seconds=env_int("PAYMENT_TIMEOUT_SECONDS", 120),
            timeout_check_seconds=env_int("TIMEOUT_CHECK_SECONDS", 10),
            rate_limit_capacity=env_int("RATE_LIMIT_CAPACITY", 20),
            rate_limit_per_second=env_float("RATE_LIMIT_PER_SECOND", 10.0),
        )
