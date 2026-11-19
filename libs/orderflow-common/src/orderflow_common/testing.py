"""Test helpers: real Postgres and Redis in containers, and Alembic migrations.

Only tests import this module, so testcontainers stays a dev dependency.
"""

import pathlib
from collections.abc import Iterator
from contextlib import contextmanager

POSTGRES_IMAGE = "postgres:17.12-alpine"
REDIS_IMAGE = "redis:8.6.8-alpine"
RABBITMQ_IMAGE = "rabbitmq:4.3.8-management-alpine"


@contextmanager
def postgres_container() -> Iterator[str]:
    """Start Postgres and yield a plain postgresql:// URL."""
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(POSTGRES_IMAGE) as pg:
        yield pg.get_connection_url(driver=None)


@contextmanager
def redis_container() -> Iterator[str]:
    from testcontainers.community.redis import RedisContainer

    with RedisContainer(REDIS_IMAGE) as rc:
        yield f"redis://{rc.get_container_host_ip()}:{rc.get_exposed_port(6379)}/0"


@contextmanager
def rabbitmq_container() -> Iterator[str]:
    """Start RabbitMQ and yield an amqp:// URL."""
    from testcontainers.community.rabbitmq import RabbitMqContainer

    with RabbitMqContainer(RABBITMQ_IMAGE) as rc:
        params = rc.get_connection_params()
        yield f"amqp://guest:guest@{params.host}:{params.port}/%2F"


def run_migrations(
    service_dir: pathlib.Path, url: str, revision: str = "head", downgrade: bool = False
) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(service_dir / "alembic.ini"))
    config.attributes["database_url"] = url
    config.attributes["skip_logging"] = True
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)
