"""PostHog data-boundary regressions.

These tests intentionally avoid the database and network. They pin the rule that
server-side analytics may carry opaque IDs and low-cardinality enums, but never
résumé content, prompts, emails, tokens, or nested document payloads.
"""

from app.core.config import settings
from app.services.posthog_service import posthog_service, sanitize_posthog_properties


def test_sanitizer_drops_identifiers_and_document_content():
    safe = sanitize_posthog_properties(
        {
            "email": "person@example.com",
            "name": "Person",
            "resume_content": "secret",
            "latex_content": "\\documentclass",
            "prompt": "rewrite",
            "job_description": "job text",
            "access_token": "token",
            "feature_key": "f01",
            "plan_key": "pro",
            "duration_ms": 123,
            "success": True,
            "nested": {"unsafe": "value"},
            "list": ["unsafe"],
        }
    )

    assert safe == {
        "feature_key": "f01",
        "plan_key": "pro",
        "duration_ms": 123,
        "success": True,
    }


def test_sanitizer_bounds_strings_and_property_count():
    payload = {"note": "x" * 500}
    payload.update({f"key_{index}": index for index in range(40)})
    safe = sanitize_posthog_properties(payload)
    assert len(str(safe["note"])) == 200
    assert len(safe) <= 25


class _FakeClient:
    def __init__(self):
        self.calls = []

    def capture(self, event, **kwargs):
        self.calls.append((event, kwargs))


def test_capture_uses_distinct_id_and_geoip_guard(monkeypatch):
    monkeypatch.setattr(settings, "POSTHOG_API_KEY", "phc_test")
    monkeypatch.setattr(settings, "POSTHOG_ENABLED", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    fake = _FakeClient()
    monkeypatch.setattr(posthog_service, "_client", fake)
    monkeypatch.setattr(posthog_service, "_attempted", True)

    posthog_service.capture(
        "user-1",
        "backend_test_event",
        {"plan_key": "pro", "email": "person@example.com"},
    )

    assert len(fake.calls) == 1
    event, kwargs = fake.calls[0]
    assert event == "backend_test_event"
    assert kwargs["distinct_id"] == "user-1"
    assert kwargs["properties"]["plan_key"] == "pro"
    assert kwargs["properties"]["$geoip_disable"] is True
    assert "email" not in kwargs["properties"]


def test_capture_is_noop_without_a_configured_key(monkeypatch):
    monkeypatch.setattr(settings, "POSTHOG_API_KEY", "")
    monkeypatch.setattr(settings, "POSTHOG_ENABLED", True)
    monkeypatch.setattr(posthog_service, "_client", None)
    monkeypatch.setattr(posthog_service, "_attempted", False)
    assert posthog_service.configured is False
    posthog_service.capture("user-id", "backend_test_event", {"plan_key": "free"})
    posthog_service.capture_event(user_id=None, event_type="compile", metadata={"status": "completed"})
