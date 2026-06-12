"""
Career Path + Skills Gap Analysis API — Feature 80.

Endpoints (prefix: /career):
  POST /career/analyze                  — run full analysis
  GET  /career/analyses/{resume_id}     — list past analyses for a resume
  GET  /career/analysis/{analysis_id}  — retrieve single analysis with path data
  GET  /career/roles?q=<search>         — role autocomplete
  POST /admin/career-graph/seed         — seed career graph (admin only)
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import CareerAnalysis, CareerRole, Resume
from ..middleware.auth_middleware import get_current_user_required as get_current_user
from ..middleware.auth_middleware import require_admin
from ..services.career_path_service import career_path_service

logger = get_logger(__name__)

router = APIRouter(prefix="/career", tags=["career"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    resume_id: str
    target_role_title: str


class CareerRoleSchema(BaseModel):
    model_config = {'from_attributes': True}

    id: str
    title: str
    level: str
    industry: str
    required_skills: list[str]
    typical_yoe_min: Optional[int] = None
    typical_yoe_max: Optional[int] = None


class CareerAnalysisSchema(BaseModel):
    model_config = {'from_attributes': True}

    id: str
    resume_id: str
    target_role_id: Optional[str] = None
    target_role_freetext: Optional[str] = None
    current_skills: list[str]
    gap_skills: list[str]
    path_role_ids: Optional[list[str]] = None
    timeline_months: Optional[int] = None
    llm_analysis: Optional[str] = None
    created_at: str
    # Resolved path roles (populated on detail endpoint)
    path_roles: Optional[list[CareerRoleSchema]] = None
    target_role: Optional[CareerRoleSchema] = None


class SeedResponse(BaseModel):
    roles_created: int
    transitions_created: int
    message: str


# ── Helper ────────────────────────────────────────────────────────────────────

def _analysis_to_schema(
    analysis: CareerAnalysis,
    path_roles: Optional[list[CareerRole]] = None,
    target_role: Optional[CareerRole] = None,
) -> dict[str, Any]:
    return {
        "id": analysis.id,
        "resume_id": analysis.resume_id,
        "target_role_id": analysis.target_role_id,
        "target_role_freetext": analysis.target_role_freetext,
        "current_skills": analysis.current_skills or [],
        "gap_skills": analysis.gap_skills or [],
        "path_role_ids": analysis.path_role_ids,
        "timeline_months": analysis.timeline_months,
        "llm_analysis": analysis.llm_analysis,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "path_roles": [
            {
                "id": r.id, "title": r.title, "level": r.level,
                "industry": r.industry, "required_skills": r.required_skills or [],
                "typical_yoe_min": r.typical_yoe_min, "typical_yoe_max": r.typical_yoe_max,
            }
            for r in (path_roles or [])
        ] or None,
        "target_role": {
            "id": target_role.id, "title": target_role.title, "level": target_role.level,
            "industry": target_role.industry,
            "required_skills": target_role.required_skills or [],
            "typical_yoe_min": target_role.typical_yoe_min,
            "typical_yoe_max": target_role.typical_yoe_max,
        } if target_role else None,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/analyze")
async def analyze_career_path(
    body: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> dict:
    """
    Run a full career path + skills gap analysis.

    Steps:
      1. Verify resume ownership
      2. Extract current role + skills from LaTeX
      3. Match target role in career graph (or use freetext)
      4. BFS path from current → target
      5. LLM gap analysis
      6. Persist + return CareerAnalysis
    """
    # Verify resume ownership
    result = await db.execute(
        select(Resume).where(
            Resume.id == body.resume_id,
            Resume.user_id == user_id,
        )
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if not body.target_role_title.strip():
        raise HTTPException(status_code=400, detail="target_role_title is required")

    try:
        analysis = await career_path_service.run_full_analysis(
            resume_id=body.resume_id,
            user_id=user_id,
            target_role_title=body.target_role_title.strip(),
            latex_content=resume.latex_content,
            db=db,
        )
    except Exception as exc:
        logger.error(f"Career analysis failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")

    # Resolve path roles for response — single bulk query instead of N+1
    path_roles: list[CareerRole] = []
    if analysis.path_role_ids:
        roles_result = await db.execute(
            select(CareerRole).where(CareerRole.id.in_(analysis.path_role_ids))
        )
        role_map = {r.id: r for r in roles_result.scalars().all()}
        path_roles = [role_map[rid] for rid in analysis.path_role_ids if rid in role_map]

    target_role = (
        await db.get(CareerRole, analysis.target_role_id)
        if analysis.target_role_id else None
    )

    return _analysis_to_schema(analysis, path_roles=path_roles, target_role=target_role)


@router.get("/analyses/{resume_id}")
async def list_career_analyses(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> list[dict]:
    """List past career analyses for a resume in reverse chronological order."""
    # Verify ownership
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Resume not found")

    analyses_result = await db.execute(
        select(CareerAnalysis)
        .where(CareerAnalysis.resume_id == resume_id, CareerAnalysis.user_id == user_id)
        .order_by(CareerAnalysis.created_at.desc())
        .limit(20)
    )
    analyses = analyses_result.scalars().all()
    return [_analysis_to_schema(a) for a in analyses]


@router.get("/analysis/{analysis_id}")
async def get_career_analysis(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> dict:
    """Retrieve a single analysis with full path role data."""
    analysis = await db.get(CareerAnalysis, analysis_id)
    if not analysis or analysis.user_id != user_id:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Bulk fetch — avoids N+1 (one SELECT per role ID)
    path_roles: list[CareerRole] = []
    if analysis.path_role_ids:
        roles_result = await db.execute(
            select(CareerRole).where(CareerRole.id.in_(analysis.path_role_ids))
        )
        role_map = {r.id: r for r in roles_result.scalars().all()}
        path_roles = [role_map[rid] for rid in analysis.path_role_ids if rid in role_map]

    target_role = (
        await db.get(CareerRole, analysis.target_role_id)
        if analysis.target_role_id else None
    )

    return _analysis_to_schema(analysis, path_roles=path_roles, target_role=target_role)


@router.get("/roles")
async def search_career_roles(
    q: str = "",
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Search career roles for autocomplete (no auth required)."""
    roles = await career_path_service.search_roles(q, db, limit=15)
    return [
        {
            "id": r.id,
            "title": r.title,
            "level": r.level,
            "industry": r.industry,
            "required_skills": r.required_skills or [],
        }
        for r in roles
    ]


# ── Admin: Seed endpoint ──────────────────────────────────────────────────────

@admin_router.post("/career-graph/seed", response_model=SeedResponse)
async def seed_career_graph(
    db: AsyncSession = Depends(get_db),
    _admin_user_id: str = Depends(require_admin),
) -> SeedResponse:
    """
    Seed the career graph with roles and transitions (admin only, idempotent).
    Re-running upserts existing roles by title+industry.
    """
    from ..data.career_graph_seed import ROLES, TRANSITIONS

    # Upsert roles
    roles_created = 0
    title_to_id: dict[str, str] = {}

    for role_data in ROLES:
        existing = await db.execute(
            select(CareerRole).where(
                CareerRole.title == role_data["title"],
                CareerRole.industry == role_data["industry"],
            )
        )
        role = existing.scalar_one_or_none()
        if not role:
            role = CareerRole(
                title=role_data["title"],
                level=role_data["level"],
                industry=role_data["industry"],
                required_skills=role_data["required_skills"],
                typical_yoe_min=role_data.get("yoe_min"),
                typical_yoe_max=role_data.get("yoe_max"),
            )
            db.add(role)
            await db.flush()
            roles_created += 1
        title_to_id[role_data["title"]] = role.id

    # Upsert transitions
    transitions_created = 0
    from ..database.models import CareerTransition

    for from_title, to_title, avg_years, difficulty in TRANSITIONS:
        from_id = title_to_id.get(from_title)
        to_id = title_to_id.get(to_title)
        if not from_id or not to_id:
            logger.warning(f"Skipping transition {from_title} → {to_title}: role not found")
            continue

        existing_t = await db.execute(
            select(CareerTransition).where(
                CareerTransition.from_role_id == from_id,
                CareerTransition.to_role_id == to_id,
            )
        )
        if not existing_t.scalar_one_or_none():
            transition = CareerTransition(
                from_role_id=from_id,
                to_role_id=to_id,
                avg_years=avg_years,
                difficulty=difficulty,
            )
            db.add(transition)
            transitions_created += 1

    await db.commit()

    return SeedResponse(
        roles_created=roles_created,
        transitions_created=transitions_created,
        message=(
            f"Seeded {roles_created} new role(s) and {transitions_created} new transition(s). "
            "Existing records were skipped."
        ),
    )
