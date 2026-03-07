from typing import List, Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func

from ..database.connection import get_db
from ..database.models import Resume, User
from ..middleware.auth_middleware import get_current_user_required
from pydantic import BaseModel, Field
from datetime import datetime

router = APIRouter(prefix="/resumes", tags=["resumes"])

# --- Schemas ---

class ResumeBase(BaseModel):
    title: str
    latex_content: str
    is_template: bool = False
    tags: Optional[List[str]] = None

class ResumeCreate(ResumeBase):
    pass

class ResumeUpdate(BaseModel):
    title: Optional[str] = None
    latex_content: Optional[str] = None
    is_template: Optional[bool] = None
    tags: Optional[List[str]] = None

class ResumeResponse(ResumeBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ResumeStats(BaseModel):
    total_resumes: int
    total_templates: int
    last_updated: Optional[datetime]

# --- Endpoints ---

@router.get("/stats", response_model=ResumeStats)
async def get_resume_stats(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Get high-level stats about user's resumes."""
    total = await db.execute(
        select(func.count(Resume.id)).where(Resume.user_id == user_id)
    )
    templates = await db.execute(
        select(func.count(Resume.id)).where(Resume.user_id == user_id, Resume.is_template == True)
    )
    latest = await db.execute(
        select(func.max(Resume.updated_at)).where(Resume.user_id == user_id)
    )
    
    return {
        "total_resumes": total.scalar() or 0,
        "total_templates": templates.scalar() or 0,
        "last_updated": latest.scalar()
    }

@router.post("/", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def create_resume(
    resume_in: ResumeCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Create a new resume for the authenticated user."""
    resume = Resume(
        id=str(uuid4()),
        user_id=user_id,
        **resume_in.model_dump()
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)
    return resume

@router.get("/", response_model=List[ResumeResponse])
async def list_resumes(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """List all resumes belonging to the authenticated user."""
    result = await db.execute(
        select(Resume).where(Resume.user_id == user_id).order_by(Resume.updated_at.desc())
    )
    return result.scalars().all()

@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Get a specific resume by ID."""
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume

@router.put("/{resume_id}", response_model=ResumeResponse)
async def update_resume(
    resume_id: str,
    resume_in: ResumeUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Update an existing resume."""
    # Check ownership first
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    update_data = resume_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(resume, key, value)
    
    resume.updated_at = datetime.now()
    await db.commit()
    await db.refresh(resume)
    return resume

@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Delete a resume."""
    result = await db.execute(
        delete(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Resume not found")
    await db.commit()
    return None
