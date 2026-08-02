"""Per-change accept/reject review endpoints (Feature 2 / P0).

Additive, stateless review layer on top of the existing optimize flow. The
frontend already holds the original + optimized LaTeX after an optimize run
(via variants/diff); these endpoints:

  * POST /optimize/segment-changes — compute the server-side diff and return
    discrete, independently-applicable change hunks + a summary.
  * POST /optimize/apply-changes   — reconstruct the final LaTeX from the
    original + the subset of hunk ids the user accepted (for recompile).

Auth is optional (mirrors compile/segment being a pure transform on
client-supplied text). Both are pure/stateless — no DB, no Redis, no LLM.
See docs/prd/2026-08-02-input-driven-optimization.md.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.logging import get_logger
from ..middleware.auth_middleware import get_current_user_optional
from ..services.resume_diff_service import (
    ChangeHunk,
    apply_changes,
    segment_changes,
    summarize,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/optimize", tags=["optimize-review"])

# Cap per-document LaTeX well under the global MAX_REQUEST_BODY_BYTES (12MB) so a
# malformed/hostile body is rejected with a clear 422 before the O(n) diff runs.
_MAX_LATEX_CHARS = 500_000
# A resume never has thousands of atomic changes; bound the apply payload.
_MAX_HUNKS = 2_000


class ChangeHunkModel(BaseModel):
    """Wire representation of a diff hunk (mirrors ChangeHunk)."""

    id: str
    kind: str  # "modified" | "added" | "removed"
    original_text: str
    new_text: str
    before_context: str = ""
    after_context: str = ""
    section: Optional[str] = None
    rationale: Optional[str] = None
    original_start: int = 0
    original_end: int = 0


class SegmentChangesRequest(BaseModel):
    original_latex: str = Field(..., description="Original LaTeX before optimization")
    optimized_latex: str = Field(..., description="LLM-optimized LaTeX")
    change_reasons: Optional[List[dict]] = Field(
        default=None,
        description="Advisory [{section, change_type, reason}] from the optimizer; "
        "used only to label hunks, never to decide applied text.",
    )


class SegmentSummary(BaseModel):
    total: int
    added: int
    modified: int
    removed: int


class SegmentChangesResponse(BaseModel):
    hunks: List[ChangeHunkModel]
    summary: SegmentSummary


class ApplyChangesRequest(BaseModel):
    original_latex: str = Field(..., description="Original LaTeX to reconstruct from")
    hunks: List[ChangeHunkModel] = Field(..., description="Hunks from /optimize/segment-changes")
    accepted_ids: List[str] = Field(
        default_factory=list, description="Ids of hunks to apply; others keep the original span"
    )


class ApplyChangesResponse(BaseModel):
    latex: str


def _validate_latex_size(*values: str) -> None:
    for v in values:
        if len(v) > _MAX_LATEX_CHARS:
            raise HTTPException(
                status_code=422,
                detail=f"LaTeX content exceeds {_MAX_LATEX_CHARS} character limit.",
            )


@router.post("/segment-changes", response_model=SegmentChangesResponse)
async def segment_changes_endpoint(
    request: SegmentChangesRequest,
    _user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Compute the original→optimized diff as discrete, applicable change hunks."""
    _validate_latex_size(request.original_latex, request.optimized_latex)
    try:
        hunks: list[ChangeHunk] = segment_changes(
            request.original_latex,
            request.optimized_latex,
            request.change_reasons,
        )
    except Exception as exc:  # pragma: no cover - defensive; diff is pure
        logger.error(f"segment-changes failed: {exc}")
        raise HTTPException(status_code=500, detail="Failed to segment changes")

    return SegmentChangesResponse(
        hunks=[ChangeHunkModel(**h.to_dict()) for h in hunks],
        summary=SegmentSummary(**summarize(hunks)),
    )


@router.post("/apply-changes", response_model=ApplyChangesResponse)
async def apply_changes_endpoint(
    request: ApplyChangesRequest,
    _user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Reconstruct the final LaTeX from the original + the accepted hunk ids."""
    _validate_latex_size(request.original_latex)
    if len(request.hunks) > _MAX_HUNKS:
        raise HTTPException(
            status_code=422,
            detail=f"Too many hunks (max {_MAX_HUNKS}).",
        )
    try:
        latex = apply_changes(
            request.original_latex,
            [h.model_dump() for h in request.hunks],
            set(request.accepted_ids),
        )
    except Exception as exc:  # pragma: no cover - defensive; apply is pure
        logger.error(f"apply-changes failed: {exc}")
        raise HTTPException(status_code=500, detail="Failed to apply changes")

    return ApplyChangesResponse(latex=latex)
