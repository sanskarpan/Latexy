"""The derived anonymous-share job family is fenced without a Compilation row."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.render_artifact_routes import _durable_fence
from app.services.render_engine.artifacts import ObjectRef, RenderManifest, sha256


def _manifest(*, job_id: str, owner: str, resume_id: str, branch: str = "draft") -> RenderManifest:
    pdf = ObjectRef(
        key="render-artifacts/v1/" + "a" * 64 + "/pdf/" + "b" * 64 + ".pdf",
        sha256="b" * 64,
        size=5,
        media_type="application/pdf",
    )
    return RenderManifest(
        schema_version=1,
        artifact_id="c" * 64,
        job_id=job_id,
        owner_scope_sha256=sha256(f"user:{owner}"),
        owner_token_sha256=sha256("lease-secret"),
        owner_epoch=3,
        owner_scope_kind="user",
        created_at=int(time.time()) - 2,
        expires_at=int(time.time()) + 120,
        source_sha256="d" * 64,
        render_source_sha256="e" * 64,
        settings_sha256="f" * 64,
        engine_fingerprint="test-engine",
        renderer_epoch="test-epoch",
        compiler="pdflatex",
        document_id=resume_id,
        content_revision=9,
        branch=branch,
        pdf=pdf,
    )


def _row(manifest: RenderManifest, *, owner: str, **overrides):
    values = {
        "user_id": owner,
        "job_type": "anonymous_share",
        "cancel_requested": False,
        "state": "completed",
        "owner_epoch": manifest.owner_epoch,
        "owner_token": "lease-secret",
        "expires_at": datetime.fromtimestamp(manifest.expires_at + 100, timezone.utc),
        "terminal_result": "completed",
        "result_payload": {"success": True, "artifact": manifest.public()},
        "compilation_id": None,
        "resume_id": manifest.document_id,
        "pdf_path": manifest.pdf.key,
        "pdf_size": manifest.pdf.size,
        "pdf_sha256": manifest.pdf.sha256,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _OneRowDB:
    def __init__(self, row):
        self.row = row
        self.execute_calls = 0

    async def execute(self, _query):
        self.execute_calls += 1
        return SimpleNamespace(first=lambda: (self.row, True, time.time()))


@pytest.mark.asyncio
async def test_anonymous_share_finalization_authorizes_derived_artifact_without_compilation():
    owner = "owner-1"
    manifest = _manifest(job_id="share-job-1", owner=owner, resume_id="resume-1")
    db = _OneRowDB(_row(manifest, owner=owner))
    redis = SimpleNamespace(eval=AsyncMock(return_value=1))

    row = await _durable_fence(db, redis, manifest, owner, export=True)

    assert row.job_type == "anonymous_share"
    assert row.compilation_id is None
    assert db.execute_calls == 1  # no Compilation authorization/query for this family
    redis.eval.assert_awaited_once()


@pytest.mark.parametrize(
    "overrides,branch,export",
    [
        ({"compilation_id": "unexpected"}, "draft", True),
        ({"resume_id": "different-resume"}, "draft", True),
        ({}, "candidate", True),
        ({"terminal_result": "failed"}, "draft", True),
        ({"result_payload": {"success": False}}, "draft", True),
        ({"cancel_requested": True}, "draft", True),
        ({}, "draft", False),
    ],
)
@pytest.mark.asyncio
async def test_anonymous_share_derived_family_rejects_unbound_or_nonterminal_rows(
    overrides, branch, export
):
    owner = "owner-1"
    manifest = _manifest(job_id="share-job-2", owner=owner, resume_id="resume-1", branch=branch)
    db = _OneRowDB(_row(manifest, owner=owner, **overrides))
    redis = SimpleNamespace(eval=AsyncMock(return_value=1))

    with pytest.raises(HTTPException):
        await _durable_fence(db, redis, manifest, owner, export=export)
    redis.eval.assert_not_awaited()

