"""From-header normalization for provider sends."""

from app.core.config import settings
from app.services.email_service import _envelope_from, _from_header


def test_from_header_prefixes_only_a_bare_address(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_FROM", "support@latexy.xyz")
    monkeypatch.setattr(settings, "EMAIL_FROM_NAME", "Latexy")
    assert _from_header() == "Latexy <support@latexy.xyz>"
    assert _envelope_from() == "support@latexy.xyz"


def test_from_header_preserves_an_existing_display_name(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_FROM", "Latexy <support@latexy.xyz>")
    monkeypatch.setattr(settings, "EMAIL_FROM_NAME", "Latexy")
    assert _from_header() == "Latexy <support@latexy.xyz>"
    assert _envelope_from() == "support@latexy.xyz"
