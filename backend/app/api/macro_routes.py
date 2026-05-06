"""
Keyboard Macro API routes — Feature 83.

prefix: /macros
"""

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..database.models import User, UserMacro
from ..middleware.auth_middleware import get_current_user_required as get_current_user

router = APIRouter(prefix='/macros', tags=['macros'])


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class MacroCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    shortcut: Optional[str] = Field(None, max_length=50)
    actions: list[dict[str, Any]] = Field(default=[])


class MacroUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    shortcut: Optional[str] = Field(None, max_length=50)
    actions: Optional[list[dict[str, Any]]] = None


class MacroResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    shortcut: Optional[str]
    actions: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    model_config = {'from_attributes': True}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_response(macro: UserMacro) -> MacroResponse:
    return MacroResponse(
        id=macro.id,
        name=macro.name,
        description=macro.description,
        shortcut=macro.shortcut,
        actions=macro.actions or [],
        created_at=macro.created_at,
        updated_at=macro.updated_at,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get('', response_model=list[MacroResponse])
async def list_macros(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MacroResponse]:
    result = await db.execute(
        select(UserMacro)
        .where(UserMacro.user_id == current_user.id)
        .order_by(UserMacro.created_at.desc())
    )
    return [_to_response(m) for m in result.scalars().all()]


@router.post('', response_model=MacroResponse, status_code=201)
async def create_macro(
    body: MacroCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MacroResponse:
    macro = UserMacro(
        user_id=current_user.id,
        name=body.name,
        description=body.description,
        shortcut=body.shortcut,
        actions=body.actions,
    )
    db.add(macro)
    await db.commit()
    await db.refresh(macro)
    return _to_response(macro)


@router.patch('/{macro_id}', response_model=MacroResponse)
async def update_macro(
    macro_id: str,
    body: MacroUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MacroResponse:
    result = await db.execute(select(UserMacro).where(UserMacro.id == macro_id))
    macro = result.scalar_one_or_none()
    if not macro:
        raise HTTPException(status_code=404, detail='Macro not found')
    if macro.user_id != current_user.id:
        raise HTTPException(status_code=403, detail='Access denied')
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(macro, field, val)
    await db.commit()
    await db.refresh(macro)
    return _to_response(macro)


@router.delete('/{macro_id}', status_code=204)
async def delete_macro(
    macro_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(select(UserMacro).where(UserMacro.id == macro_id))
    macro = result.scalar_one_or_none()
    if not macro:
        raise HTTPException(status_code=404, detail='Macro not found')
    if macro.user_id != current_user.id:
        raise HTTPException(status_code=403, detail='Access denied')
    await db.delete(macro)
    await db.commit()
