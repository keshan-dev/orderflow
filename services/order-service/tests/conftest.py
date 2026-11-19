"""Real Postgres and Redis for tests, started once per test session with Testcontainers."""

import functools
import pathlib

import pytest
from sqlalchemy import text

from order_service.config import Settings
from orderflow_common import testing
from orderflow_common.connections import make_engine, make_redis

SERVICE_DIR = pathlib.Path(__file__).resolve().parents[1]
ALL_TABLES = "order_items, orders, outbox, processed_events"

run_migrations = functools.partial(testing.run_migrations, SERVICE_DIR)


@pytest.fixture(scope="session")
def database_url():
    with testing.postgres_container() as url:
        run_migrations(url)
        yield url


@pytest.fixture(scope="session")
def redis_url():
    with testing.redis_container() as url:
        yield url


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


@pytest.fixture
def app_settings(database_url, redis_url) -> Settings:
    """Real Postgres and Redis. Kafka and RabbitMQ are unreachable on purpose, so app tests
    never join the consumer groups or queues of the running Compose services."""
    return Settings(
        database_url=database_url,
        redis_url=redis_url,
        kafka_bootstrap_servers="127.0.0.1:1",
        rabbitmq_url="amqp://x:y@127.0.0.1:1/%2F",
    )
