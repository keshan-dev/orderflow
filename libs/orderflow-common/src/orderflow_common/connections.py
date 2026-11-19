"""Connections to PostgreSQL and Redis, always with timeouts and limited retries."""

import logging
from collections.abc import Callable

import redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

DB_CONNECT_TIMEOUT_SECONDS = 3
DB_STATEMENT_TIMEOUT_MS = 5000
REDIS_TIMEOUT_SECONDS = 2
REDIS_RETRIES = 3


def to_psycopg_url(url: str) -> str:
    """Accept a plain postgresql:// URL and tell SQLAlchemy to use the psycopg 3 driver."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def make_engine(url: str, pool_size: int = 5) -> Engine:
    return create_engine(
        to_psycopg_url(url),
        pool_size=pool_size,
        max_overflow=5,
        pool_timeout=5,
        pool_pre_ping=True,  # replaces dead connections after a database restart
        connect_args={
            "connect_timeout": DB_CONNECT_TIMEOUT_SECONDS,
            "options": f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS}",
        },
    )


def make_redis(url: str) -> redis.Redis:
    return redis.Redis.from_url(
        url,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
        retry=Retry(ExponentialBackoff(cap=1.0, base=0.1), REDIS_RETRIES),
        retry_on_error=[redis.ConnectionError, redis.TimeoutError],
        health_check_interval=30,
        decode_responses=True,
    )


def retry_transient[T](func: Callable[[], T], attempts: int = 3) -> T:
    """Run func, retrying only on connection-type errors, a limited number of times."""
    retrying = retry(
        retry=retry_if_exception_type(
            (OperationalError, redis.ConnectionError, redis.TimeoutError, ConnectionError)
        ),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=0.2, max=2),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    return retrying(func)()


def postgres_ok(engine: Engine) -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        log.warning("postgres check failed", exc_info=True)
        return False


def redis_ok(client: redis.Redis) -> bool:
    try:
        return bool(client.ping())
    except Exception:
        log.warning("redis check failed", exc_info=True)
        return False
