"""Narrow durable owned-PDF recovery contract tests.

These tests exercise the route with a database-shaped result and mocked object
storage.  The shared real-DB/HTTP acceptance path is intentionally left to the
terminal-boundary owner because this file must not flush or reset the suite's
Redis/database fixtures.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, text

from app.database.models import Compilation, JobFinalization, Resume
from app.services.storage_service import compilation_pdf_key

PDF = b"%PDF-1.7\nowned durable artifact\n"


class _Result:
    def __init__(self, pair):
        self.pair = pair

    def first(self):
        return self.pair


class _DB:
    def __init__(self, pair=None, error=None):
        self.pair = pair
        self.error = error
        self.calls = 0

    async def execute(self, _query):
        self.calls += 1
        if self.error:
            raise self.error
        return _Result(self.pair)


def _durable_rows(*, user_id: str, job_id: str, job_type: str = "latex_compilation", **overrides):
    compilation_id = overrides.pop("compilation_id", str(uuid4()))
    finalization_compilation_id = overrides.pop("finalization_compilation_id", compilation_id)
    owner_token = overrides.pop("owner_token", "owned-pdf-owner")
    key = overrides.pop("pdf_path", compilation_pdf_key(job_id, owner_token))
    pdf_size = overrides.pop("pdf_size", len(PDF))
    resume_id = overrides.pop("resume_id", None)
    compilation_resume_id = overrides.pop("compilation_resume_id", resume_id)
    finalization = SimpleNamespace(
        job_id=job_id,
        user_id=user_id,
        job_type=job_type,
        state=overrides.pop("state", "completed"),
        compilation_id=finalization_compilation_id,
        resume_id=resume_id,
        owner_token=owner_token,
        pdf_path=key,
        pdf_size=overrides.pop("finalization_size", pdf_size),
        pdf_sha256=overrides.pop("pdf_sha256", hashlib.sha256(PDF).hexdigest()),
    )
    compilation = SimpleNamespace(
        id=compilation_id,
        job_id=job_id,
        user_id=user_id,
        status=overrides.pop("compilation_status", "completed"),
        resume_id=compilation_resume_id,
        pdf_path=overrides.pop("compilation_path", key),
        pdf_size=overrides.pop("compilation_size", pdf_size),
    )
    assert not overrides
    return finalization, compilation


def _redis_without_artifact():
    redis = AsyncMock()
    redis.get.return_value = None
    return redis


async def _missing_metadata(_job_id, _user_id):
    raise HTTPException(status_code=404, detail="Job not found")


async def _cached_metadata(_job_id, _user_id):
    return None


async def _download(monkeypatch, tmp_path, *, db, user_id, job_id, storage_result=PDF, metadata="missing"):
    from app.api import routes

    monkeypatch.setattr(
        routes,
        "_assert_job_download_access",
        _missing_metadata if metadata == "missing" else _cached_metadata,
    )
    monkeypatch.setattr(
        routes,
        "get_job_files",
        lambda _job: (None, tmp_path / "absent.pdf", None),
    )
    redis = _redis_without_artifact()
    with (
        patch("app.core.redis.get_redis_client", new=AsyncMock(return_value=redis)),
        patch("app.services.storage_service.download_bytes", return_value=storage_result),
    ):
        return await routes.download_pdf(job_id, user_id, db)


@pytest.mark.asyncio
async def test_authenticated_owner_recovers_when_redis_metadata_expired(
    tmp_path, monkeypatch
):
    user_id, job_id = str(uuid4()), str(uuid4())
    rows = _durable_rows(user_id=user_id, job_id=job_id)
    response = await _download(
        monkeypatch, tmp_path, db=_DB(rows), user_id=user_id, job_id=job_id
    )
    assert response.body == PDF
    assert response.media_type == "application/pdf"


@pytest.mark.asyncio
async def test_authenticated_owner_recovers_with_cached_metadata_but_no_transient_pdf(
    tmp_path, monkeypatch
):
    user_id, job_id = str(uuid4()), str(uuid4())
    response = await _download(
        monkeypatch,
        tmp_path,
        db=_DB(_durable_rows(user_id=user_id, job_id=job_id)),
        user_id=user_id,
        job_id=job_id,
        metadata="cached",
    )
    assert response.body == PDF


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_id, pair",
    [
        (None, None),  # anonymous callers never perform nullable-owner DB recovery
        (str(uuid4()), None),  # wrong owner/missing row
    ],
)
async def test_wrong_owner_and_anonymous_are_not_recovered(
    tmp_path, monkeypatch, user_id, pair
):
    from app.api import routes

    job_id = str(uuid4())
    db = _DB(pair)
    monkeypatch.setattr(routes, "_assert_job_download_access", _missing_metadata)
    with pytest.raises(HTTPException) as caught:
        await routes.download_pdf(job_id, user_id, db)
    assert caught.value.status_code == 404
    if user_id is None:
        assert db.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row_overrides",
    [
        {"state": "failed"},
        {"state": "cancelled"},
        {"job_type": "llm_optimization"},
        {"compilation_status": "processing"},
        {"compilation_path": "compilations/other.pdf"},
        {"finalization_compilation_id": str(uuid4())},
        {"resume_id": str(uuid4()), "compilation_resume_id": str(uuid4())},
    ],
)
async def test_non_success_private_or_mismatched_rows_return_404(
    tmp_path, monkeypatch, row_overrides
):
    user_id, job_id = str(uuid4()), str(uuid4())
    awaitable_rows = _durable_rows(user_id=user_id, job_id=job_id, **row_overrides)
    with pytest.raises(HTTPException) as caught:
        await _download(
            monkeypatch,
            tmp_path,
            db=_DB(awaitable_rows),
            user_id=user_id,
            job_id=job_id,
        )
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_database_error_fails_closed_503(tmp_path, monkeypatch):
    user_id, job_id = str(uuid4()), str(uuid4())
    with pytest.raises(HTTPException) as caught:
        await _download(
            monkeypatch,
            tmp_path,
            db=_DB(error=RuntimeError("database unavailable")),
            user_id=user_id,
            job_id=job_id,
        )
    assert caught.value.status_code == 503


@pytest.mark.asyncio
async def test_expired_finalization_is_not_recovered(tmp_path, monkeypatch):
    user_id, job_id = str(uuid4()), str(uuid4())
    with pytest.raises(HTTPException) as caught:
        await _download(monkeypatch, tmp_path, db=_DB(None), user_id=user_id, job_id=job_id)
    assert caught.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "storage_result, expected_status",
    [
        (None, 404),
        (RuntimeError("storage unavailable"), 503),
        (b"not a pdf", 404),
        (b"%PDF-corrupt", 404),
    ],
)
async def test_durable_storage_is_bounded_and_integrity_checked(
    tmp_path, monkeypatch, storage_result, expected_status
):
    user_id, job_id = str(uuid4()), str(uuid4())
    rows = _durable_rows(user_id=user_id, job_id=job_id)
    storage = (
        patch("app.services.storage_service.download_bytes", side_effect=storage_result)
        if isinstance(storage_result, Exception)
        else patch("app.services.storage_service.download_bytes", return_value=storage_result)
    )
    from app.api import routes

    monkeypatch.setattr(routes, "_assert_job_download_access", _missing_metadata)
    monkeypatch.setattr(routes, "get_job_files", lambda _job: (None, tmp_path / "absent.pdf", None))
    with (
        patch("app.core.redis.get_redis_client", new=AsyncMock(return_value=_redis_without_artifact())),
        storage,
    ):
        with pytest.raises(HTTPException) as caught:
            await routes.download_pdf(job_id, user_id, _DB(rows))
    assert caught.value.status_code == expected_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"finalization_size": len(PDF) + 1},
        {"pdf_sha256": "0" * 64},
    ],
)
async def test_durable_size_hash_mismatch_is_404(tmp_path, monkeypatch, overrides):
    user_id, job_id = str(uuid4()), str(uuid4())
    rows = _durable_rows(user_id=user_id, job_id=job_id, **overrides)
    with pytest.raises(HTTPException) as caught:
        await _download(monkeypatch, tmp_path, db=_DB(rows), user_id=user_id, job_id=job_id)
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_durable_storage_oversize_is_413(tmp_path, monkeypatch):
    from app.services.storage_service import StorageObjectTooLarge

    user_id, job_id = str(uuid4()), str(uuid4())
    rows = _durable_rows(user_id=user_id, job_id=job_id)
    from app.api import routes

    monkeypatch.setattr(routes, "_assert_job_download_access", _missing_metadata)
    monkeypatch.setattr(routes, "get_job_files", lambda _job: (None, tmp_path / "absent.pdf", None))
    with (
        patch("app.core.redis.get_redis_client", new=AsyncMock(return_value=_redis_without_artifact())),
        patch("app.services.storage_service.download_bytes", side_effect=StorageObjectTooLarge("large")),
    ):
        with pytest.raises(HTTPException) as caught:
            await routes.download_pdf(job_id, user_id, _DB(rows))
    assert caught.value.status_code == 413


@pytest.mark.asyncio
async def test_http_recovery_uses_db_artifact_over_divergent_redis_and_local_bytes(
    client: AsyncClient, auth_headers: dict, db_session, monkeypatch, tmp_path
):
    """The real route must not let transient bytes override the DB pointer."""
    from app.api import routes

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    user_id = str(
        (
            await db_session.execute(
                text('SELECT "userId" FROM session WHERE token = :token'), {"token": token}
            )
        ).scalar_one()
    )
    job_id = str(uuid4())
    resume_id = str(uuid4())
    compilation_id = str(uuid4())
    owner_token = f"test-owned-pdf-{uuid4()}"
    pdf_path = compilation_pdf_key(job_id, owner_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    db_session.add(
        Resume(
            id=resume_id,
            user_id=user_id,
            title="Owned PDF recovery",
            latex_content="\\documentclass{article}",
        )
    )
    # These models use scalar foreign-key columns without ORM relationships;
    # flush each parent explicitly so test ordering does not depend on the
    # unit-of-work's insert ordering while the real FK remains enforced.
    await db_session.flush()
    db_session.add(
        Compilation(
            id=compilation_id,
            user_id=user_id,
            resume_id=resume_id,
            job_id=job_id,
            status="completed",
            pdf_path=pdf_path,
            pdf_size=len(PDF),
        )
    )
    await db_session.flush()
    db_session.add(
        JobFinalization(
            id=str(uuid4()),
            job_id=job_id,
            user_id=user_id,
            job_type="latex_compilation",
            compilation_id=compilation_id,
            resume_id=resume_id,
            owner_token=owner_token,
            state="completed",
            terminal_result="completed",
            pdf_path=pdf_path,
            pdf_sha256=hashlib.sha256(PDF).hexdigest(),
            pdf_size=len(PDF),
            expires_at=expires_at,
        )
    )
    await db_session.commit()

    local_pdf = tmp_path / "divergent-local.pdf"
    local_pdf.write_bytes(b"%PDF-local-divergent")
    redis = AsyncMock()
    redis.get.side_effect = [None, base64.b64encode(b"%PDF-redis-divergent").decode()]
    monkeypatch.setattr(routes, "get_job_files", lambda _job: (tmp_path, local_pdf, None))
    monkeypatch.setattr("app.core.redis.get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(
        "app.services.storage_service.download_bytes",
        lambda _key, max_bytes=None: PDF,
    )

    try:
        response = await client.get(f"/download/{job_id}", headers=auth_headers)
        assert response.status_code == 200
        assert response.content == PDF
        # Metadata is checked once; the divergent cached PDF must never be read.
        assert redis.get.await_count == 1
    finally:
        await db_session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
        await db_session.execute(delete(Compilation).where(Compilation.job_id == job_id))
        await db_session.execute(delete(Resume).where(Resume.id == resume_id))
        await db_session.commit()
