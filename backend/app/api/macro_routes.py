"""
Keyboard Macro CRUD API — Feature 83E.

Endpoints (all require authentication):
  GET    /macros            — list user's macros (summaries, no actions payload)
  POST   /macros            — create a new macro
  GET    /macros/{macro_id} — fetch a single macro with full actions
  PATCH  /macros/{macro_id} — update name/description/shortcut/actions
  DELETE /macros/{macro_id} — delete a macro

Per-user limit: 50 macros max.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..database.models import UserMacro
from ..middleware.auth_middleware import get_current_user_required

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/macros", tags=["macros"])

MAX_MACROS_PER_USER = 50


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class MacroSummaryResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    shortcut: Optional[str]
    created_at: str
    updated_at: str


class MacroDetailResponse(MacroSummaryResponse):
    actions: List[Any]


class CreateMacroRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    shortcut: Optional[str] = Field(None, max_length=50)
    actions: List[Any] = Field(..., min_length=1)


class UpdateMacroRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    shortcut: Optional[str] = None
    actions: Optional[List[Any]] = Field(None, min_length=1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _summary(m: UserMacro) -> MacroSummaryResponse:
    return MacroSummaryResponse(
        id=m.id,
        name=m.name,
        description=m.description,
        shortcut=m.shortcut,
        created_at=m.created_at.isoformat(),
        updated_at=m.updated_at.isoformat(),
    )


def _detail(m: UserMacro) -> MacroDetailResponse:
    return MacroDetailResponse(
        id=m.id,
        name=m.name,
        description=m.description,
        shortcut=m.shortcut,
        actions=m.actions if isinstance(m.actions, list) else [],
        created_at=m.created_at.isoformat(),
        updated_at=m.updated_at.isoformat(),
    )


async def _get_macro_or_404(
    macro_id: str, user_id: str, db: AsyncSession
) -> UserMacro:
    result = await db.execute(
        select(UserMacro).where(
            UserMacro.id == macro_id, UserMacro.user_id == user_id
        )
    )
    macro = result.scalar_one_or_none()
    if macro is None:
        raise HTTPException(status_code=404, detail="Macro not found")
    return macro


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[MacroSummaryResponse])
async def list_macros(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> List[MacroSummaryResponse]:
    """Return all macros for the authenticated user (no actions payload)."""
    result = await db.execute(
        select(UserMacro)
        .where(UserMacro.user_id == user_id)
        .order_by(UserMacro.created_at.desc())
    )
    macros = result.scalars().all()
    return [_summary(m) for m in macros]


@router.post("", response_model=MacroDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_macro(
    body: CreateMacroRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> MacroDetailResponse:
    """Create a new macro. Fails with 429 if the user already has 50 macros."""
    count_result = await db.execute(
        select(UserMacro).where(UserMacro.user_id == user_id)
    )
    count = len(count_result.scalars().all())
    if count >= MAX_MACROS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Maximum {MAX_MACROS_PER_USER} macros per user",
        )

    macro = UserMacro(
        user_id=user_id,
        name=body.name,
        description=body.description,
        shortcut=body.shortcut,
        actions=body.actions,
    )
    db.add(macro)
    await db.commit()
    await db.refresh(macro)
    return _detail(macro)


@router.get("/{macro_id}", response_model=MacroDetailResponse)
async def get_macro(
    macro_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> MacroDetailResponse:
    """Return a single macro with full actions payload."""
    macro = await _get_macro_or_404(macro_id, user_id, db)
    return _detail(macro)


@router.patch("/{macro_id}", response_model=MacroDetailResponse)
async def update_macro(
    macro_id: str,
    body: UpdateMacroRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> MacroDetailResponse:
    """Partially update a macro's fields."""
    macro = await _get_macro_or_404(macro_id, user_id, db)

    if body.name is not None:
        macro.name = body.name
    if body.description is not None:
        macro.description = body.description
    if body.shortcut is not None:
        macro.shortcut = body.shortcut
    if body.actions is not None:
        macro.actions = body.actions

    await db.commit()
    await db.refresh(macro)
    return _detail(macro)


@router.delete("/{macro_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_macro(
    macro_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> None:
    """Delete a macro."""
    macro = await _get_macro_or_404(macro_id, user_id, db)
    await db.delete(macro)
    await db.commit()
