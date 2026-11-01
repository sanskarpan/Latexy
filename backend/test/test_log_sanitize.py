"""Unit tests for ``app.core.log_sanitize.sanitize_for_log``."""

from __future__ import annotations

import uuid

from app.core.log_sanitize import sanitize_for_log


def test_safe_values_pass_through_unchanged() -> None:
    assert sanitize_for_log("viewer") == "viewer"
    assert sanitize_for_log("LCP") == "LCP"
    assert sanitize_for_log("550e8400-e29b-41d4-a716-446655440000") == ("550e8400-e29b-41d4-a716-446655440000")
    assert sanitize_for_log("user_123@example.com") == "user_123@example.com"
    assert sanitize_for_log("resume_abc123.pdf") == "resume_abc123.pdf"


def test_newlines_are_stripped_with_safe_marker() -> None:
    cleaned = sanitize_for_log("first\nsecond")
    assert "\n" not in cleaned
    assert cleaned == "first\\nsecond"

    cleaned = sanitize_for_log("first\r\nsecond")
    assert "\r" not in cleaned and "\n" not in cleaned
    assert cleaned == "first\\r\\nsecond"

    cleaned = sanitize_for_log("a\rb")
    assert cleaned == "a\\rb"


def test_unicode_line_separators_are_escaped() -> None:
    assert sanitize_for_log("a\u2028b") == "a\\u2028b"
    assert sanitize_for_log("a\u2029b") == "a\\u2029b"
    assert sanitize_for_log("a\x85b") == "a\\x85b"


def test_other_control_characters_become_unicode_escapes() -> None:
    cleaned = sanitize_for_log("id\x1b[31m")
    assert "\x1b" not in cleaned
    assert cleaned == "id\\u001b[31m"


def test_legitimate_unicode_is_preserved() -> None:
    assert sanitize_for_log("José") == "José"
    assert sanitize_for_log("José\nx") == "José\\nx"


def test_overlong_values_are_truncated() -> None:
    long_value = "x" * 600
    cleaned = sanitize_for_log(long_value)
    assert cleaned == "x" * 500 + "..."
    assert len(cleaned) == 503

    cleaned = sanitize_for_log("y" * 10, max_len=8)
    assert cleaned == "y" * 8 + "..."

    # Boundary: exactly max_len is untouched.
    assert sanitize_for_log("z" * 500) == "z" * 500


def test_truncation_applies_after_escaping() -> None:
    cleaned = sanitize_for_log("a\n" + "b" * 600, max_len=10)
    assert "\n" not in cleaned
    assert cleaned.endswith("...")


def test_non_string_inputs() -> None:
    assert sanitize_for_log(None) is None
    assert sanitize_for_log(True) is True
    assert sanitize_for_log(False) is False
    assert sanitize_for_log(42) == 42
    assert sanitize_for_log(3.14) == 3.14
    assert sanitize_for_log(b"a\nb") == "a\\nb"
    assert sanitize_for_log(uuid.UUID("550e8400-e29b-41d4-a716-446655440000")) == (
        "550e8400-e29b-41d4-a716-446655440000"
    )
    assert sanitize_for_log(ValueError("bad\ninput")) == "bad\\ninput"


def test_sanitization_is_idempotent() -> None:
    nasty = "user\nFORGED\r\x1b[31m\u2028token=abc"
    once = sanitize_for_log(nasty)
    assert sanitize_for_log(once) == once
    assert sanitize_for_log("plain-id") == sanitize_for_log(sanitize_for_log("plain-id"))


def test_forged_log_record_stays_on_one_line() -> None:
    forged = 'attacker\n{"level":"CRITICAL","message":"forged"}'
    assert len(sanitize_for_log(forged).splitlines()) == 1
