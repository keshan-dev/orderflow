from dataclasses import dataclass

from orderflow_common.settings import env_int, env_str


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    kafka_bootstrap_servers: str = "localhost:29092"
    hold_ttl_seconds: int = 900
    sweeper_interval_seconds: int = 10
    product_cache_seconds: int = 60

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=env_str("DATABASE_URL"),
            redis_url=env_str("REDIS_URL"),
            kafka_bootstrap_servers=env_str("KAFKA_BOOTSTRAP_SERVERS"),
            hold_ttl_seconds=env_int("HOLD_TTL_SECONDS", 900),
            sweeper_interval_seconds=env_int("SWEEPER_INTERVAL_SECONDS", 10),
            product_cache_seconds=env_int("PRODUCT_CACHE_SECONDS", 60),
        )
