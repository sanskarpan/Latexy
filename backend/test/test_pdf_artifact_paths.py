"""Regression tests for local compiled-artifact path and ownership guards."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


def test_get_job_files_rejects_path_traversal(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.utils.file_utils import get_job_files

    monkeypatch.setattr(settings, "TEMP_DIR", tmp_path)
    with pytest.raises(HTTPException) as caught:
        get_job_files("../../outside")
    assert caught.value.status_code == 400
    assert not (tmp_path / ".." / "outside").exists()


def test_document_delivery_rejects_non_uuid_job_id():
    from app.api.document_delivery_routes import _safe_temp_pdf

    assert _safe_temp_pdf(SimpleNamespace(job_id="../../outside")) is None


@pytest.mark.asyncio
async def test_download_ownership_fails_closed_when_redis_is_unavailable():
    from app.api import routes

    with patch(
        "app.core.redis.get_redis_client",
        new=AsyncMock(side_effect=ConnectionError("redis unavailable")),
    ):
        with pytest.raises(HTTPException) as caught:
            await routes._assert_job_download_access(str(uuid4()), "owner")
    assert caught.value.status_code == 503


@pytest.mark.asyncio
async def test_download_ownership_accepts_explicit_anonymous_metadata():
    from app.api import routes

    redis = AsyncMock()
    redis.get.return_value = json.dumps({"user_id": None})
    with patch("app.core.redis.get_redis_client", new=AsyncMock(return_value=redis)):
        await routes._assert_job_download_access(str(uuid4()), None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"job_id": "present-but-owner-missing"},
        {"user_id": 42},
        [],
    ],
)
async def test_download_ownership_rejects_metadata_without_valid_owner_field(metadata):
    from app.api import routes

    redis = AsyncMock()
    redis.get.return_value = json.dumps(metadata)
    with patch("app.core.redis.get_redis_client", new=AsyncMock(return_value=redis)):
        with pytest.raises(HTTPException) as caught:
            await routes._assert_job_download_access(str(uuid4()), None)
    assert caught.value.status_code == 503
