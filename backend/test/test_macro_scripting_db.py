"""Database-backed B53c contracts (migration, ownership, versioning)."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app.api.macro_routes import (
    MacroCreate,
    MacroExecuteRequest,
    MacroUpdate,
    create_macro,
    delete_macro,
    execute_macro,
    list_macros,
    update_macro,
)
from app.database.models import User, UserMacro


@pytest.mark.asyncio
async def test_script_lifecycle_is_persisted_and_stale_execution_is_rejected(db_session):
    user_id = str(uuid.uuid4())
    db_session.add(User(id=user_id, email=f"test_macro_{user_id}@example.com", name="Macro test"))
    await db_session.commit()

    created = await create_macro(
        MacroCreate(name="Safe", actions=[], script='replace "old" with "new" all'),
        db_session,
        user_id,
    )
    assert created.script_version == 1
    assert len(created.script_hash or "") == 64
    shortcut_macro = await create_macro(
        MacroCreate(name="Shortcut", shortcut="SHIFT+CTRL+Q", actions=[{"type": "insert", "text": "x"}]),
        db_session,
        user_id,
    )
    assert shortcut_macro.shortcut == "ctrl+shift+q"
    with pytest.raises(HTTPException) as duplicate:
        await create_macro(
            MacroCreate(name="Duplicate shortcut", shortcut="ctrl+shift+q", actions=[]),
            db_session,
            user_id,
        )
    assert duplicate.value.status_code == 409
    result = await execute_macro(
        created.id,
        MacroExecuteRequest(document="old old", expected_script_version=1),
        db_session,
        user_id,
    )
    assert result.document == "new new"

    updated = await update_macro(
        created.id,
        MacroUpdate(script='append "!"', expected_script_version=1),
        db_session,
        user_id,
    )
    assert updated.script_version == 2

    converted = await update_macro(
        created.id,
        MacroUpdate(actions=[{"type": "insert", "text": "prefix"}], expected_script_version=2),
        db_session,
        user_id,
    )
    assert converted.script is None and converted.actions == [{"type": "insert", "text": "prefix"}]

    recorded = await create_macro(
        MacroCreate(name="Recorded", actions=[{"type": "insert", "text": "prefix"}]),
        db_session,
        user_id,
    )
    with pytest.raises(HTTPException) as duplicate_update:
        await update_macro(
            recorded.id,
            MacroUpdate(shortcut="ctrl+shift+q"),
            db_session,
            user_id,
        )
    assert duplicate_update.value.status_code == 409
    cleared = await update_macro(recorded.id, MacroUpdate(shortcut=None), db_session, user_id)
    assert cleared.shortcut is None
    converted_to_script = await update_macro(
        recorded.id,
        MacroUpdate(script='append "!"', expected_script_version=1),
        db_session,
        user_id,
    )
    assert converted_to_script.script == 'append "!"'
    assert converted_to_script.actions == []

    other_id = str(uuid.uuid4())
    db_session.add(User(id=other_id, email=f"test_macro_other_{other_id}@example.com", name="Other"))
    await db_session.commit()
    with pytest.raises(Exception) as private:
        await execute_macro(
            created.id,
            MacroExecuteRequest(document="x", expected_script_version=2),
            db_session,
            other_id,
        )
    assert getattr(private.value, "status_code", None) == 404

    with pytest.raises(Exception) as stale:
        await execute_macro(
            created.id,
            MacroExecuteRequest(document="x", expected_script_version=1),
            db_session,
            user_id,
        )
    assert getattr(stale.value, "status_code", None) == 409
    await db_session.execute(delete(User).where(User.id == user_id))
    await db_session.execute(delete(User).where(User.id == other_id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_quarantined_legacy_macro_is_stateful_but_not_executable(db_session):
    user_id = str(uuid.uuid4())
    db_session.add(User(id=user_id, email=f"test_macro_legacy_{user_id}@example.com", name="Legacy test"))
    await db_session.commit()

    legacy = await create_macro(
        MacroCreate(name="Old recording", actions=[{"type": "insert", "text": "hidden"}]),
        db_session,
        user_id,
    )
    row = await db_session.get(UserMacro, legacy.id)
    assert row is not None
    row.actions = []
    row.legacy_actions = [{"type": "insert", "text": "hidden"}] * 256
    await db_session.commit()

    listed = await list_macros(db=db_session, user_id=user_id)
    response = next(item for item in listed if item.id == legacy.id)
    assert response.legacy_actions_available is True
    assert response.actions == []
    assert not hasattr(response, "legacy_actions")

    renamed = await update_macro(
        legacy.id,
        MacroUpdate(name="Replacement required"),
        db_session,
        user_id,
    )
    assert renamed.name == "Replacement required"

    with pytest.raises(Exception) as action_update:
        await update_macro(
            legacy.id,
            MacroUpdate(actions=[{"type": "insert", "text": "new"}]),
            db_session,
            user_id,
        )
    assert getattr(action_update.value, "status_code", None) == 409

    with pytest.raises(Exception) as script_update:
        await update_macro(
            legacy.id,
            MacroUpdate(script='append "!"', expected_script_version=1),
            db_session,
            user_id,
        )
    assert getattr(script_update.value, "status_code", None) == 409

    with pytest.raises(Exception) as execution:
        await execute_macro(
            legacy.id,
            MacroExecuteRequest(document="x", expected_script_version=1),
            db_session,
            user_id,
        )
    assert getattr(execution.value, "status_code", None) == 409

    assert await delete_macro(legacy.id, db_session, user_id) is None
    assert await db_session.get(UserMacro, legacy.id) is None
    await db_session.execute(delete(User).where(User.id == user_id))
    await db_session.commit()
