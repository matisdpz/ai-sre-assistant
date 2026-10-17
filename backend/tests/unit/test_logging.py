import json
import logging
import sys

from app.logging_config import JsonFormatter


def _record(msg: str, exc_info=None, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("test.logger", logging.WARNING, __file__, 1, msg, (), exc_info)
    record.__dict__.update(extra)
    return record


def test_formats_record_as_single_json_line_with_extra_fields() -> None:
    line = JsonFormatter().format(_record("db slow", service="payment-service", latency_ms=812))

    assert "\n" not in line
    payload = json.loads(line)
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "test.logger"
    assert payload["msg"] == "db slow"
    assert payload["service"] == "payment-service"
    assert payload["latency_ms"] == 812
    assert payload["ts"].endswith("+00:00")  # UTC timestamp


def test_includes_exception_traceback() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        line = JsonFormatter().format(_record("failed", exc_info=sys.exc_info()))

    payload = json.loads(line)
    assert "RuntimeError: boom" in payload["exc"]


def test_non_serializable_extra_does_not_break_logging() -> None:
    payload = json.loads(JsonFormatter().format(_record("x", obj=object())))
    assert payload["obj"].startswith("<object object")
