from dataclasses import dataclass

from orderflow_common.settings import env_str


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    kafka_bootstrap_servers: str = "localhost:29092"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=env_str("DATABASE_URL"),
            redis_url=env_str("REDIS_URL"),
            kafka_bootstrap_servers=env_str("KAFKA_BOOTSTRAP_SERVERS"),
        )
