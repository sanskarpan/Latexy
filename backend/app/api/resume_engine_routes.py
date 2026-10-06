"""Versioned semantic fields and explicitly accepted AI candidates."""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..database.connection import get_db
from ..database.models import Compilation, JobFinalization, Resume, ResumeOptimizationRun, ResumeTemplate
from ..middleware.auth_middleware import get_current_user_required
from ..services.resume_engine.acceptance import valid_run_result, validate_factual_dependencies
from ..services.resume_engine.budgets import BudgetExceeded, initial_budget
from ..services.resume_engine.document import digest
from ..services.resume_engine.semantic import (
    DocumentConflict,
    UnsupportedDocument,
    apply_node_edits,
    project_document,
    public_document,
)
from ..utils.uuid_guard import ensure_uuid
from .resume_routes import _get_resume_document_access, _sync_linked_variants

router = APIRouter(prefix="/resumes", tags=["resume-engine"])
public_router = APIRouter(prefix="/public/engine", tags=["resume-engine"])


class NodePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(min_length=1, max_length=128)
    expected_node_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    text: str = Field(max_length=4000)


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_revision: StrictInt = Field(ge=1)
    expected_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    patches: list[NodePatch] = Field(min_length=1, max_length=100)
    merge_disjoint: bool = False


class OptimizeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_revision: StrictInt = Field(ge=1)
    expected_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    job_description: str = Field(min_length=1, max_length=20000)
    effort: Literal["quick", "standard", "deep"] = "standard"
    max_cost_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    model: Literal["gpt-4o-mini", "gpt-4o"] | None = None
    target_sections: list[str] | None = Field(default=None, max_length=20)
    custom_instructions: str | None = Field(default=None, max_length=4000)


class Decisions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accept_patch_ids: list[str] = Field(default_factory=list, max_length=100)
    reject_patch_ids: list[str] = Field(default_factory=list, max_length=100)
    expected_content_revision: StrictInt = Field(ge=1)
    expected_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    merge_disjoint: bool = False


class GuestDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latex_content: str = Field(min_length=1, max_length=1_000_000)
    device_fingerprint: str | None = Field(default=None, max_length=255)


class GuestPatch(GuestDocument):
    expected_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    patches: list[NodePatch] = Field(min_length=1, max_length=100)


def guest_document(source: str):
    return project_document(SimpleNamespace(id="guest", user_id="guest", latex_content=source, content_revision=1))


@public_router.post("/document")
async def project_guest(body: GuestDocument):
    document = guest_document(body.latex_content)
    return {"document": public_document(document), "latex_content": body.latex_content}


@public_router.post("/document/patch")
async def patch_guest(body: GuestPatch):
    document = guest_document(body.latex_content)
    try:
        source, _ = apply_node_edits(
            document,
            [p.model_dump() for p in body.patches],
            expected_revision=1,
            expected_source=body.expected_source_sha256,
        )
    except DocumentConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"document": public_document(guest_document(source)), "latex_content": source}


async def _document(db, resume):
    template = await db.get(ResumeTemplate, resume.selected_template_id) if resume.selected_template_id else None
    try:
        return project_document(resume, template.category if template else None)
    except (UnsupportedDocument, ValidationError, ValueError) as exc:
        raise HTTPException(422, "Document cannot be projected safely") from exc


async def _access(db, resume_id, user_id, *, write=False, owner=False):
    ensure_uuid(resume_id, "Resume not found")
    # Lock source authority before access checks; collaborators are re-evaluated
    # after locking so revoked editors cannot race a stale preflight permission.
    if write:
        await db.execute(select(Resume.id).where(Resume.id == resume_id).with_for_update())
    resume, role = await _get_resume_document_access(db, resume_id, user_id)
    if owner and role != "owner" or write and role not in {"owner", "editor"}:
        raise HTTPException(403, "Editing permission required")
    return resume


@router.get("/{resume_id}/engine/document")
async def get_document(
    resume_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_required)
):
    resume = await _access(db, resume_id, user_id)
    return {"document": public_document(await _document(db, resume)), "latex_content": resume.latex_content}


@router.patch("/{resume_id}/engine/document")
async def patch_document(
    resume_id: str,
    body: DocumentPatch,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    resume = await _access(db, resume_id, user_id, write=True)
    document = await _document(db, resume)
    try:
        source, structured = apply_node_edits(
            document,
            [p.model_dump() for p in body.patches],
            expected_revision=body.expected_content_revision,
            expected_source=body.expected_source_sha256,
            merge_disjoint=body.merge_disjoint,
        )
    except (DocumentConflict, ValidationError) as exc:
        raise HTTPException(409, str(exc)) from exc
    resume.latex_content = source
    if structured is not None:
        resume.structured_content = structured
        await _sync_linked_variants(resume, db)
    await db.commit()
    await db.refresh(resume)
    return {"document": public_document(await _document(db, resume)), "latex_content": resume.latex_content}


@router.post("/{resume_id}/engine/optimize")
async def optimize_document(
    resume_id: str,
    body: OptimizeDocument,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    if settings.RESUME_SEMANTIC_ENGINE_ENABLED is not True:
        raise HTTPException(503, "Semantic optimization is disabled")
    resume = await _access(db, resume_id, user_id, owner=True)
    document = await _document(db, resume)
    if document["source_mode"] != "managed":
        raise HTTPException(
            422, "Custom source remains in advanced mode; choose a managed template to use semantic optimization"
        )
    supported_scope = {node["section"] for node in document["nodes"] if node["ai_editable"]}
    if body.target_sections and any(section.casefold() not in supported_scope for section in body.target_sections):
        raise HTTPException(422, "Requested section has no safely editable semantic nodes")
    if (
        document["content_revision"] != body.expected_content_revision
        or document["source_sha256"] != body.expected_source_sha256
    ):
        raise HTTPException(409, "Document changed; refresh before optimizing")
    try:
        initial_budget(body.effort, body.max_cost_usd)
    except BudgetExceeded as exc:
        raise HTTPException(422, str(exc)) from exc
    from .job_routes import JobSubmissionRequest, submit_job

    metadata = {
        "resume_id": resume_id,
        "optimization_engine": "semantic_v1",
        "optimization_effort": body.effort,
        "expected_content_revision": body.expected_content_revision,
        "expected_source_sha256": body.expected_source_sha256,
        "skip_auto_save": True,
        "branch": "candidate",
    }
    if body.max_cost_usd is not None:
        metadata["max_cost_usd"] = body.max_cost_usd
    return await submit_job(
        JobSubmissionRequest(
            job_type="combined",
            latex_content=resume.latex_content,
            job_description=body.job_description,
            metadata=metadata,
            model=body.model,
            target_sections=body.target_sections,
            custom_instructions=body.custom_instructions,
        ),
        http_request,
        db,
        user_id,
    )


@router.get("/{resume_id}/engine/runs/{run_id}")
async def get_run(
    resume_id: str, run_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_required)
):
    await _access(db, resume_id, user_id, owner=True)
    run = await db.scalar(
        select(ResumeOptimizationRun).where(
            ResumeOptimizationRun.id == run_id,
            ResumeOptimizationRun.resume_id == resume_id,
            ResumeOptimizationRun.user_id == user_id,
        )
    )
    if not run or run.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(404, "Optimization run not found")
    if run.result is not None and not valid_run_result(run.result):
        raise HTTPException(409, "Candidate result integrity failed")
    arbiter = await db.scalar(
        select(JobFinalization).where(
            JobFinalization.job_id == run_id,
            JobFinalization.expires_at > func.clock_timestamp(),
        )
    )
    effective_status = "cancelled" if arbiter and arbiter.cancel_requested else run.status
    return {
        "run_id": run.id,
        "document_id": run.resume_id,
        "base_revision": run.base_revision,
        "source_sha256": run.source_sha256,
        "status": effective_status,
        "job_status": "cancelled"
        if arbiter and arbiter.cancel_requested
        else (arbiter.state if arbiter else "unavailable"),
        "acceptance_ready": bool(
            arbiter and arbiter.state == "completed" and not arbiter.cancel_requested and run.result is not None
        ),
        "effort": run.effort,
        "document": public_document(run.snapshot),
        "result": run.result,
        "budget": run.budget,
        "decisions": run.decisions,
        "coverage": run.context_payload["coverage"],
        "pdf_quality": (arbiter.result_payload or {}).get("pdf_quality") if arbiter else None,
    }


@router.post("/{resume_id}/engine/runs/{run_id}/decisions")
async def decide_run(
    resume_id: str,
    run_id: str,
    body: Decisions,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    resume = await _access(db, resume_id, user_id, write=True, owner=True)
    run = await db.scalar(
        select(ResumeOptimizationRun)
        .where(
            ResumeOptimizationRun.id == run_id,
            ResumeOptimizationRun.resume_id == resume_id,
            ResumeOptimizationRun.user_id == user_id,
        )
        .with_for_update()
    )
    if (
        not run
        or not run.result
        or not valid_run_result(run.result)
        or run.status not in {"completed", "partial"}
        or run.expires_at <= datetime.now(timezone.utc)
    ):
        raise HTTPException(409, "No completed candidate available")
    arbiter = await db.scalar(
        select(JobFinalization).where(
            JobFinalization.job_id == run_id,
            JobFinalization.expires_at > func.clock_timestamp(),
        )
    )
    if not arbiter or arbiter.cancel_requested or arbiter.state != "completed":
        raise HTTPException(409, "Candidate job must complete successfully before acceptance")
    accept, reject = set(body.accept_patch_ids), set(body.reject_patch_ids)
    patches = {p["patch_id"]: p for p in run.result["patches"]}
    if (
        accept & reject
        or len(accept) != len(body.accept_patch_ids)
        or len(reject) != len(body.reject_patch_ids)
        or not (accept | reject) <= patches.keys()
    ):
        raise HTTPException(422, "Unknown, conflicting or duplicate decisions")
    decisions = dict(run.decisions or {})
    statuses = dict(decisions.get("patches", {}))
    if any(
        statuses.get(pid) not in {None, outcome}
        for outcome, ids in (("accepted", accept), ("rejected", reject))
        for pid in ids
    ):
        raise HTTPException(409, "A recorded decision cannot be reversed")
    if accept | reject and all(
        statuses.get(pid) == outcome for outcome, ids in (("accepted", accept), ("rejected", reject)) for pid in ids
    ):
        # A lost response can be retried without replaying the mutation. Return
        # the current source; export still checks the receipt against it.
        return {
            "run_id": run_id,
            "decisions": decisions,
            "document": public_document(await _document(db, resume)),
            "latex_content": resume.latex_content,
        }
    document = await _document(db, resume)
    new_accept = accept - {pid for pid, value in statuses.items() if value == "accepted"}
    try:
        validate_factual_dependencies(document, run.context_payload, [patches[pid] for pid in sorted(new_accept)],
                                      list(patches.values()), statuses, effort=run.effort)
        source, structured = apply_node_edits(
            document,
            [patches[pid] for pid in sorted(new_accept)],
            expected_revision=body.expected_content_revision,
            expected_source=body.expected_source_sha256,
            merge_disjoint=body.merge_disjoint,
            ai_only=True,
        )
    except (DocumentConflict, ValidationError) as exc:
        raise HTTPException(409, str(exc)) from exc
    if new_accept:
        resume.latex_content, resume.structured_content = source, structured
        await _sync_linked_variants(resume, db)
        await db.flush()
        await db.refresh(resume)
    statuses.update({pid: "accepted" for pid in accept})
    statuses.update({pid: "rejected" for pid in reject})
    decisions["patches"] = statuses
    complete = (
        all(statuses.get(pid) == "accepted" for pid in patches)
        and digest(resume.latex_content) == run.result["candidate_source_sha256"]
    )
    decisions["complete_acceptance"] = complete
    if complete:
        decisions.update(
            accepted_source_sha256=digest(resume.latex_content), accepted_content_revision=resume.content_revision
        )
        # This candidate snapshot is now an explicitly accepted historical PDF.
        # Persist authorization with the compilation, beyond the run's TTL.
        await db.execute(
            update(Compilation)
            .where(
                Compilation.job_id == run.job_id,
                Compilation.resume_id == resume.id,
                Compilation.artifact_branch == "candidate",
                Compilation.pdf_path.is_not(None),
            )
            .values(artifact_accepted=True)
        )
    else:
        decisions.pop("accepted_source_sha256", None)
        decisions.pop("accepted_content_revision", None)
    run.decisions = decisions
    await db.commit()
    await db.refresh(resume)
    return {
        "run_id": run_id,
        "decisions": decisions,
        "document": public_document(await _document(db, resume)),
        "latex_content": resume.latex_content,
    }
