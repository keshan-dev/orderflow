import json
import logging

import pytest

from orderflow_common.logging import JsonFormatter, log_context
from orderflow_common.settings import MissingSettingError, env_float, env_int, env_str


def test_env_str_reads_value_and_default(monkeypatch):
    monkeypatch.setenv("OF_TEST", "abc")
    assert env_str("OF_TEST") == "abc"
    assert env_str("OF_MISSING", "fallback") == "fallback"


def test_env_str_missing_raises(monkeypatch):
    monkeypatch.delenv("OF_MISSING", raising=False)
    with pytest.raises(MissingSettingError):
        env_str("OF_MISSING")


def test_env_int_and_float(monkeypatch):
    monkeypatch.setenv("OF_INT", "7")
    monkeypatch.setenv("OF_FLOAT", "0.25")
    assert env_int("OF_INT") == 7
    assert env_float("OF_FLOAT") == 0.25
    monkeypatch.setenv("OF_INT", "seven")
    with pytest.raises(MissingSettingError):
        env_int("OF_INT")


def test_json_formatter_includes_service_context_and_extra():
    formatter = JsonFormatter("test-service")
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "reserved %s", ("stock",), None)
    record.attempt = 2
    with log_context(order_id="o-1"):
        line = json.loads(formatter.format(record))
    assert line["service"] == "test-service"
    assert line["msg"] == "reserved stock"
    assert line["order_id"] == "o-1"
    assert line["attempt"] == 2


def test_log_context_is_removed_after_block():
    formatter = JsonFormatter("s")
    with log_context(order_id="o-1"):
        pass
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "x", (), None)
    assert "order_id" not in json.loads(formatter.format(record))
