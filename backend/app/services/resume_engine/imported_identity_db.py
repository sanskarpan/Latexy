"""Metadata-only CAS persistence; callers retain their document transaction."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm.attributes import set_committed_value

from ...database.models import Resume
from .imported_identity import bind_projection, reconcile_projection, seed_projection
from .semantic import DocumentConflict, project_document


async def ensure_imported_projection(db, resume: Resume, category: str | None = None) -> dict:
    """Return a fresh projection with chosen persisted IDs, without committing.

    No document source/revision is changed. Concurrent seed writers compare the
    old metadata as well as exact source/revision; the loser refreshes the chosen
    record rather than returning a different identity set. GET callers commit
    metadata-only work; mutation callers commit their existing transaction.
    """
    for _ in range(3):
        document = project_document(resume, category, use_imported_identity=False)
        if document["source_mode"] == "managed":
            return document
        previous = resume.imported_projection
        bound = bind_projection(document, previous)
        if bound is not document:
            return bound
        chosen, payload = seed_projection(document)
        metadata_match = Resume.imported_projection.is_(None) if previous is None else Resume.imported_projection == previous
        statement = update(Resume).where(
            Resume.id == resume.id, Resume.latex_content == document["_source"],
            Resume.content_revision == document["content_revision"], metadata_match,
        ).values(imported_projection=payload).returning(Resume.content_revision)
        with db.no_autoflush:
            changed = (await db.execute(statement.execution_options(synchronize_session=False))).first()
        if changed is not None:
            set_committed_value(resume, "imported_projection", payload)
            return chosen
        with db.no_autoflush:
            current = (await db.execute(select(Resume).where(Resume.id == resume.id)
                                      .execution_options(populate_existing=True))).scalar_one_or_none()
        if current is None:
            raise DocumentConflict("Document disappeared while preparing its editable projection")
        resume = current
    raise DocumentConflict("Document changed while preparing its editable projection")


def persist_reconciled_projection(resume: Resume, previous_document: dict, source: str,
                                 approved_patches: list[dict] | None = None) -> dict:
    """Set metadata alongside an already-authorized source mutation; never commit."""
    if resume.latex_content != source:
        raise DocumentConflict("Imported projection differs from the adopted source")
    document = project_document(resume, use_imported_identity=False)
    try:
        reconciled, metadata = reconcile_projection(document, previous_document, approved_patches)
    except (ValueError, TypeError, KeyError) as exc:
        raise DocumentConflict("Imported edit identity could not be safely reconciled") from exc
    resume.imported_projection = metadata
    return reconciled
