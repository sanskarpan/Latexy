"""Security properties of the process-wide structured logging boundary."""

from __future__ import annotations

import json
import logging

from app.core.logging import JsonFormatter


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
