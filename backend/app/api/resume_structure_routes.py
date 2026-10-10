"""Strict source-CAS structural editing for managed resumes."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_required
from ..services.resume_engine.semantic import DocumentConflict, public_document
from ..services.resume_engine.structure import apply_reorder
from ..services.resume_managed_source_service import apply_managed_document_change

router = APIRouter(tags=["resume-engine"])


class StructureMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_revision: StrictInt = Field(ge=1)
    expected_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    container_id: StrictStr = Field(min_length=1, max_length=256)
    ordered_ids: list[StrictStr] = Field(max_length=1000)


@router.post("/{resume_id}/engine/structure")
async def reorder_document(resume_id: str, body: StructureMutation,
                           db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_required)):
    # Reuse the canonical lock-then-access check, including collaborator revocation.
    from .resume_engine_routes import _access, _document
    from .resume_routes import _sync_linked_variants

    resume = await _access(db, resume_id, user_id, write=True)
    await db.refresh(resume)  # row lock is held; reject stale ORM snapshots as well as stale clients
    document = await _document(db, resume)
    try:
        source, structured = apply_reorder(document, expected_revision=body.expected_content_revision,
                                           expected_source=body.expected_source_sha256,
                                           container_id=body.container_id, ordered_ids=body.ordered_ids)
    except (DocumentConflict, ValidationError) as exc:
        raise HTTPException(409, str(exc)) from exc
    if apply_managed_document_change(
        resume, source, structured, previous_structured=document["_structured_content"]
    ):
        await _sync_linked_variants(resume, db)
    await db.commit()
    await db.refresh(resume)
    return {"document": public_document(await _document(db, resume)), "latex_content": resume.latex_content}
