"""Unaccepted candidates cannot replace the user's share/email/export PDF."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.api.application_routes import _get_resume_pdf
from app.api.document_delivery_routes import _owned_compiled_pdf
from app.api.export_routes import _get_latest_compiled_pdf
from app.database.models import Compilation, Resume, User


async def test_latest_candidate_is_excluded_from_canonical_pdf_routes(db_session, monkeypatch):
    user_id, resume_id = str(uuid4()), str(uuid4())
    now = datetime.now(timezone.utc)
    draft, candidate = b"%PDF-1.7\naccepted draft", b"%PDF-1.7\nunaccepted candidate"
    db_session.add(User(id=user_id, email="test_candidate_" + user_id + "@example.test", name="Fixture"))
    await db_session.flush()
    db_session.add(Resume(id=resume_id, user_id=user_id, title="Fixture", latex_content="source"))
    await db_session.flush()
    first, second = str(uuid4()), str(uuid4())
    db_session.add_all([
        Compilation(id=first, user_id=user_id, resume_id=resume_id, job_id=str(uuid4()), status="completed",
                    pdf_path="fixture-draft", pdf_size=len(draft), artifact_branch="draft", artifact_accepted=True,
                    created_at=now - timedelta(minutes=1)),
        Compilation(id=second, user_id=user_id, resume_id=resume_id, job_id=str(uuid4()), status="completed",
                    pdf_path="fixture-candidate", pdf_size=len(candidate), artifact_branch="candidate", artifact_accepted=False,
                    created_at=now),
    ])
    await db_session.flush()
    monkeypatch.setattr("app.services.storage_service.download_bytes", lambda key, *args: {"fixture-draft": draft, "fixture-candidate": candidate}[key])
    assert await _get_resume_pdf(resume_id, user_id, db_session) == draft
    _, selected, data = await _owned_compiled_pdf(resume_id, user_id, db_session)
    assert selected.id == first and data == draft
    assert await _get_latest_compiled_pdf(resume_id, user_id, db_session) == draft
    with pytest.raises(HTTPException) as error:
        await _owned_compiled_pdf(resume_id, user_id, db_session, compilation_id=second)
    assert error.value.status_code == 422
    await db_session.execute(update(Compilation).where(Compilation.id == second).values(artifact_accepted=True))
    assert await _get_resume_pdf(resume_id, user_id, db_session) == candidate
