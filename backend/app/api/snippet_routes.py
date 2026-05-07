"""
Snippet Marketplace API routes — Feature 82.

prefix: /snippets
"""

import re
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..data.official_snippets import OFFICIAL_SNIPPETS
from ..database.connection import get_db
from ..database.models import Snippet, SnippetInstall, SnippetUpvote, User
from ..middleware.auth_middleware import (
    get_current_user_optional,
)
from ..middleware.auth_middleware import (
    get_current_user_required as get_current_user,
)

router = APIRouter(prefix='/snippets', tags=['snippets'])
admin_router = APIRouter(prefix='/admin', tags=['admin'])

# ── Security ──────────────────────────────────────────────────────────────────

_DANGEROUS_PATTERNS = [
    r'\\write18',
    r'\\input\{/',
    r'\\input\{\\',
    r'\\immediate\\write',
    r'\\openout',
    r'\\openin',
    r'\\read\s',
    r'\\typein',
    r'\\ShellEscape',
]
_DANGER_RE = re.compile('|'.join(_DANGEROUS_PATTERNS), re.IGNORECASE)


def _check_content_safety(content: str) -> None:
    """Raise 422 if content contains shell-injection patterns."""
    if _DANGER_RE.search(content):
        raise HTTPException(
            status_code=422,
            detail='Snippet content contains disallowed LaTeX commands that could execute shell commands.',
        )


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class SnippetCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=100)
    description: str = Field(..., min_length=10, max_length=500)
    content: str = Field(..., min_length=10, max_length=10_000)
    category: Literal['header', 'experience', 'skills', 'education', 'misc']
    tags: list[str] = Field(default=[], max_items=10)

    @field_validator('tags')
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        return [t.strip().lower()[:50] for t in v if t.strip()]


class SnippetUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=100)
    description: Optional[str] = Field(None, min_length=10, max_length=500)
    content: Optional[str] = Field(None, min_length=10, max_length=10_000)
    category: Optional[Literal['header', 'experience', 'skills', 'education', 'misc']] = None
    tags: Optional[list[str]] = None


class SnippetResponse(BaseModel):
    id: str
    title: str
    description: str
    content: str
    category: str
    tags: list[str]
    is_official: bool
    installs_count: int
    upvotes_count: int
    author_name: Optional[str]
    created_at: datetime
    installed_by_me: bool
    upvoted_by_me: bool

    model_config = {'from_attributes': True}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _build_response(
    snippet: Snippet,
    user_id: Optional[str],
    db: AsyncSession,
) -> SnippetResponse:
    installed_by_me = False
    upvoted_by_me = False
    if user_id:
        inst = await db.execute(
            select(SnippetInstall).where(
                SnippetInstall.snippet_id == snippet.id,
                SnippetInstall.user_id == user_id,
            )
        )
        installed_by_me = inst.scalar_one_or_none() is not None

        upv = await db.execute(
            select(SnippetUpvote).where(
                SnippetUpvote.snippet_id == snippet.id,
                SnippetUpvote.user_id == user_id,
            )
        )
        upvoted_by_me = upv.scalar_one_or_none() is not None

    author_name: Optional[str] = None
    if snippet.author_id:
        author_res = await db.execute(select(User).where(User.id == snippet.author_id))
        author = author_res.scalar_one_or_none()
        if author:
            author_name = author.name or author.email

    return SnippetResponse(
        id=snippet.id,
        title=snippet.title,
        description=snippet.description,
        content=snippet.content,
        category=snippet.category,
        tags=snippet.tags or [],
        is_official=snippet.is_official,
        installs_count=snippet.installs_count,
        upvotes_count=snippet.upvotes_count,
        author_name=author_name,
        created_at=snippet.created_at,
        installed_by_me=installed_by_me,
        upvoted_by_me=upvoted_by_me,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get('', response_model=list[SnippetResponse])
async def list_snippets(
    category: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    sort: Literal['popular', 'newest', 'official'] = Query('popular'),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> list[SnippetResponse]:
    stmt = select(Snippet)
    if category:
        stmt = stmt.where(Snippet.category == category)
    if q:
        q_lower = f'%{q.lower()}%'
        stmt = stmt.where(
            func.lower(Snippet.title).like(q_lower)
            | func.lower(Snippet.description).like(q_lower)
        )
    if sort == 'popular':
        stmt = stmt.order_by(Snippet.installs_count.desc(), Snippet.created_at.desc())
    elif sort == 'official':
        stmt = stmt.order_by(Snippet.is_official.desc(), Snippet.installs_count.desc())
    else:
        stmt = stmt.order_by(Snippet.created_at.desc())
    stmt = stmt.offset(offset).limit(limit)

    result = await db.execute(stmt)
    snippets = result.scalars().all()
    user_id = current_user.id if current_user else None
    return [await _build_response(s, user_id, db) for s in snippets]


@router.get('/{snippet_id}', response_model=SnippetResponse)
async def get_snippet(
    snippet_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> SnippetResponse:
    result = await db.execute(select(Snippet).where(Snippet.id == snippet_id))
    snippet = result.scalar_one_or_none()
    if not snippet:
        raise HTTPException(status_code=404, detail='Snippet not found')
    user_id = current_user.id if current_user else None
    return await _build_response(snippet, user_id, db)


@router.post('', response_model=SnippetResponse, status_code=201)
async def create_snippet(
    body: SnippetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SnippetResponse:
    _check_content_safety(body.content)
    snippet = Snippet(
        author_id=current_user.id,
        title=body.title,
        description=body.description,
        content=body.content,
        category=body.category,
        tags=body.tags,
        is_official=False,
    )
    db.add(snippet)
    await db.commit()
    await db.refresh(snippet)
    return await _build_response(snippet, current_user.id, db)


@router.patch('/{snippet_id}', response_model=SnippetResponse)
async def update_snippet(
    snippet_id: str,
    body: SnippetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SnippetResponse:
    result = await db.execute(select(Snippet).where(Snippet.id == snippet_id))
    snippet = result.scalar_one_or_none()
    if not snippet:
        raise HTTPException(status_code=404, detail='Snippet not found')
    if snippet.author_id != current_user.id:
        raise HTTPException(status_code=403, detail='Only the author can update this snippet')
    if body.content:
        _check_content_safety(body.content)
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(snippet, field, val)
    await db.commit()
    await db.refresh(snippet)
    return await _build_response(snippet, current_user.id, db)


@router.delete('/{snippet_id}', status_code=204)
async def delete_snippet(
    snippet_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(select(Snippet).where(Snippet.id == snippet_id))
    snippet = result.scalar_one_or_none()
    if not snippet:
        raise HTTPException(status_code=404, detail='Snippet not found')
    if snippet.author_id != current_user.id:
        raise HTTPException(status_code=403, detail='Only the author can delete this snippet')
    await db.delete(snippet)
    await db.commit()


@router.post('/{snippet_id}/install', status_code=204)
async def install_snippet(
    snippet_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(select(Snippet).where(Snippet.id == snippet_id))
    snippet = result.scalar_one_or_none()
    if not snippet:
        raise HTTPException(status_code=404, detail='Snippet not found')

    # Idempotent: only add if not already installed
    existing = await db.execute(
        select(SnippetInstall).where(
            SnippetInstall.snippet_id == snippet_id,
            SnippetInstall.user_id == current_user.id,
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(SnippetInstall(snippet_id=snippet_id, user_id=current_user.id))
        snippet.installs_count = (snippet.installs_count or 0) + 1
        await db.commit()


@router.delete('/{snippet_id}/install', status_code=204)
async def uninstall_snippet(
    snippet_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(select(Snippet).where(Snippet.id == snippet_id))
    snippet = result.scalar_one_or_none()
    if not snippet:
        raise HTTPException(status_code=404, detail='Snippet not found')

    existing = await db.execute(
        select(SnippetInstall).where(
            SnippetInstall.snippet_id == snippet_id,
            SnippetInstall.user_id == current_user.id,
        )
    )
    install = existing.scalar_one_or_none()
    if install:
        await db.delete(install)
        snippet.installs_count = max(0, (snippet.installs_count or 1) - 1)
        await db.commit()


@router.post('/{snippet_id}/upvote', status_code=204)
async def toggle_upvote(
    snippet_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(select(Snippet).where(Snippet.id == snippet_id))
    snippet = result.scalar_one_or_none()
    if not snippet:
        raise HTTPException(status_code=404, detail='Snippet not found')

    existing = await db.execute(
        select(SnippetUpvote).where(
            SnippetUpvote.snippet_id == snippet_id,
            SnippetUpvote.user_id == current_user.id,
        )
    )
    upvote = existing.scalar_one_or_none()
    if upvote:
        # Toggle off
        await db.delete(upvote)
        snippet.upvotes_count = max(0, (snippet.upvotes_count or 1) - 1)
    else:
        # Toggle on
        db.add(SnippetUpvote(snippet_id=snippet_id, user_id=current_user.id))
        snippet.upvotes_count = (snippet.upvotes_count or 0) + 1
    await db.commit()


# ── Admin seed endpoint ───────────────────────────────────────────────────────

@admin_router.post('/snippets/seed', status_code=200)
async def seed_official_snippets(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Upsert official snippets by title (idempotent)."""
    upserted = 0
    for data in OFFICIAL_SNIPPETS:
        res = await db.execute(select(Snippet).where(Snippet.title == data['title']))
        existing = res.scalar_one_or_none()
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
        else:
            db.add(Snippet(**data))
            upserted += 1
    await db.commit()
    return {'seeded': upserted, 'total': len(OFFICIAL_SNIPPETS)}
