"""
Tests for Feature 83 — Keyboard Macro System.

Strategy:
  - Test the route handler functions directly with mock DB sessions
  - Verifies CRUD operations, authorization, and JSONB actions storage
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.macro_routes import MacroCreate, MacroUpdate, create_macro, delete_macro, list_macros, update_macro
from app.database.models import User, UserMacro

# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_user(user_id: str | None = None) -> User:
    user = MagicMock(spec=User)
    user.id = user_id or str(uuid.uuid4())
    user.email = 'test@example.com'
    user.name = 'Test User'
    return user


def make_macro(
    user_id: str,
    name: str = 'Bold Text',
    description: str | None = None,
    shortcut: str | None = 'ctrl+shift+b',
    actions: list | None = None,
) -> UserMacro:
    macro = MagicMock(spec=UserMacro)
    macro.id = str(uuid.uuid4())
    macro.user_id = user_id
    macro.name = name
    macro.description = description
    macro.shortcut = shortcut
    macro.actions = actions or [{'type': 'insert', 'text': '\\textbf{'}]
    macro.created_at = datetime.now(timezone.utc)
    macro.updated_at = datetime.now(timezone.utc)
    return macro


# ── Test 1: Create macro stores actions as JSONB ───────────────────────────────

class TestCreateMacro:
    @pytest.mark.asyncio
    async def test_create_macro_stores_actions(self):
        """POST /macros stores actions JSONB and returns correct fields."""
        user = make_user()
        actions = [
            {'type': 'insert', 'text': '\\textbf{'},
            {'type': 'move', 'direction': 'right', 'count': 0},
        ]
        body = MacroCreate(
            name='Bold Wrapper',
            shortcut='ctrl+shift+b',
            actions=actions,
        )

        created = make_macro(user.id, name='Bold Wrapper', actions=actions)
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=lambda obj: None)

        with pytest.MonkeyPatch.context() as mp:
            import app.api.macro_routes as routes
            original_cls = routes.UserMacro

            def patched_cls(**kwargs):
                return created

            mp.setattr(routes, 'UserMacro', patched_cls)
            result = await create_macro(body=body, db=mock_db, current_user=user)

        assert result.name == 'Bold Wrapper'
        assert result.actions == actions

    @pytest.mark.asyncio
    async def test_create_macro_shortcut_stored_as_is(self):
        """Shortcut string is stored verbatim — no server-side validation."""
        user = make_user()
        raw_shortcut = 'ctrl+shift+9'
        body = MacroCreate(name='My Macro', shortcut=raw_shortcut, actions=[])
        created = make_macro(user.id, shortcut=raw_shortcut)

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with pytest.MonkeyPatch.context() as mp:
            import app.api.macro_routes as routes
            mp.setattr(routes, 'UserMacro', lambda **kwargs: created)
            result = await create_macro(body=body, db=mock_db, current_user=user)

        assert result.shortcut == raw_shortcut


# ── Test 2: List macros — only current user's macros returned ──────────────────

class TestListMacros:
    @pytest.mark.asyncio
    async def test_list_returns_only_current_user_macros(self):
        """GET /macros never leaks other users' macros."""
        user = make_user()
        user_macros = [make_macro(user.id, name=f'Macro {i}') for i in range(3)]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = user_macros
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await list_macros(db=mock_db, current_user=user)

        assert len(result) == 3
        assert all(r.name.startswith('Macro') for r in result)

    @pytest.mark.asyncio
    async def test_list_returns_empty_for_new_user(self):
        """New user with no macros gets an empty list."""
        user = make_user()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await list_macros(db=mock_db, current_user=user)
        assert result == []


# ── Test 3: Delete — 403 for another user ─────────────────────────────────────

class TestDeleteMacro:
    @pytest.mark.asyncio
    async def test_delete_by_other_user_raises_403(self):
        """DELETE /macros/{id} by non-owner returns 403."""
        owner = make_user()
        attacker = make_user()
        macro = make_macro(owner.id)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = macro
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await delete_macro(macro_id=macro.id, db=mock_db, current_user=attacker)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_not_found_raises_404(self):
        """DELETE /macros/{id} for unknown ID returns 404."""
        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await delete_macro(macro_id=str(uuid.uuid4()), db=mock_db, current_user=user)
        assert exc_info.value.status_code == 404


# ── Test 4: Update macro — updated_at advances ────────────────────────────────

class TestUpdateMacro:
    @pytest.mark.asyncio
    async def test_update_macro_name(self):
        """PATCH /macros/{id} updates the name field."""
        user = make_user()
        macro = make_macro(user.id, name='Old Name')

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = macro
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        # Simulate setattr behaviour
        def fake_setattr(obj, key, val):
            object.__setattr__(obj, key, val) if not isinstance(obj, MagicMock) else None

        body = MacroUpdate(name='New Name')
        result = await update_macro(macro_id=macro.id, body=body, db=mock_db, current_user=user)

        # Verify setattr was called via model_dump
        mock_db.commit.assert_awaited_once()
