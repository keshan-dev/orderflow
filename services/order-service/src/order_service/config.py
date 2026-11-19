from dataclasses import dataclass

from orderflow_common.settings import env_int, env_str


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    kafka_bootstrap_servers: str = "localhost:29092"
    # Keep shorter than inventory-service HOLD_TTL_SECONDS (900 by default).
    payment_timeout_seconds: int = 120
    timeout_check_seconds: int = 10

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=env_str("DATABASE_URL"),
            redis_url=env_str("REDIS_URL"),
            kafka_bootstrap_servers=env_str("KAFKA_BOOTSTRAP_SERVERS"),
            payment_timeout_seconds=env_int("PAYMENT_TIMEOUT_SECONDS", 120),
            timeout_check_seconds=env_int("TIMEOUT_CHECK_SECONDS", 10),
        )
