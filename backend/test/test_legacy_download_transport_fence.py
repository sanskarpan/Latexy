"""Durable-job authority must fence the legacy cached-file download paths."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response


class _AuthorityDB:
    def __init__(self, *, job_id: str, durable_state: str | None = None, error: Exception | None = None):
        self.job_id = job_id
        self.row = None if durable_state is None else SimpleNamespace(
            id="durable-row",
            job_id=job_id,
            user_id="another-owner" if durable_state == "foreign" else "owner",
            state="completed" if durable_state in {"expired", "foreign"} else durable_state,
            expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)
                        if durable_state == "expired" else datetime.now(timezone.utc) + timedelta(days=1)),
        )
        self.error = error

    async def scalar(self, _query):
        if self.error:
            raise self.error
        clause = _query.whereclause
        assert clause.left.name == "job_id"
        assert clause.right.value == self.job_id
        return self.row.id if self.row is not None and self.row.job_id == clause.right.value else None


async def _metadata_ok(_job_id, _user_id):
    return None


def _redis(*values):
    client = AsyncMock()
    client.get.side_effect = values
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["pdf", "synctex"])
async def test_durable_anonymous_trial_never_uses_raw_cache_or_local_file(
    route, monkeypatch, tmp_path
):
    from app.api import routes

    job_id = str(uuid4())
    local_pdf = tmp_path / "resume.pdf"
    local_pdf.write_bytes(b"%PDF-unaccepted")
    monkeypatch.setattr(routes, "_assert_job_download_access", _metadata_ok)
    monkeypatch.setattr(routes, "get_job_files", lambda _job: (tmp_path, local_pdf, None))
    client = _redis(None, b"unaccepted cached bytes")
    with patch("app.core.redis.get_redis_client", new=AsyncMock(return_value=client)):
        call = (
            routes.download_pdf(job_id, None, _AuthorityDB(job_id=job_id, durable_state="completed"))
            if route == "pdf"
            else routes.download_synctex(job_id, None, _AuthorityDB(job_id=job_id, durable_state="completed"))
        )
        with pytest.raises(HTTPException) as caught:
            await call

    assert caught.value.status_code == 404
    # The first read checks for a render manifest; the raw artifact key is not read.
    assert client.get.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["pdf", "synctex"])
@pytest.mark.parametrize("durable_state", ["pending", "committing", "cancelled", "expired", "foreign", "unknown"])
async def test_durable_authority_blocks_legacy_transport_even_when_recovery_is_ineligible(
    route, durable_state, monkeypatch, tmp_path
):
    """Any durable row fences transient output; eligible lookup may still recover accepted PDFs."""
    from app.api import routes

    job_id, user_id = str(uuid4()), str(uuid4())
    monkeypatch.setattr(routes, "_assert_job_download_access", _metadata_ok)
    local_pdf = tmp_path / "resume.pdf"
    local_pdf.write_bytes(b"%PDF-unaccepted")
    monkeypatch.setattr(routes, "get_job_files", lambda _job: (tmp_path, local_pdf, None))
    client = _redis(None, b"unaccepted cached bytes")
    db = _AuthorityDB(job_id=job_id, durable_state=durable_state)
    with (
        patch("app.core.redis.get_redis_client", new=AsyncMock(return_value=client)),
        patch.object(
            routes,
            "_lookup_owned_durable_pdf",
            new=AsyncMock(side_effect=HTTPException(404, "PDF not found")),
        ) as lookup,
        patch(
            "app.api.render_artifact_routes.serve_artifact",
            new=AsyncMock(side_effect=HTTPException(404, "SyncTeX data not found")),
        ) as serve,
    ):
        call = (
            routes.download_pdf(job_id, user_id, db)
            if route == "pdf"
            else routes.download_synctex(job_id, user_id, db)
        )
        with pytest.raises(HTTPException) as caught:
            await call

    assert caught.value.status_code == 404
    assert lookup.await_count == (1 if route == "pdf" else 0)
    assert serve.await_count == (1 if route == "synctex" else 0)
    assert client.get.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["pdf", "synctex"])
async def test_authority_database_failure_blocks_legacy_fallback(route, monkeypatch, tmp_path):
    from app.api import routes

    job_id = str(uuid4())
    monkeypatch.setattr(routes, "_assert_job_download_access", _metadata_ok)
    monkeypatch.setattr(routes, "get_job_files", lambda _job: (tmp_path, tmp_path / "absent.pdf", None))
    client = _redis(None, b"unaccepted cached bytes")
    with patch("app.core.redis.get_redis_client", new=AsyncMock(return_value=client)):
        call = (
            routes.download_pdf(job_id, str(uuid4()), _AuthorityDB(job_id=job_id, error=RuntimeError("db down")))
            if route == "pdf"
            else routes.download_synctex(job_id, str(uuid4()), _AuthorityDB(job_id=job_id, error=RuntimeError("db down")))
        )
        with pytest.raises(HTTPException) as caught:
            await call

    assert caught.value.status_code == 503
    assert client.get.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["pdf", "synctex"])
async def test_legacy_cache_still_serves_jobs_without_durable_authority(route, monkeypatch, tmp_path):
    from app.api import routes

    job_id = str(uuid4())
    monkeypatch.setattr(routes, "_assert_job_download_access", _metadata_ok)
    monkeypatch.setattr(routes, "get_job_files", lambda _job: (tmp_path, tmp_path / "absent.pdf", None))
    cached = b"%PDF-legacy" if route == "pdf" else b"legacy synctex"
    transported = base64.b64encode(cached) if route == "pdf" else cached
    client = _redis(None, transported)
    with patch("app.core.redis.get_redis_client", new=AsyncMock(return_value=client)):
        response = (
            await routes.download_pdf(job_id, None, _AuthorityDB(job_id=job_id))
            if route == "pdf"
            else await routes.download_synctex(job_id, None, _AuthorityDB(job_id=job_id))
        )

    assert isinstance(response, Response)
    assert response.body == cached


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["pdf", "synctex"])
async def test_valid_manifest_reader_remains_preferred(route, monkeypatch):
    from app.api import routes

    job_id, user_id = str(uuid4()), str(uuid4())
    monkeypatch.setattr(routes, "_assert_job_download_access", _metadata_ok)
    manifest_response = Response(content=b"accepted manifest artifact")
    client = _redis(b"manifest-pointer")
    with (
        patch("app.core.redis.get_redis_client", new=AsyncMock(return_value=client)),
        patch(
            "app.api.render_artifact_routes.serve_artifact",
            new=AsyncMock(return_value=manifest_response),
        ) as serve,
    ):
        response = (
            await routes.download_pdf(job_id, user_id, _AuthorityDB(job_id=job_id, durable_state="completed"))
            if route == "pdf"
            else await routes.download_synctex(job_id, user_id, _AuthorityDB(job_id=job_id, durable_state="completed"))
        )

    assert response is manifest_response
    assert serve.await_count == 1

