"""Adversarial coverage for the bounded B53c macro DSL."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.macro_routes import MacroCreate, MacroExecuteRequest, MacroUpdate, execute_macro
from app.services.macro_scripting import (
    MAX_LINES,
    MAX_OPERATIONS,
    MAX_SOURCE_BYTES,
    MacroScriptError,
    execute_script,
    parse_script,
)


def test_deterministic_transform_and_no_cursor_state():
    source = 'replace "old" with "new" all\nprepend "HEADER "'
    assert execute_script(source, "old old") == "HEADER new new"
    assert execute_script(source, "old old") == execute_script(source, "old old")


@pytest.mark.parametrize(
    "source",
    [
        "import os",
        'exec "print(1)"',
        'replace "x" with "y" loop',
        "move 1 sideways",
        "delete-prefix nope",
        'prepend "unterminated',
    ],
)
def test_unknown_or_malformed_language_fails_closed(source):
    with pytest.raises(MacroScriptError):
        parse_script(source)


def test_source_line_and_operation_limits():
    with pytest.raises(MacroScriptError):
        parse_script(('prepend "x"\n' * (MAX_LINES + 1)).strip())
    with pytest.raises(MacroScriptError):
        parse_script(('prepend "x"\n' * (MAX_OPERATIONS + 1)).strip())
    with pytest.raises(MacroScriptError):
        parse_script('prepend "' + ("x" * MAX_SOURCE_BYTES) + '"')


def test_input_and_output_limits_are_enforced():
    with pytest.raises(MacroScriptError):
        execute_script('prepend "x"', "x" * 500_001)
    with pytest.raises(MacroScriptError):
        execute_script('prepend "x"', "x" * 500_000)
    with pytest.raises(MacroScriptError, match="invalid Unicode"):
        execute_script('append "x"', "bad\ud800")


def test_legacy_actions_and_script_updates_are_bounded_and_versioned():
    with pytest.raises(ValidationError):
        MacroCreate(name="Too many", actions=[{"type": "insert", "text": "x"}] * 129)
    with pytest.raises(ValidationError):
        MacroCreate(name="Bad command", actions=[{"type": "command", "monacoCommand": "../../escape"}])
    with pytest.raises(ValidationError):
        MacroCreate(name="Extra", actions=[{"type": "insert", "text": "x", "extra": True}])
    with pytest.raises(ValidationError):
        MacroCreate(name="Ambiguous", actions=[{"type": "insert", "text": "x"}], script='append "x"')
    with pytest.raises(ValidationError):
        MacroCreate(name=" ", actions=[])
    with pytest.raises(ValidationError):
        MacroUpdate(script='append "x"')
    with pytest.raises(ValidationError, match="script cannot be cleared"):
        MacroUpdate(script=None, expected_script_version=1)
    with pytest.raises(ValidationError):
        MacroCreate(name="Empty", actions=[], script="# only a comment")
    assert MacroCreate(name="Canonical", shortcut="SHIFT+CTRL+Q").shortcut == "ctrl+shift+q"
    for shortcut in ("ctrl+s", "ctrl+ctrl+q", "meta+q", "ctrl+not-a-key"):
        with pytest.raises(ValidationError):
            MacroCreate(name="Invalid shortcut", shortcut=shortcut)


@pytest.mark.asyncio
async def test_execute_route_is_owner_and_version_scoped():
    owner_id = str(uuid.uuid4())
    macro = MagicMock()
    macro.id = str(uuid.uuid4())
    macro.user_id = owner_id
    macro.script = 'replace "old" with "new"'
    macro.script_version = 3
    result = MagicMock()
    result.scalar_one_or_none.return_value = macro
    db = AsyncMock()
    db.execute.return_value = result

    out = await execute_macro(
        macro_id=macro.id,
        body=MacroExecuteRequest(document="old", expected_script_version=3),
        db=db,
        user_id=owner_id,
    )
    assert out.document == "new"
    assert out.script_version == 3
    assert out.operation_count == 1

    db.execute.return_value = result
    with pytest.raises(HTTPException) as exc:
        await execute_macro(
            macro_id=macro.id,
            body=MacroExecuteRequest(document="old", expected_script_version=2),
            db=db,
            user_id=owner_id,
        )
    assert exc.value.status_code == 409

    private_result = MagicMock()
    private_result.scalar_one_or_none.return_value = None
    db.execute.return_value = private_result
    with pytest.raises(HTTPException) as exc:
        await execute_macro(
            macro_id=macro.id,
            body=MacroExecuteRequest(document="old", expected_script_version=3),
            db=db,
            user_id=str(uuid.uuid4()),
        )
    assert exc.value.status_code == 404
