"""Security properties of the process-wide structured logging boundary."""

from __future__ import annotations

import io
import json
import logging

from app.core.logging import JsonFormatter, get_logger


def test_attacker_controlled_line_breaks_cannot_forge_log_records() -> None:
    record = logging.LogRecord(
        name="app.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Rejected input: %s",
        args=("first line\n{\"level\":\"CRITICAL\",\"message\":\"forged\"}\rthird",),
        exc_info=None,
    )

    rendered = JsonFormatter().format(record)

    assert len(rendered.splitlines()) == 1
    payload = json.loads(rendered)
    assert payload["message"].startswith("Rejected input: first line\n")
    assert payload["level"] == "WARNING"


def test_message_text_redacts_embedded_credentials() -> None:
    message = (
        "redis://user:super-secret@redis.example/0 "
        "Authorization: Bearer abc.def.ghi token=gQAAAA-private-value"
    )
    record = logging.LogRecord(
        name="app.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )

    rendered = JsonFormatter().format(record)

    assert "super-secret" not in rendered
    assert "abc.def.ghi" not in rendered
    assert "gQAAAA-private-value" not in rendered
    assert rendered.count("[redacted]") >= 3


def test_application_logger_protects_plain_worker_handlers() -> None:
    logger = get_logger("app.test.plain_worker")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    previous_level = logger.level
    previous_propagation = logger.propagate
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    try:
        logger.warning("Rejected %s", "id\nFORGED\r\x1b[31m\u2028token=private-token")
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagation
    rendered = stream.getvalue()
    assert len(rendered.splitlines()) == 1
    assert "private-token" not in rendered
    assert "\\u000aFORGED\\u000d\\u001b" in rendered
    assert "\\u2028token=[redacted]" in rendered
