import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import render_artifact_routes as routes
from app.api.render_artifact_routes import _accepted_artifact_matches_resume


@pytest.fixture
def accepted_rows():
    now = datetime.now(timezone.utc)
    owner = "owner-a"
    resume_id = "resume-a"
    job_id = "job-a"
    compilation_id = "compilation-a"
    source_hash = "a" * 64
    artifact_id = "b" * 64
    resume = SimpleNamespace(id=resume_id, user_id=owner, content_revision=7, latex_content="current source")
    compilation = SimpleNamespace(
        id=compilation_id, job_id=job_id, user_id=owner, resume_id=resume_id,
        status="completed", artifact_accepted=True, artifact_branch="draft",
    )
    finalization = SimpleNamespace(
        user_id=owner, job_type="latex_compilation", state="completed", terminal_result="completed",
        cancel_requested=False, job_id=job_id, compilation_id=compilation_id, resume_id=resume_id,
        expires_at=now + timedelta(hours=1),
        result_payload={"artifact": {
            "job_id": job_id, "artifact_id": artifact_id, "document_id": resume_id,
            "content_revision": 7, "source_sha256": source_hash, "branch": "draft",
        }},
    )
    return finalization, compilation, resume, owner, source_hash, artifact_id


def test_current_owner_document_source_revision_is_recoverable(accepted_rows):
    finalization, compilation, resume, owner, source_hash, artifact_id = accepted_rows
    assert _accepted_artifact_matches_resume(finalization, compilation, resume, owner, source_hash) == artifact_id


@pytest.mark.parametrize("field,value", [
    ("user_id", "owner-b"),
    ("job_type", "combined"),
    ("state", "failed"),
    ("terminal_result", "failed"),
    ("cancel_requested", True),
    ("resume_id", "resume-b"),
    ("compilation_id", "compilation-b"),
])
def test_rejects_forged_or_nonaccepted_finalization(accepted_rows, field, value):
    finalization, compilation, resume, owner, source_hash, _ = accepted_rows
    setattr(finalization, field, value)
    assert _accepted_artifact_matches_resume(finalization, compilation, resume, owner, source_hash) is None


@pytest.mark.parametrize("field,value", [
    ("user_id", "owner-b"),
    ("resume_id", "resume-b"),
    ("status", "processing"),
    ("artifact_accepted", False),
    ("artifact_branch", "candidate"),
])
def test_rejects_unaccepted_compilation(accepted_rows, field, value):
    finalization, compilation, resume, owner, source_hash, _ = accepted_rows
    setattr(compilation, field, value)
    assert _accepted_artifact_matches_resume(finalization, compilation, resume, owner, source_hash) is None


@pytest.mark.parametrize("artifact_field,value,source_hash", [
    ("source_sha256", "c" * 64, "a" * 64),
    ("content_revision", 6, "a" * 64),
    ("document_id", "resume-b", "a" * 64),
    ("branch", "candidate", "a" * 64),
])
def test_rejects_stale_source_revision_or_document(accepted_rows, artifact_field, value, source_hash):
    finalization, compilation, resume, owner, _, _ = accepted_rows
    finalization.result_payload["artifact"][artifact_field] = value
    assert _accepted_artifact_matches_resume(finalization, compilation, resume, owner, source_hash) is None


def test_rejects_expired_artifact(accepted_rows):
    finalization, compilation, resume, owner, source_hash, _ = accepted_rows
    finalization.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert _accepted_artifact_matches_resume(finalization, compilation, resume, owner, source_hash) is None


class _Result:
    def __init__(self, *, resume=None, rows=()):
        self._resume = resume
        self._rows = rows

    def scalar_one_or_none(self):
        return self._resume

    def all(self):
        return self._rows


class _DB:
    def __init__(self, resume, rows):
        self._resume = resume
        self._rows = rows
        self._calls = 0

    async def execute(self, _query):
        self._calls += 1
        return _Result(resume=self._resume) if self._calls == 1 else _Result(rows=self._rows)


@pytest.mark.parametrize("failure", ["missing_manifest", "fence_404", "manifest_mismatch"])
def test_eligible_artifact_that_cannot_be_verified_is_retryable(monkeypatch, failure):
    owner = str(uuid4())
    resume_id = str(uuid4())
    job_id = str(uuid4())
    compilation_id = str(uuid4())
    source = "\\documentclass{article}\\begin{document}ok\\end{document}"
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    artifact_id = "b" * 64
    resume = SimpleNamespace(id=resume_id, user_id=owner, content_revision=3, latex_content=source)
    compilation = SimpleNamespace(
        id=compilation_id, job_id=job_id, user_id=owner, resume_id=resume_id,
        status="completed", artifact_accepted=True, artifact_branch="draft",
    )
    finalization = SimpleNamespace(
        user_id=owner, job_type="latex_compilation", state="completed", terminal_result="completed",
        cancel_requested=False, job_id=job_id, compilation_id=compilation_id, resume_id=resume_id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        result_payload={"artifact": {
            "job_id": job_id, "artifact_id": artifact_id, "document_id": resume_id,
            "content_revision": 3, "source_sha256": source_hash, "branch": "draft",
        }},
    )
    manifest = SimpleNamespace(
        job_id=job_id, artifact_id=artifact_id, document_id=resume_id,
        content_revision=3, source_sha256=source_hash, branch="draft",
    )

    async def get_redis():
        return object()

    async def load_manifest(*_args, **_kwargs):
        if failure == "missing_manifest":
            raise HTTPException(404)
        if failure == "manifest_mismatch":
            return SimpleNamespace(**{**vars(manifest), "source_sha256": "c" * 64})
        return manifest

    async def durable_fence(*_args, **_kwargs):
        if failure == "fence_404":
            raise HTTPException(404)
        return finalization

    monkeypatch.setattr(routes, "get_redis_client", get_redis)
    monkeypatch.setattr(routes, "load_manifest", load_manifest)
    monkeypatch.setattr(routes, "_durable_fence", durable_fence)
    db = _DB(resume, [(finalization, compilation)])

    with pytest.raises(HTTPException) as raised:
        asyncio.run(routes.latest_accepted_artifact(resume_id, owner, db))

    assert raised.value.status_code == 503
    assert raised.value.headers == {"Retry-After": "2"}
