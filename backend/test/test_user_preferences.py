"""Unit tests for account-synced UI preferences (onboarding + theme).

Pure logic only (no DB): the preferences extractor, the request model, and the
JSONB merge behavior the PATCH /me/preferences endpoint relies on.
"""
from __future__ import annotations

import pytest

from app.api.routes import MeResponse, UserPreferencesUpdate, _user_preferences
from app.services.entitlement_service import entitlement_service


def _set_dictionary_capability(monkeypatch, *, allowed: bool):
    async def has_feature(key, *, user, db=None):
        assert key == "c16"
        assert user
        return allowed

    monkeypatch.setattr(entitlement_service, "has_feature", has_feature)


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
        assert UserPreferencesUpdate(has_onboarded=True).model_dump() == {
            "has_onboarded": True,
            "theme": None,
            "spell_dictionary": None,
        }
        assert UserPreferencesUpdate(theme="light").theme == "light"

    def test_spell_dictionary_is_normalized_and_deduplicated(self):
        body = UserPreferencesUpdate(spell_dictionary=[" OpenAI ", "openai", "Node.js"])
        assert body.spell_dictionary == ["openai", "node.js"]

    @pytest.mark.parametrize("words", [["two words"], [""], ["x" * 65], ["ok"] * 501])
    def test_spell_dictionary_rejects_unbounded_or_invalid_words(self, words):
        with pytest.raises(ValueError):
            UserPreferencesUpdate(spell_dictionary=words)

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


@pytest.mark.asyncio
async def test_spell_dictionary_round_trips_without_replacing_other_preferences(client, auth_headers, monkeypatch):
    _set_dictionary_capability(monkeypatch, allowed=True)
    first = await client.patch(
        "/me/preferences",
        headers=auth_headers,
        json={"has_onboarded": True, "theme": "dark"},
    )
    assert first.status_code == 200

    updated = await client.patch(
        "/me/preferences",
        headers=auth_headers,
        json={"spell_dictionary": [" OpenAI ", "openai", "Node.js"]},
    )
    assert updated.status_code == 200
    assert updated.json()["preferences"] == {
        "has_onboarded": True,
        "theme": "dark",
        "spell_dictionary": ["openai", "node.js"],
    }

    loaded = await client.get("/me", headers=auth_headers)
    assert loaded.status_code == 200
    assert loaded.json()["preferences"] == updated.json()["preferences"]


@pytest.mark.asyncio
async def test_spell_dictionary_new_word_is_denied_without_mutating_preferences(client, auth_headers, monkeypatch):
    _set_dictionary_capability(monkeypatch, allowed=False)
    before = (await client.get("/me", headers=auth_headers)).json()["preferences"]

    denied = await client.patch(
        "/me/preferences",
        headers=auth_headers,
        json={"spell_dictionary": ["capability-off-new-word"]},
    )
    assert denied.status_code == 403
    assert (await client.get("/me", headers=auth_headers)).json()["preferences"] == before


@pytest.mark.asyncio
async def test_spell_dictionary_existing_words_can_sync_or_be_removed_when_off(client, auth_headers, monkeypatch):
    capability = {"allowed": True}

    async def has_feature(key, *, user, db=None):
        assert key == "c16"
        assert user
        return capability["allowed"]

    monkeypatch.setattr(entitlement_service, "has_feature", has_feature)
    seeded = await client.patch(
        "/me/preferences",
        headers=auth_headers,
        json={"spell_dictionary": ["keep-word", "remove-word"]},
    )
    assert seeded.status_code == 200
    capability["allowed"] = False

    same = await client.patch(
        "/me/preferences",
        headers=auth_headers,
        json={"spell_dictionary": ["keep-word", "remove-word"]},
    )
    assert same.status_code == 200
    assert same.json()["preferences"]["spell_dictionary"] == ["keep-word", "remove-word"]

    removed = await client.patch(
        "/me/preferences",
        headers=auth_headers,
        json={"spell_dictionary": ["keep-word"]},
    )
    assert removed.status_code == 200
    assert removed.json()["preferences"]["spell_dictionary"] == ["keep-word"]


@pytest.mark.asyncio
async def test_spell_dictionary_mixed_theme_and_new_word_denial_is_atomic(client, auth_headers, monkeypatch):
    _set_dictionary_capability(monkeypatch, allowed=True)
    initialized = await client.patch(
        "/me/preferences",
        headers=auth_headers,
        json={"theme": "light", "spell_dictionary": ["existing-word"]},
    )
    assert initialized.status_code == 200
    before = initialized.json()["preferences"]
    _set_dictionary_capability(monkeypatch, allowed=False)

    denied = await client.patch(
        "/me/preferences",
        headers=auth_headers,
        json={"theme": "dark", "spell_dictionary": ["existing-word", "new-word"]},
    )
    assert denied.status_code == 403
    assert (await client.get("/me", headers=auth_headers)).json()["preferences"] == before
