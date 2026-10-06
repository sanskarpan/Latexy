"""Read-only recovery of durable terminal job results.

Redis is the fast result transport, not the source of truth after a terminal
decision.  These helpers deliberately read only non-expired, user-owned,
terminal ``JobFinalization`` rows and return the already-bounded payload kept
by the arbiter.  They never recreate rows or extend retention.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Compilation, JobFinalization
from ..workers.finalization_arbiter import bounded_result_payload, typed_missing_output_fields

_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "fenced"})
_OUTPUT_UNAVAILABLE_ERROR = "Completed job output unavailable"


async def recover_terminal_job(
    session: AsyncSession,
    *,
    job_id: str,
    user_id: str,
    expected_type: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Return a bounded terminal result for exactly one authenticated owner.

    ``expected_type="github_import"`` requires the durable job discriminator
    for new rows and a narrow owner-token fallback for legacy rows, plus a
    typed projects list for successful imports. ``JobFinalization`` rows in
    the ``fenced`` state are exposed as bounded generic failures.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        # Anonymous/ownerless callers must never gain a durable-row lookup
        # path merely because SQL NULL comparison happens to match a nullable
        # finalization row.
        return None

    row = await session.scalar(
        select(JobFinalization)
        .where(
            JobFinalization.job_id == job_id,
            JobFinalization.user_id == user_id,
            JobFinalization.state.in_(_TERMINAL_STATES),
            JobFinalization.expires_at > func.clock_timestamp(),
        )
    )
    if row is None:
        return None

    payload = bounded_result_payload(job_id, row.result_payload)
    if expected_type == "github_import":
        if row.job_type:
            if row.job_type != expected_type:
                return None
        elif not (row.owner_token or "").startswith("github-import-"):
            # Legacy rows predate the discriminator. Keep the compatibility
            # fallback narrow and never infer GitHub from payload fields alone.
            return None
        projects = payload.get("projects")
        # Successful imports must retain their typed evidence.  Failure rows
        # produced by generic cleanup may legitimately contain no generated
        # projects; expose those as an empty list rather than losing the
        # terminal decision.  Any present value is still type-checked.
        if row.state == "completed" and not isinstance(projects, list):
            return None
        if projects is not None and not isinstance(projects, list):
            return None
        payload.setdefault("projects", [])

    state = "failed" if row.state == "fenced" else str(row.state)
    output_unavailable = False
    if state == "completed":
        missing_fields = typed_missing_output_fields(row.job_type, payload)
        if payload.get("recovery_complete") is False or missing_fields:
            output_unavailable = True
            payload["success"] = False
            payload["recovery_complete"] = False
            omitted_fields = payload.get("omitted_output_fields")
            if not isinstance(omitted_fields, list):
                omitted_fields = []
            for field in missing_fields:
                if field not in omitted_fields:
                    omitted_fields.append(field)
            payload["omitted_output_fields"] = omitted_fields
            payload["error_code"] = "output_unavailable"
        else:
            payload["success"] = True
    else:
        payload["success"] = False
    result: dict[str, Any] = {
        "state": state,
        "payload": payload,
        "error": _OUTPUT_UNAVAILABLE_ERROR if output_unavailable else (
            None if state == "completed" else ("Job cancelled" if state == "cancelled" else "Job failed")
        ),
        "error_code": "output_unavailable" if output_unavailable else None,
        "output_unavailable": output_unavailable,
        # Only a successful terminal authority may expose an artifact. Old
        # failed/cancelled rows can retain stale pointers from earlier writes.
        "pdf_path": row.pdf_path if row.state == "completed" else None,
        "pdf_size": row.pdf_size if row.state == "completed" else None,
    }

    # A completed arbiter row may have been written before Redis publication.
    # The immutable PDF pointer is allowed only through the same user-owned
    # compilation relationship; never search by job ID alone for another user.
    if row.state == "completed" and not result["pdf_path"]:
        compilation = await session.scalar(
            select(Compilation).where(
                Compilation.job_id == job_id,
                Compilation.user_id == user_id,
                Compilation.status == "completed",
            )
        )
        if compilation is not None:
            result["pdf_path"] = compilation.pdf_path
            result["pdf_size"] = compilation.pdf_size
    return result
