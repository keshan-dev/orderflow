import pytest
from sqlalchemy.exc import OperationalError

from orderflow_common.connections import retry_transient, to_psycopg_url


def test_to_psycopg_url():
    assert to_psycopg_url("postgresql://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert to_psycopg_url("postgresql+psycopg://x") == "postgresql+psycopg://x"


def test_retry_transient_retries_then_succeeds():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("down")
        return "ok"

    assert retry_transient(flaky, attempts=3) == "ok"
    assert len(calls) == 3


def test_retry_transient_gives_up_after_limit():
    calls = []

    def always_down():
        calls.append(1)
        raise OperationalError("select 1", {}, Exception("down"))

    with pytest.raises(OperationalError):
        retry_transient(always_down, attempts=2)
    assert len(calls) == 2


def test_retry_transient_does_not_retry_other_errors():
    calls = []

    def bug():
        calls.append(1)
        raise ValueError("bug")

    with pytest.raises(ValueError):
        retry_transient(bug, attempts=3)
    assert len(calls) == 1
