from dataclasses import dataclass

from orderflow_common.settings import env_str


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(database_url=env_str("DATABASE_URL"), redis_url=env_str("REDIS_URL"))
