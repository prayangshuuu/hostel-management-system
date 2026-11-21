"""Unit tests for structured logging and formatters."""

import json
import logging

import pytest

from app.core.config import settings
from app.core.logging import (
    DevFormatter,
    JSONFormatter,
    RequestIdFilter,
    request_id_ctx_var,
    setup_logging,
)


def test_request_id_filter() -> None:
    """Verify that RequestIdFilter sets request_id on LogRecord."""
    token = request_id_ctx_var.set("test-request-id-123")
    try:
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="test message",
            args=(),
            exc_info=None,
        )
        filt = RequestIdFilter()
        filt.filter(record)
        assert getattr(record, "request_id", None) == "test-request-id-123"
    finally:
        request_id_ctx_var.reset(token)


def test_json_formatter() -> None:
    """Verify that JSONFormatter produces valid structured JSON payload."""
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Sample log message %s",
        args=("arg1",),
        exc_info=None,
    )
    record.request_id = "req-abc-999"

    formatter = JSONFormatter()
    output = formatter.format(record)
    data = json.loads(output)

    assert data["level"] == "INFO"
    assert data["logger"] == "app.test"
    assert data["message"] == "Sample log message arg1"
    assert data["request_id"] == "req-abc-999"
    assert "timestamp" in data


def test_json_formatter_with_exception() -> None:
    """Verify that JSONFormatter captures exceptions properly."""
    try:
        raise ValueError("Something bad happened")
    except ValueError:
        import sys

        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="app.test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=1,
        msg="Error encountered",
        args=(),
        exc_info=exc_info,
    )
    formatter = JSONFormatter()
    output = formatter.format(record)
    data = json.loads(output)

    assert data["level"] == "ERROR"
    assert "exception" in data
    assert "ValueError: Something bad happened" in data["exception"]


def test_dev_formatter() -> None:
    """Verify that DevFormatter produces formatted text containing request id and level."""
    record = logging.LogRecord(
        name="app.test",
        level=logging.WARNING,
        pathname="test.py",
        lineno=1,
        msg="Warning message",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-dev-456"

    formatter = DevFormatter()
    output = formatter.format(record)

    assert "[WARNING]" in output
    assert "[app.test]" in output
    assert "[req-dev-456]" in output
    assert "Warning message" in output


def test_setup_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify setup_logging configures root logger handlers and log level."""
    monkeypatch.setattr(settings, "LOG_LEVEL", "DEBUG")
    monkeypatch.setattr(settings, "APP_ENV", "production")

    setup_logging()
    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG
    assert len(root_logger.handlers) == 1
    assert isinstance(root_logger.handlers[0].formatter, JSONFormatter)
