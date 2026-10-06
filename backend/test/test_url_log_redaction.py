"""Regression coverage for user URL and provider-error log redaction."""

from app.services.job_scraper_service import _safe_url_for_log


def test_url_log_helper_drops_query_fragment_and_credentials():
    url = "https://alice:secret@example.com/private/path?token=super-secret&email=a@example.com#frag"

    assert _safe_url_for_log(url) == "https://example.com/private/path"


def test_invalid_url_log_helper_is_non_sensitive():
    assert _safe_url_for_log("https://[invalid") == "<invalid-url>"


def test_url_log_helper_neutralizes_control_characters_and_bounds_length():
    safe = _safe_url_for_log("https://example.com/first\rforged-entry/" + "x" * 1000)

    assert "\r" not in safe
    assert "\n" not in safe
    assert "forged-entry" in safe
    assert len(safe) == 512
