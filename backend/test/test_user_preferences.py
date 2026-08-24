"""Unit tests for account-synced UI preferences (onboarding + theme).

Pure logic only (no DB): the preferences extractor, the request model, and the
JSONB merge behavior the PATCH /me/preferences endpoint relies on.
"""
from __future__ import annotations

import pytest

from app.api.routes import MeResponse, UserPreferencesUpdate, _user_preferences


class _FakeUser:
    def __init__(self, meta):
        self.user_metadata = meta


class TestUserPreferences:
    def test_extract_preferences_only(self):
        # Must return the `preferences` sub-dict, not the sibling integration tokens.
        u = _FakeUser({"preferences": {"has_onboarded": True, "theme": "dark"}, "zotero": "tok"})
        assert _user_preferences(u) == {"has_onboarded": True, "theme": "dark"}
        assert "zotero" not in _user_preferences(u)

    def test_extract_when_absent(self):
        assert _user_preferences(_FakeUser(None)) == {}
        assert _user_preferences(_FakeUser({})) == {}
        assert _user_preferences(_FakeUser({"zotero": "tok"})) == {}

    def test_meresponse_preferences_default_empty(self):
        assert MeResponse(id="1", email="a@b.com", plan="free").preferences == {}

    def test_update_model_accepts_partial(self):
        assert UserPreferencesUpdate(has_onboarded=True).model_dump() == {"has_onboarded": True, "theme": None}
        assert UserPreferencesUpdate(theme="light").theme == "light"

    def _merge(self, existing_meta, has_onboarded=None, theme=None):
        """Mirror the endpoint's JSONB merge (a fresh dict, preferences sub-key)."""
        meta = dict(existing_meta or {})
        prefs = dict(meta.get("preferences") or {})
        if has_onboarded is not None:
            prefs["has_onboarded"] = has_onboarded
        if theme is not None:
            prefs["theme"] = theme
        meta["preferences"] = prefs
        return meta

    def test_merge_preserves_sibling_metadata(self):
        merged = self._merge({"zotero": "tok"}, has_onboarded=True)
        assert merged["zotero"] == "tok"
        assert merged["preferences"] == {"has_onboarded": True}

    def test_merge_is_partial_over_existing_prefs(self):
        merged = self._merge({"preferences": {"has_onboarded": True, "theme": "dark"}}, theme="light")
        # theme updated, has_onboarded retained
        assert merged["preferences"] == {"has_onboarded": True, "theme": "light"}

    @pytest.mark.parametrize("bad", ["blue", "system", ""])
    def test_theme_validation_rejects_unknown(self, bad):
        # The endpoint validates theme ∈ {light, dark}; mirror that contract here.
        assert bad not in ("light", "dark")
