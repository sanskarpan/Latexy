"""Direct-route reproductions for job ownership metadata shape handling.

These tests intentionally describe the fail-closed contract.  They use only
in-memory Redis/DB doubles, so they do not touch the shared test fixtures.
Missing owners and explicit identity conflicts must fail closed before reads
or mutations; documented explicit-owner legacy envelopes remain compatible.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.job_metadata import parse_ownership_metadata
from app.api.job_routes import (
    cancel_job,
    get_job_result,
    get_job_state,
    get_job_stream,
)
from app.api.routes import _assert_job_download_access
from app.api.ws_routes import _job_ws_access_ok
from app.workers.finalization_arbiter import FinalizationOutcome


class _Redis:
    def __init__(self, values: dict[str, object]):
        self.values = values

    async def get(self, key: str):
        return self.values.get(key)

    async def xrange(self, *_args, **_kwargs):
        return self.values.get("__stream__", [])

    async def zrevrange(self, *_args):
        return self.values.get("__zset__", [])


class _DB:
    def __init__(self):
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


def _key(job_id: str, suffix: str) -> str:
    return f"latexy:job:{job_id}:{suffix}"


def _state() -> str:
    return json.dumps(
        {"status": "processing", "stage": "compile", "percent": 50, "last_updated": 1.0}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [{}, {"job_id": str(uuid4()), "user_id": None}])
async def test_state_requires_explicit_owner_shape(metadata):
    """Absent owner or a metadata/job-id mismatch must not expose state."""
    job_id = str(uuid4())
    redis = _Redis({_key(job_id, "meta"): json.dumps(metadata), _key(job_id, "state"): _state()})
    with patch("app.api.job_routes.get_redis_client", new=AsyncMock(return_value=redis)):
        with pytest.raises(HTTPException) as denied:
            await get_job_state(job_id, db=None, user_id=None)
        assert denied.value.status_code == 503


@pytest.mark.asyncio
async def test_state_rejects_metadata_bound_to_a_different_job_key():
    job_id = str(uuid4())
    redis = _Redis(
        {
            _key(job_id, "meta"): json.dumps({"job_id": str(uuid4()), "user_id": "owner"}),
            _key(job_id, "state"): json.dumps(
                {"status": "completed", "stage": "done", "percent": 100, "last_updated": 1.0}
            ),
        }
    )
    with patch("app.api.job_routes.get_redis_client", new=AsyncMock(return_value=redis)):
        with pytest.raises(HTTPException) as denied:
            await get_job_state(job_id, db=None, user_id="owner")
        assert denied.value.status_code == 503


@pytest.mark.asyncio
async def test_result_with_missing_owner_does_not_expose_private_payload():
    job_id = str(uuid4())
    redis = _Redis(
        {
            _key(job_id, "meta"): json.dumps({}),
            _key(job_id, "result"): json.dumps(
                {"success": True, "job_id": job_id, "result": {"private": "resume"}}
            ),
        }
    )
    with patch("app.api.job_routes.get_redis_client", new=AsyncMock(return_value=redis)):
        with pytest.raises(HTTPException) as denied:
            await get_job_result(job_id, db=None, user_id=None)
        assert denied.value.status_code == 503


@pytest.mark.asyncio
async def test_stream_with_missing_owner_does_not_replay_private_events():
    job_id = str(uuid4())
    redis = _Redis(
        {
            _key(job_id, "meta"): json.dumps({}),
            "__stream__": [("1-0", {"payload": json.dumps({"private": "resume"})})],
        }
    )
    with patch("app.api.job_routes.get_redis_client", new=AsyncMock(return_value=redis)):
        with pytest.raises(HTTPException) as denied:
            await get_job_stream(job_id, user_id=None)
        assert denied.value.status_code == 503


@pytest.mark.asyncio
async def test_cancel_with_missing_owner_does_not_mutate_private_job():
    job_id = str(uuid4())
    redis = _Redis({_key(job_id, "meta"): json.dumps({})})
    db = _DB()
    arbiter = AsyncMock(return_value=FinalizationOutcome.ALREADY_COMPLETED)
    with (
        patch("app.api.job_routes.get_redis_client", new=AsyncMock(return_value=redis)),
        patch(
            "app.api.job_routes.request_cancel_finalization",
            new=arbiter,
        ),
    ):
        with pytest.raises(HTTPException) as denied:
            await cancel_job(job_id, db=db, user_id=None)
        assert denied.value.status_code == 503
    arbiter.assert_not_called()
    db.commit.assert_not_called()
    db.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_ws_missing_owner_and_mismatched_job_id_are_not_anonymous():
    job_id = str(uuid4())
    for metadata in (
        {},
        {"job_id": str(uuid4()), "user_id": None},
        {"job_id": str(uuid4()), "user_id": "owner"},
    ):
        redis = _Redis({_key(job_id, "meta"): json.dumps(metadata)})
        with patch("app.api.ws_routes.get_redis_client", new=AsyncMock(return_value=redis)):
            caller = "owner" if metadata.get("user_id") == "owner" else None
            assert await _job_ws_access_ok(job_id, caller) is False


@pytest.mark.asyncio
async def test_ws_explicit_anonymous_metadata_remains_allowed():
    job_id = str(uuid4())
    redis = _Redis({_key(job_id, "meta"): json.dumps({"job_id": job_id, "user_id": None})})
    with patch("app.api.ws_routes.get_redis_client", new=AsyncMock(return_value=redis)):
        assert await _job_ws_access_ok(job_id, None) is True


@pytest.mark.asyncio
async def test_download_metadata_job_id_must_match_lookup_key():
    job_id = str(uuid4())
    redis = AsyncMock()
    redis.get.return_value = json.dumps({"job_id": str(uuid4()), "user_id": "owner"})
    with patch("app.core.redis.get_redis_client", new=AsyncMock(return_value=redis)):
        with pytest.raises(HTTPException) as denied:
            await _assert_job_download_access(job_id, "owner")
        assert denied.value.status_code == 503


@pytest.mark.parametrize("raw", ["{", "[]", "null", '{"user_id": false}', '{"user_id": 1}', '{"user_id": ""}', '{"user_id": " "}'])
def test_invalid_owner_envelopes_are_503(raw):
    with pytest.raises(HTTPException) as denied:
        parse_ownership_metadata(raw, "synthetic-job")
    assert denied.value.status_code == 503


@pytest.mark.parametrize("owner", [None, "legacy-owner"])
def test_explicit_legacy_ownership_without_id_remains_compatible(owner):
    assert parse_ownership_metadata(json.dumps({"user_id": owner}), "legacy-job")["user_id"] == owner


@pytest.mark.asyncio
async def test_list_index_does_not_grant_access_to_other_or_malformed_job_metadata():
    from app.api.job_routes import list_jobs

    ids = [str(uuid4()) for _ in range(4)]
    values = {"__zset__": ids}
    for job_id in ids:
        values[_key(job_id, "state")] = _state()
    values[_key(ids[0], "meta")] = json.dumps({"job_id": ids[0], "user_id": "owner"})
    values[_key(ids[1], "meta")] = json.dumps({"job_id": ids[1], "user_id": "other-owner"})
    values[_key(ids[2], "meta")] = json.dumps({})
    # Fourth entry has no metadata at all.
    with patch("app.api.job_routes.get_redis_client", new=AsyncMock(return_value=_Redis(values))):
        response = await list_jobs(user_id="owner", limit=50)
    assert response.total_count == 1
    assert [job["job_id"] for job in response.jobs] == ids[:1]


@pytest.mark.asyncio
async def test_http_malformed_metadata_does_not_expose_cached_job_state(client):
    job_id = str(uuid4())
    redis = _Redis({_key(job_id, "meta"): "{}", _key(job_id, "state"): _state()})
    with patch("app.api.job_routes.get_redis_client", new=AsyncMock(return_value=redis)):
        response = await client.get(f"/jobs/{job_id}/state")
    assert response.status_code == 503
    payload = response.json()
    assert payload["detail"] == "Job ownership could not be verified"
    assert payload["error"]["message"] == payload["detail"]
    assert payload["error"]["code"] == "http_error"
    assert isinstance(payload["error"]["request_id"], str)
    assert set(payload) == {"detail", "error"}
