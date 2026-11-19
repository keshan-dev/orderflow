"""Real Postgres and Redis for tests, started once per test session with Testcontainers."""

import pathlib

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

from orderflow_common.connections import make_engine, make_redis

SERVICE_DIR = pathlib.Path(__file__).resolve().parents[1]
ALL_TABLES = "reservations, stock, products, outbox, processed_events"


def run_migrations(url: str, revision: str = "head", downgrade: bool = False) -> None:
    config = Config(str(SERVICE_DIR / "alembic.ini"))
    config.attributes["database_url"] = url
    config.attributes["skip_logging"] = True
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


@pytest.fixture(scope="session")
def database_url():
    with PostgresContainer("postgres:17.12-alpine") as pg:
        url = pg.get_connection_url(driver=None)
        run_migrations(url)
        yield url


@pytest.fixture(scope="session")
def redis_url():
    with RedisContainer("redis:8.6.8-alpine") as rc:
        yield f"redis://{rc.get_container_host_ip()}:{rc.get_exposed_port(6379)}/0"


@pytest.fixture
def engine(database_url):
    eng = make_engine(database_url, pool_size=20)
    with eng.begin() as conn:
        conn.execute(text(f"TRUNCATE {ALL_TABLES} CASCADE"))
    yield eng
    eng.dispose()


@pytest.fixture
def redis_client(redis_url):
    client = make_redis(redis_url)
    client.flushdb()
    yield client
    client.close()
