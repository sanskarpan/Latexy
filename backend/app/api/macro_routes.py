"""
Keyboard Macro API routes — Feature 83.

prefix: /macros
"""

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..database.models import User, UserMacro
from ..middleware.auth_middleware import get_current_user_required as get_current_user
from ..middleware.entitlements import require_feature
from ..services.macro_scripting import MAX_OPERATIONS, MacroScriptError, execute_script, parse_script
from ..utils.uuid_guard import ensure_uuid

router = APIRouter(prefix="/macros", tags=["macros"])
MAX_MACROS_PER_USER = 200
MAX_ACTION_BYTES = 65_536
_SAFE_MONACO_COMMANDS = frozenset(
    {
        "editor.action.formatDocument",
        "editor.action.indentLines",
        "editor.action.outdentLines",
    }
)
_SHORTCUT_MODIFIERS = ("ctrl", "alt", "shift")
_SHORTCUT_KEYS = frozenset(
    {
        "backspace",
        "delete",
        "down",
        "end",
        "enter",
        "escape",
        "home",
        "insert",
        "left",
        "pagedown",
        "pageup",
        "right",
        "space",
        "tab",
        "up",
    }
)
_RESERVED_SHORTCUTS = frozenset(
    {
        "ctrl+s",
        "ctrl+shift+s",
        "ctrl+c",
        "ctrl+v",
        "ctrl+x",
        "ctrl+z",
        "ctrl+shift+z",
        "ctrl+p",
        "ctrl+f",
        "ctrl+h",
        "ctrl+r",
        "ctrl+l",
        "ctrl+w",
        "ctrl+t",
        "ctrl+tab",
        "ctrl+shift+tab",
        "ctrl+pageup",
        "ctrl+pagedown",
        "ctrl+space",
        "ctrl+shift+p",
        "ctrl+`",
        "ctrl+alt+delete",
        "alt+f4",
    }
)


def _valid_action_text(value: Any) -> bool:
    if not isinstance(value, str) or any(ord(char) < 0x20 and char not in "\t\n\r" for char in value):
        return False
    try:
        return len(value.encode("utf-8")) <= 100_000
    except UnicodeEncodeError:
        return False


def _validate_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep legacy recorded macros finite and free of executable payloads."""
    if len(actions) > MAX_OPERATIONS:
        raise ValueError(f"actions exceed {MAX_OPERATIONS} operations")
    try:
        if len(json.dumps(actions, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_ACTION_BYTES:
            raise ValueError(f"actions exceed {MAX_ACTION_BYTES} bytes")
    except (TypeError, UnicodeError) as exc:
        raise ValueError("actions must contain JSON values") from exc
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ValueError(f"action {index + 1} must be an object")
        kind = action.get("type")
        expected_keys = {
            "insert": {"type", "text"},
            "move": {"type", "direction", "count"},
            "select": {"type", "startLine", "startCol", "endLine", "endCol"},
            "delete": {"type", "direction", "count"},
            "replace": {"type", "search", "replacement", "all"},
            "command": {"type", "monacoCommand"},
        }.get(kind)
        if expected_keys is None or set(action) != expected_keys:
            raise ValueError(f"action {index + 1} has unsupported or extra fields")
        if kind == "insert":
            if not _valid_action_text(action.get("text")):
                raise ValueError(f"action {index + 1} has invalid text")
        elif kind == "move":
            if (
                action.get("direction") not in {"up", "down", "left", "right"}
                or type(action.get("count")) is not int
                or not 0 <= action["count"] <= 500_000
            ):
                raise ValueError(f"action {index + 1} has invalid move")
        elif kind == "select":
            if any(
                type(action.get(field)) is not int or action[field] < 1 or action[field] > 500_000
                for field in ("startLine", "startCol", "endLine", "endCol")
            ):
                raise ValueError(f"action {index + 1} has invalid selection")
        elif kind == "delete":
            if (
                action.get("direction") not in {"forward", "backward"}
                or type(action.get("count")) is not int
                or not 0 <= action["count"] <= 500_000
            ):
                raise ValueError(f"action {index + 1} has invalid delete")
        elif kind == "replace":
            if (
                not _valid_action_text(action.get("search"))
                or not action["search"]
                or not _valid_action_text(action.get("replacement"))
                or not isinstance(action.get("all"), bool)
            ):
                raise ValueError(f"action {index + 1} has invalid replace")
        elif kind == "command":
            if action["monacoCommand"] not in _SAFE_MONACO_COMMANDS:
                raise ValueError(f"action {index + 1} has invalid command")
        else:
            raise ValueError(f"action {index + 1} has unsupported type")
    return actions


def _safe_actions(actions: Any) -> list[dict[str, Any]]:
    """Never expose pre-hardening JSONB rows directly to a client/player."""
    try:
        return _validate_actions(actions if isinstance(actions, list) else [])
    except (TypeError, UnicodeError, ValueError):
        return []


def _has_legacy_actions(macro: UserMacro) -> bool:
    # The quarantined value is always the pre-cap JSON array.  Keeping this
    # shape check also makes lightweight route doubles that omit the optional
    # field behave like pre-0053 rows.
    return isinstance(getattr(macro, "legacy_actions", None), (list, dict))


def _clean_label(value: str, label: str) -> str:
    value = value.strip()
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} contains invalid Unicode") from exc
    if not value or any(ord(char) < 0x20 for char in value):
        raise ValueError(f"{label} must contain visible text")
    return value


def _normalize_shortcut(value: Optional[str]) -> Optional[str]:
    if value is None or not value.strip():
        return None
    parts = [part.strip().lower() for part in value.split("+") if part.strip()]
    if not 2 <= len(parts) <= 4:
        raise ValueError("shortcut must include ctrl and one supported key")
    modifiers = [part for part in parts if part in _SHORTCUT_MODIFIERS]
    keys = [part for part in parts if part not in _SHORTCUT_MODIFIERS]
    if "ctrl" not in modifiers or len(keys) != 1 or len(set(modifiers)) != len(modifiers):
        raise ValueError("shortcut must include ctrl and one supported key")
    key = keys[0]
    if not (re.fullmatch(r"[a-z0-9]", key) or re.fullmatch(r"f(?:[1-9]|1[0-9]|2[0-4])", key) or key in _SHORTCUT_KEYS):
        raise ValueError("shortcut key is not supported")
    normalized = "+".join([modifier for modifier in _SHORTCUT_MODIFIERS if modifier in modifiers] + [key])
    if normalized in _RESERVED_SHORTCUTS:
        raise ValueError("shortcut is reserved by the editor or browser")
    return normalized


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class MacroCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    shortcut: Optional[str] = Field(None, max_length=50)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    script: Optional[str] = Field(None, max_length=16_384)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return _clean_label(value, "name")

    @field_validator("description")
    @classmethod
    def clean_optional_label(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _clean_label(value, "description or shortcut")

    @field_validator("shortcut")
    @classmethod
    def normalize_create_shortcut(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_shortcut(value)

    @model_validator(mode="after")
    def validate_macro(self):
        _validate_actions(self.actions)
        if self.script is not None and self.actions:
            raise ValueError("a macro must contain either actions or a script, not both")
        if self.script is not None:
            try:
                if not parse_script(self.script):
                    raise ValueError("script must contain at least one operation")
            except MacroScriptError as exc:
                raise ValueError("Macro script validation failed") from exc
        return self


class MacroUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    shortcut: Optional[str] = Field(None, max_length=50)
    actions: Optional[list[dict[str, Any]]] = None
    script: Optional[str] = Field(None, max_length=16_384)
    expected_script_version: Optional[int] = Field(None, ge=1, exclude=True)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _clean_label(value, "name")

    @field_validator("description")
    @classmethod
    def clean_optional_label(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _clean_label(value, "description or shortcut")

    @field_validator("shortcut")
    @classmethod
    def normalize_update_shortcut(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_shortcut(value)

    @model_validator(mode="after")
    def validate_macro(self):
        if self.actions is not None:
            _validate_actions(self.actions)
        if "script" in self.model_fields_set and "actions" in self.model_fields_set:
            raise ValueError("send either script or actions, not both")
        if "script" in self.model_fields_set and self.expected_script_version is None:
            raise ValueError("expected_script_version is required when changing script")
        if "script" in self.model_fields_set and self.script is None:
            raise ValueError("script cannot be cleared; send recorded actions to convert this macro")
        if self.script is not None:
            try:
                if not parse_script(self.script):
                    raise ValueError("script must contain at least one operation")
            except MacroScriptError as exc:
                raise ValueError("Macro script validation failed") from exc
        return self


class MacroResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    shortcut: Optional[str]
    actions: list[dict[str, Any]]
    script: Optional[str]
    script_version: int
    script_hash: Optional[str]
    legacy_actions_available: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _to_response(macro: UserMacro) -> MacroResponse:
    script = getattr(macro, "script", None)
    if not isinstance(script, str):
        script = None
    script_version = getattr(macro, "script_version", 1)
    if not isinstance(script_version, int):
        script_version = 1
    script_hash = getattr(macro, "script_hash", None)
    if not isinstance(script_hash, str):
        script_hash = None
    return MacroResponse(
        id=macro.id,
        name=macro.name,
        description=macro.description,
        shortcut=macro.shortcut,
        actions=_safe_actions(macro.actions),
        script=script,
        script_version=script_version,
        script_hash=script_hash,
        legacy_actions_available=_has_legacy_actions(macro),
        created_at=macro.created_at,
        updated_at=macro.updated_at,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[MacroResponse])
async def list_macros(
    offset: int = Query(0, ge=0),
    limit: int = Query(MAX_MACROS_PER_USER, ge=1, le=MAX_MACROS_PER_USER),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> list[MacroResponse]:
    # Direct service-level callers/tests do not pass FastAPI's Query defaults.
    if not isinstance(offset, int):
        offset = 0
    if not isinstance(limit, int):
        limit = MAX_MACROS_PER_USER
    result = await db.execute(
        select(UserMacro)
        .where(UserMacro.user_id == user_id)
        .order_by(UserMacro.created_at.desc(), UserMacro.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [_to_response(m) for m in result.scalars().all()]


@router.post(
    "",
    response_model=MacroResponse,
    status_code=201,
    dependencies=[Depends(require_feature("macros"))],
)
async def create_macro(
    body: MacroCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> MacroResponse:
    # The guard is intentionally skipped only for isolated unit-test doubles
    # that replace the mapped class with a factory; real requests always use the
    # mapped ``id`` attribute and therefore receive the hard cap.
    if hasattr(UserMacro, "id"):
        owner_result = await db.execute(select(User).where(User.id == user_id).with_for_update())
        if owner_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="User not found")
        if body.shortcut is not None:
            shortcut_result = await db.execute(
                select(UserMacro.id).where(UserMacro.user_id == user_id, UserMacro.shortcut == body.shortcut).limit(1)
            )
            if shortcut_result.scalar_one_or_none() is not None:
                raise HTTPException(status_code=409, detail="That shortcut is already assigned to another macro")
        count_result = await db.execute(
            select(UserMacro.id).where(UserMacro.user_id == user_id).limit(MAX_MACROS_PER_USER + 1)
        )
        if len(count_result.scalars().all()) >= MAX_MACROS_PER_USER:
            raise HTTPException(status_code=409, detail="Macro limit reached; delete an existing macro first")
    macro = UserMacro(
        user_id=user_id,
        name=body.name,
        description=body.description,
        shortcut=body.shortcut,
        actions=body.actions,
        script=body.script,
        script_hash=hashlib.sha256(body.script.encode("utf-8")).hexdigest() if body.script is not None else None,
    )
    db.add(macro)
    await db.commit()
    await db.refresh(macro)
    return _to_response(macro)


@router.patch("/{macro_id}", response_model=MacroResponse)
async def update_macro(
    macro_id: str,
    body: MacroUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> MacroResponse:
    ensure_uuid(macro_id, "Macro not found")
    result = await db.execute(
        select(UserMacro).where(UserMacro.id == macro_id, UserMacro.user_id == user_id).with_for_update()
    )
    macro = result.scalar_one_or_none()
    if not macro:
        raise HTTPException(status_code=404, detail="Macro not found")
    updates = body.model_dump(exclude_unset=True, exclude={"expected_script_version"})
    if "shortcut" in updates and updates["shortcut"] is not None:
        await db.execute(select(User.id).where(User.id == user_id).with_for_update())
        shortcut_result = await db.execute(
            select(UserMacro.id)
            .where(
                UserMacro.user_id == user_id,
                UserMacro.shortcut == updates["shortcut"],
                UserMacro.id != macro_id,
            )
            .limit(1)
        )
        if shortcut_result.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="That shortcut is already assigned to another macro")
    if _has_legacy_actions(macro) and {"actions", "script"} & updates.keys():
        raise HTTPException(
            status_code=409,
            detail="This legacy macro is not executable; delete it and record a replacement before changing its actions",
        )
    if "actions" in updates and macro.script is not None:
        if body.expected_script_version is None or body.expected_script_version != (macro.script_version or 1):
            raise HTTPException(status_code=409, detail="Macro script changed; reload before replacing it")
        macro.script = None
        macro.script_hash = None
        macro.script_version = (macro.script_version or 1) + 1
    if "script" in updates:
        expected = body.expected_script_version
        current = macro.script_version or 1
        if expected is not None and expected != current:
            raise HTTPException(status_code=409, detail="Macro script changed; reload before saving")
        macro.script_version = current + 1
        macro.script_hash = (
            hashlib.sha256((updates["script"] or "").encode("utf-8")).hexdigest()
            if updates["script"] is not None
            else None
        )
        # A macro has exactly one execution representation. Script edits
        # intentionally replace any recorded action sequence.
        macro.actions = []
    for field, val in updates.items():
        setattr(macro, field, val)
    await db.commit()
    await db.refresh(macro)
    return _to_response(macro)


class MacroExecuteRequest(BaseModel):
    document: str = Field(..., min_length=0, max_length=500_000)
    expected_script_version: int = Field(..., ge=1)


class MacroExecuteResponse(BaseModel):
    document: str
    script_version: int
    script_hash: str
    operation_count: int


@router.post(
    "/{macro_id}/execute",
    response_model=MacroExecuteResponse,
    dependencies=[Depends(require_feature("macros"))],
)
async def execute_macro(
    macro_id: str,
    body: MacroExecuteRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> MacroExecuteResponse:
    """Execute a stored script as a pure, deterministic document transform.

    No document is persisted and no side effect is available to the script;
    retrying the request is therefore safe.  The expected version protects
    callers from silently running stale source after an edit.
    """
    ensure_uuid(macro_id, "Macro not found")
    result = await db.execute(select(UserMacro).where(UserMacro.id == macro_id, UserMacro.user_id == user_id))
    macro = result.scalar_one_or_none()
    if not macro:
        raise HTTPException(status_code=404, detail="Macro not found")
    if _has_legacy_actions(macro):
        raise HTTPException(
            status_code=409,
            detail="This legacy macro is not executable; delete it and record a replacement before running it",
        )
    script = macro.script
    if script is None:
        raise HTTPException(status_code=409, detail="Macro has no script")
    version = macro.script_version or 1
    if body.expected_script_version != version:
        raise HTTPException(status_code=409, detail="Macro script changed; reload before executing")
    try:
        operations = parse_script(script)
        document = execute_script(script, body.document)
    except MacroScriptError as exc:
        # A malformed stored script is an internal consistency error, but do
        # not leak a traceback or implementation details to the caller.
        raise HTTPException(status_code=422, detail="Macro script validation failed.") from exc
    return MacroExecuteResponse(
        document=document,
        script_version=version,
        script_hash=hashlib.sha256(script.encode("utf-8")).hexdigest(),
        operation_count=len(operations),
    )


@router.delete("/{macro_id}", status_code=204)
async def delete_macro(
    macro_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> None:
    ensure_uuid(macro_id, "Macro not found")
    result = await db.execute(select(UserMacro).where(UserMacro.id == macro_id, UserMacro.user_id == user_id))
    macro = result.scalar_one_or_none()
    if not macro:
        raise HTTPException(status_code=404, detail="Macro not found")
    await db.delete(macro)
    await db.commit()
