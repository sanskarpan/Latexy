"""Real Postgres/Redis coverage for the derived anonymous PDF lineage."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, select, update

from app.api import render_artifact_routes, routes
from app.database.models import Compilation, JobFinalization, Resume, User
from app.services.latex_pii_redactor import redact
from app.services.render_engine.artifacts import (
    ObjectRef,
    binary_key,
    canonical_json,
    parse_manifest,
    sha256,
)
from app.workers.finalization_arbiter import FinalizationOutcome, commit_success

PDF = b"%PDF-1.7\nredacted anonymous integration fixture\n"


@pytest.mark.asyncio
async def test_accepted_derived_anonymous_share_returns_pdf_without_compilation(
    db_session_factory, monkeypatch
):
    user_id, resume_id, share_job_id, ordinary_job_id = (str(uuid4()) for _ in range(4))
    share_token = "share_" + uuid4().hex
    owner_token = "owner_" + uuid4().hex
    latex = r"\documentclass{article}\begin{document}private@example.test\end{document}"
    redacted = redact(latex)
    scope = sha256(f"user:{user_id}")
    pdf = ObjectRef(
        key=binary_key(scope, sha256(PDF), "pdf"),
        sha256=sha256(PDF),
        size=len(PDF),
        media_type="application/pdf",
    )
    now = int(time.time())
    manifest_fields = {
        "schema_version": 1,
        "job_id": share_job_id,
        "owner_scope_sha256": scope,
        "owner_scope_kind": "user",
        "created_at": now - 1,
        "expires_at": now + 3600,
        "owner_token_sha256": sha256(owner_token),
        "owner_epoch": 1,
        "source_sha256": sha256(redacted),
        "render_source_sha256": sha256(redacted),
        "settings_sha256": sha256(canonical_json({})),
        "engine_fingerprint": "integration-fixture",
        "renderer_epoch": "integration-fixture",
        "compiler": "pdflatex",
        "document_id": resume_id,
        "content_revision": 4,
        "branch": "draft",
        "page_count": 1,
        "pdf": pdf.model_dump(),
        "synctex": None,
        "geometry": None,
    }
    manifest_fields["artifact_id"] = sha256(canonical_json(manifest_fields))
    manifest = parse_manifest(manifest_fields)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    share_lifecycle = f"latexy:job:{share_job_id}:lifecycle"
    share_pointer = f"latexy:job:{share_job_id}:artifact"
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)

    async with db_session_factory() as db:
        try:
            db.add(User(id=user_id, email=f"{user_id}@example.test", name="Anonymous fixture"))
            foreign_user_id = str(uuid4())
            db.add(User(id=foreign_user_id, email=f"{foreign_user_id}@example.test", name="Foreign fixture"))
            await db.flush()
            resume = Resume(
                id=resume_id,
                user_id=user_id,
                title="Integration resume",
                latex_content=latex,
                content_revision=4,
                resume_settings={
                    "share_anonymous": True,
                    "share_anonymous_job_id": share_job_id,
                },
                share_token=share_token,
                share_token_created_at=datetime.now(timezone.utc),
            )
            db.add(resume)
            await db.flush()
            # Preserve a normal accepted compilation to prove the derived
            # anonymous render does not pollute/replace ordinary history.
            ordinary = Compilation(
                id=str(uuid4()),
                user_id=user_id,
                resume_id=resume_id,
                job_id=ordinary_job_id,
                status="completed",
                pdf_path="compilations/original-accepted.pdf",
                pdf_size=123,
                artifact_accepted=True,
                artifact_branch="draft",
            )
            db.add(ordinary)
            db.add(JobFinalization(
                id=str(uuid4()),
                job_id=share_job_id,
                user_id=user_id,
                job_type="anonymous_share",
                compilation_id=None,
                resume_id=resume_id,
                owner_token=owner_token,
                owner_epoch=1,
                state="pending",
                cancel_requested=False,
                lease_expires_at=expires_at,
                expires_at=expires_at,
            ))
            await db.commit()

            outcome = await commit_success(
                db,
                job_id=share_job_id,
                owner_token=owner_token,
                owner_epoch=1,
                result_payload={"success": True, "artifact": manifest.public()},
                pdf_path=manifest.pdf.key,
                pdf_sha256=manifest.pdf.sha256,
                pdf_size=manifest.pdf.size,
                resume_id=resume_id,
                render_manifest=manifest_fields,
                require_pdf=True,
            )
            assert outcome is FinalizationOutcome.ACCEPTED
            await db.commit()

            terminal = await db.scalar(select(JobFinalization).where(
                JobFinalization.job_id == share_job_id
            ))
            assert terminal is not None
            assert terminal.state == "completed"
            assert terminal.terminal_result == "completed"
            assert terminal.compilation_id is None
            assert terminal.resume_id == resume_id
            assert terminal.result_payload["artifact"] == manifest.public()

            await redis.hset(share_lifecycle, mapping={
                "status": "completed",
                "epoch": 1,
                "cancel_requested": 0,
            })
            await redis.set(share_pointer, canonical_json(manifest.model_dump()).decode("utf-8"))
            monkeypatch.setattr(render_artifact_routes, "get_redis_client", lambda: _awaitable(redis))
            monkeypatch.setattr(
                render_artifact_routes.storage_service,
                "download_bytes",
                lambda key, max_bytes: PDF if key == manifest.pdf.key else None,
            )
            monkeypatch.setattr(
                render_artifact_routes.storage_service,
                "generate_presigned_url",
                lambda key, ttl=3600: f"https://storage.example/{key}?ttl={ttl}",
            )
            monkeypatch.setattr(routes.entitlement_service, "has_feature", _allow_feature)
            monkeypatch.setattr(routes, "_record_resume_view", _noop_view)

            from starlette.requests import Request

            request = Request({
                "type": "http", "http_version": "1.1", "method": "GET",
                "scheme": "http", "path": f"/share/{share_token}",
                "raw_path": f"/share/{share_token}".encode(),
                "query_string": b"", "headers": [],
                "client": ("test", 1234), "server": ("test", 80),
            })
            async def public_share():
                return await routes.get_shared_resume(share_token, request, db)

            response = await public_share()
            assert response.is_anonymous is True
            assert response.pdf_url == f"https://storage.example/{manifest.pdf.key}?ttl=3600"
            assert response.pdf_url is not None

            # Current source is rechecked on every public request.
            resume.latex_content = latex + "% changed after render"
            await db.commit()
            assert (await public_share()).pdf_url is None
            resume.latex_content = latex
            await db.commit()

            # The DB row's owner and cancellation state remain authoritative.
            await db.execute(update(JobFinalization).where(
                JobFinalization.job_id == share_job_id
            ).values(user_id=foreign_user_id))
            await db.commit()
            assert (await public_share()).pdf_url is None
            await db.execute(update(JobFinalization).where(
                JobFinalization.job_id == share_job_id
            ).values(user_id=user_id))
            await db.commit()
            await db.execute(update(JobFinalization).where(
                JobFinalization.job_id == share_job_id
            ).values(cancel_requested=True))
            await db.commit()
            assert (await public_share()).pdf_url is None
            await db.execute(update(JobFinalization).where(
                JobFinalization.job_id == share_job_id
            ).values(cancel_requested=False))
            await db.commit()

            # A review candidate is not a public draft, even if someone
            # replaces both the pointer and the bounded row artifact payload.
            candidate_fields = dict(manifest_fields)
            candidate_fields["branch"] = "candidate"
            candidate_fields["artifact_id"] = sha256(canonical_json({
                key: value for key, value in candidate_fields.items() if key != "artifact_id"
            }))
            candidate_manifest = parse_manifest(candidate_fields)
            await db.execute(update(JobFinalization).where(
                JobFinalization.job_id == share_job_id
            ).values(result_payload={"success": True, "artifact": candidate_manifest.public()}))
            await db.commit()
            await redis.set(share_pointer, canonical_json(candidate_manifest.model_dump()).decode("utf-8"))
            assert (await public_share()).pdf_url is None
            await db.execute(update(JobFinalization).where(
                JobFinalization.job_id == share_job_id
            ).values(result_payload={"success": True, "artifact": manifest.public()}))
            await db.commit()
            await redis.set(share_pointer, canonical_json(manifest.model_dump()).decode("utf-8"))

            ordinary_after = await db.scalar(select(Compilation).where(
                Compilation.job_id == ordinary_job_id
            ))
            derived_compilation = await db.scalar(select(Compilation).where(
                Compilation.job_id == share_job_id
            ))
            assert ordinary_after.pdf_path == "compilations/original-accepted.pdf"
            assert ordinary_after.artifact_accepted is True
            assert derived_compilation is None
        finally:
            await db.rollback()
            await db.execute(delete(JobFinalization).where(JobFinalization.job_id == share_job_id))
            await db.execute(delete(Compilation).where(Compilation.job_id == ordinary_job_id))
            await db.execute(delete(Resume).where(Resume.id == resume_id))
            await db.execute(delete(User).where(User.id.in_([user_id, foreign_user_id])))
            await db.commit()
            await redis.delete(share_lifecycle, share_pointer, f"latexy:job:{share_job_id}:cancel")
            await redis.aclose()


async def _awaitable(value):
    return value


async def _allow_feature(*_args, **_kwargs):
    return True


async def _noop_view(*_args, **_kwargs):
    return None
