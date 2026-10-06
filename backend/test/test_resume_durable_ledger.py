"""Real PostgreSQL + Redis tests for durable paid-stage fencing and receipts."""

import asyncio
import copy
import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.resume_engine_routes import Decisions, decide_run, get_run
from app.core.config import settings
from app.database.models import (
    Compilation,
    JobFinalization,
    Resume,
    ResumeOptimizationRun,
    ResumeOptimizationStage,
    ResumeTemplate,
    User,
)
from app.services.resume_engine.acceptance import is_candidate_export_accepted
from app.services.resume_engine.budgets import initial_budget
from app.services.resume_engine.context import build_context
from app.services.resume_engine.document import digest
from app.services.resume_engine.ledger import DurableOptimizationLedger
from app.services.resume_engine.semantic import apply_node_edits, project_managed_document
from app.services.resume_engine.service import run_semantic_optimization
from app.services.resume_engine.stages import StageCheckpointError, stage_fingerprint
from app.utils.db_url import normalize_database_url
from app.workers.job_lifecycle import clear_current_owner, lifecycle_key, set_current_capability


def database(operation):
    async def execute():
        engine = create_async_engine(normalize_database_url(settings.DATABASE_URL), poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                value = await operation(db)
                await db.commit()
                return value
        finally:
            await engine.dispose()

    return asyncio.run(execute())


@pytest.fixture
def admitted():
    user_id, resume_id, job_id = (str(uuid4()) for _ in range(3))
    template_id = str(uuid4())
    owner = "semantic-owner-" + str(uuid4())
    client = redis.Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    doc = project_managed_document(
        document_id=resume_id,
        owner_scope=user_id,
        content_revision=1,
        structured_content={
            "basics": {"name": "Jane"},
            "experience": [{"id": "role-a", "bullets": ["Built Python services"]}],
        },
        category="ats_safe",
        template_id=template_id,
    )

    async def create(db):
        db.add(User(id=user_id, email="semantic_scope_" + user_id + "@example.test", name="Semantic test"))
        await db.flush()
        db.add(
            ResumeTemplate(
                id=template_id, name="Semantic test template", category="ats_safe", latex_content=doc["_source"]
            )
        )
        await db.flush()
        db.add(
            Resume(
                id=resume_id,
                user_id=user_id,
                title="Semantic test",
                latex_content=doc["_source"],
                structured_content=doc["_structured_content"],
                content_source="builder",
                builder_status="active",
                selected_template_id=template_id,
            )
        )
        await db.flush()
        db.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                job_type="combined",
                user_id=user_id,
                resume_id=resume_id,
                owner_token=owner,
                owner_epoch=1,
                state="pending",
                cancel_requested=False,
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                expires_at=datetime.now(timezone.utc) + timedelta(days=40),
            )
        )

    database(create)
    client.hset(
        lifecycle_key(job_id),
        mapping={
            "status": "running",
            "owner": owner,
            "epoch": 1,
            "cancel_requested": 0,
            "lease_until": time.time() + 600,
        },
    )
    ledger = DurableOptimizationLedger(client, job_id, owner=owner, epoch=1)
    context = build_context(doc, "Python required")
    context["approved_scope"] = []
    context["direction"] = {"custom_instructions": ""}
    args = dict(
        user_id=user_id,
        resume_id=resume_id,
        document=doc,
        context=context,
        effort="quick",
        provider="openai",
        model="gpt-4o-mini",
        credential_scope=hashlib.sha256(b"semantic-test-key").hexdigest(),
        budget=initial_budget("quick"),
    )
    ledger.create_or_restore(**args)
    yield ledger, args, user_id, resume_id, job_id, client

    async def cleanup(db):
        user = await db.get(User, user_id)
        await db.delete(user)
        await db.flush()
        template = await db.get(ResumeTemplate, template_id)
        await db.delete(template)

    database(cleanup)
    client.delete(lifecycle_key(job_id))
    client.close()
    clear_current_owner(job_id)


def optimize(admitted):
    ledger, args, user_id, resume_id, job_id, client = admitted
    calls = []
    set_current_capability(job_id, ledger.owner, ledger.epoch)

    def create(**kwargs):
        data = json.loads(kwargs["messages"][1]["content"])["input"]
        calls.append(data)
        if "nodes" in data:
            node = data["nodes"][0]
            fact = next(f for f in data["facts"] if f["node_id"] == node["node_id"])
            value = {
                "patches": [
                    {
                        "node_id": node["node_id"],
                        "expected_node_revision": node["node_revision"],
                        "text": "Developed Python services",
                        "evidence_ids": [fact["fact_id"]],
                        "requirement_ids": [],
                        "reason": "Clearer action wording",
                    }
                ],
                "missing_evidence": [],
            }
        else:
            value = {
                "verdicts": [
                    {"patch_id": p["patch_id"], "supported": True, "reason": "Same action and tool"}
                    for p in data["candidates"]
                ]
            }
        return iter(
            [
                Obj(
                    usage=None, choices=[Obj(delta=Obj(content=json.dumps(value), refusal=None), finish_reason="stop")]
                ),
                Obj(usage=Obj(prompt_tokens=100, completion_tokens=40), choices=[]),
            ]
        )

    sdk = Obj(chat=Obj(completions=Obj(create=create)), close=lambda: None)
    kwargs = dict(
        job_id=job_id,
        source=args["document"]["_source"],
        job_description="Python required",
        user_id=user_id,
        metadata={
            "resume_id": resume_id,
            "optimization_effort": "quick",
            "expected_content_revision": 1,
            "expected_source_sha256": args["document"]["source_sha256"],
        },
        api_key="semantic-test-key",
        model="gpt-4o-mini",
        redis=client,
        cancelled=lambda: False,
        publish=lambda *a: None,
        client_factory=lambda **kw: sdk,
    )
    first = run_semantic_optimization(**kwargs)
    second = run_semantic_optimization(**kwargs)
    assert first[0][0] == second[0][0] and len(calls) == 2  # generation + independent review, never repaid
    return first


def test_actual_candidate_roundtrip_replay_then_explicit_acceptance(admitted):
    _, args, user_id, resume_id, job_id, _ = admitted
    stage, projection = optimize(admitted)
    assert "Developed Python services" in stage[0] and projection["source_sha256"] == digest(stage[0])

    async def accept(db):
        resume = await db.get(Resume, resume_id)
        assert resume.latex_content == args["document"]["_source"]  # candidate did not auto-save
        run = await db.get(ResumeOptimizationRun, job_id)
        arbiter = await db.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        arbiter.state = "completed"
        compilation = Compilation(
            user_id=user_id,
            resume_id=resume_id,
            job_id=job_id,
            status="success",
            pdf_path="isolated-candidate.pdf",
            artifact_branch="candidate",
            artifact_accepted=False,
        )
        db.add(compilation)
        await db.commit()
        patch_id = run.result["patches"][0]["patch_id"]
        response = await decide_run(
            resume_id,
            job_id,
            Decisions(
                accept_patch_ids=[patch_id],
                expected_content_revision=1,
                expected_source_sha256=args["document"]["source_sha256"],
            ),
            db,
            user_id,
        )
        assert response["document"]["content_revision"] == 2
        assert response["decisions"]["complete_acceptance"]
        await db.refresh(compilation)
        assert compilation.artifact_accepted is True
        assert await is_candidate_export_accepted(db, job_id, user_id, digest(stage[0]))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await decide_run(
                resume_id,
                job_id,
                Decisions(
                    reject_patch_ids=[patch_id], expected_content_revision=2, expected_source_sha256=digest(stage[0])
                ),
                db,
                user_id,
            )
        assert exc.value.status_code == 409

    database(accept)


def test_jd_paid_stage_replays_frozen_plan_despite_later_cache_change(admitted, monkeypatch):
    from app.database.models import ResumeRequirementContext
    from app.services.resume_engine.requirements import extract_requirements, refinement_cache_id

    ledger, args, user_id, resume_id, job_id, client = admitted
    description = "Budget management required"

    async def reset(db):
        await db.delete(await db.get(ResumeOptimizationRun, job_id))

    database(reset)
    set_current_capability(job_id, ledger.owner, ledger.epoch)
    base = extract_requirements(description)
    row = base["requirements"][0]
    response = {"items": [{"excerpt_id": row["requirement_id"], "start": 0, "end": len(description),
                           "text": description, "importance": "required",
                           "skills": [{"start": 0, "end": len("Budget management"),
                                       "text": "Budget management", "canonical": "budget management"}]}]}
    requests, generation_facts = [], []

    def create(**kwargs):
        data = json.loads(kwargs["messages"][1]["content"])["input"]
        requests.append(data)
        if "excerpts" in data:
            value = response
        else:
            generation_facts.append(data["facts"])
            assert any(item["skills"] == ["budget management"] for item in data["requirements"]["requirements"])
            value = {"patches": [], "missing_evidence": []}
        return iter([Obj(usage=None, choices=[Obj(delta=Obj(content=json.dumps(value), refusal=None), finish_reason="stop")]),
                     Obj(usage=Obj(prompt_tokens=80, completion_tokens=40), choices=[])])

    sdk = Obj(chat=Obj(completions=Obj(create=create)), close=lambda: None)
    kwargs = dict(job_id=job_id, source=args["document"]["_source"], job_description=description, user_id=user_id,
                  metadata={"resume_id": resume_id, "optimization_effort": "standard", "expected_content_revision": 1,
                            "expected_source_sha256": args["document"]["source_sha256"]},
                  api_key="semantic-test-key", model="gpt-4o-mini", redis=client,
                  cancelled=lambda: False, publish=lambda *a: None, client_factory=lambda **kw: sdk)
    finish = DurableOptimizationLedger.finish
    failed = []

    def fail_once(self, result, status):
        if not failed:
            failed.append(True)
            raise RuntimeError("Simulated finalization interruption after completed paid stages")
        return finish(self, result, status)

    monkeypatch.setattr(DurableOptimizationLedger, "finish", fail_once)
    with pytest.raises(RuntimeError, match="finalization interruption"):
        run_semantic_optimization(**kwargs)

    async def poison_cache(db):
        cached = await db.get(ResumeRequirementContext, refinement_cache_id(user_id, description, "en"))
        assert cached is not None
        cached.requirements = {"response": {"items": []}, "version": "requirements-semantic-v2",
                               "source_sha256": digest(description), "language": "en"}

    database(poison_cache)
    stage, _ = run_semantic_optimization(**kwargs)
    assert stage[0] == args["document"]["_source"] and len(requests) == 2
    assert all("budget" not in fact["text"].casefold() for facts in generation_facts for fact in facts)

    async def inspect(db):
        run = await db.get(ResumeOptimizationRun, job_id)
        assert run.context_payload["requirement_refinement_plan"]["mode"] == "model"
        assert run.budget["requests"] == 2 <= run.budget["policy"]["max_requests"]
        assert run.result["requirements"]["requirements"][0]["skills"] == ["budget management"]

    database(inspect)


def test_verified_patch_emits_before_other_group_finishes(admitted):
    ledger, args, user_id, resume_id, job_id, client = admitted
    structured = copy.deepcopy(args["document"]["_structured_content"])
    structured["experience"].append({"id": "role-b", "bullets": ["Built SQL services"]})
    doc = project_managed_document(
        document_id=resume_id,
        owner_scope=user_id,
        content_revision=2,
        structured_content=structured,
        category="ats_safe",
        template_id=args["document"]["template_id"],
    )

    async def replace(db):
        run = await db.get(ResumeOptimizationRun, job_id)
        await db.delete(run)
        resume = await db.get(Resume, resume_id)
        resume.latex_content, resume.structured_content = doc["_source"], doc["_structured_content"]

    database(replace)
    set_current_capability(job_id, ledger.owner, ledger.epoch)
    first_patch = threading.Event()
    events = []
    calls = []

    def create(**kwargs):
        data = json.loads(kwargs["messages"][1]["content"])["input"]
        calls.append(data)
        if "nodes" in data:
            node = data["nodes"][0]
            if node["entry_id"] == "role-b":
                assert first_patch.wait(5), "Service waited for all generators before verifying first patch"
            fact = next(f for f in data["facts"] if f["node_id"] == node["node_id"])
            value = {
                "patches": [
                    {
                        "node_id": node["node_id"],
                        "expected_node_revision": node["node_revision"],
                        "text": node["text"].replace("Built", "Developed"),
                        "evidence_ids": [fact["fact_id"]],
                        "requirement_ids": [],
                        "reason": "Clearer action wording",
                    }
                ],
                "missing_evidence": [],
            }
        else:
            value = {
                "verdicts": [
                    {"patch_id": p["patch_id"], "supported": True, "reason": "Same scoped facts"}
                    for p in data["candidates"]
                ]
            }
        return iter(
            [
                Obj(
                    usage=None, choices=[Obj(delta=Obj(content=json.dumps(value), refusal=None), finish_reason="stop")]
                ),
                Obj(usage=Obj(prompt_tokens=100, completion_tokens=40), choices=[]),
            ]
        )

    def publish(_job_id, event, payload):
        events.append((event, payload))
        if event == "patch.ready" and payload.get("provisional"):
            first_patch.set()

    sdk = Obj(chat=Obj(completions=Obj(create=create)), close=lambda: None)
    stage, _ = run_semantic_optimization(
        job_id=job_id,
        source=doc["_source"],
        job_description="Python and SQL required",
        user_id=user_id,
        metadata={
            "resume_id": resume_id,
            "optimization_effort": "quick",
            "expected_content_revision": 2,
            "expected_source_sha256": doc["source_sha256"],
        },
        api_key="semantic-test-key",
        model="gpt-4o-mini",
        redis=client,
        cancelled=lambda: False,
        publish=publish,
        client_factory=lambda **kw: sdk,
    )
    assert first_patch.is_set() and len(calls) == 4
    assert "Developed Python" in stage[0] and "Developed SQL" in stage[0]
    assert len(next(payload for event, payload in events if event == "review.ready")["final_patch_ids"]) == 2


def test_newer_same_node_edit_prevents_candidate_acceptance(admitted):
    _, args, user_id, resume_id, job_id, _ = admitted
    optimize(admitted)

    async def concurrent(db):
        resume = await db.get(Resume, resume_id)
        node = next(n for n in args["document"]["nodes"] if n["kind"] == "bullet")
        source, structured = apply_node_edits(
            args["document"],
            [
                {
                    "node_id": node["node_id"],
                    "expected_node_revision": node["node_revision"],
                    "text": "Built Python data services",
                }
            ],
            expected_revision=1,
            expected_source=args["document"]["source_sha256"],
        )
        resume.latex_content, resume.structured_content = source, structured
        arbiter = await db.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        arbiter.state = "completed"
        await db.commit()
        await db.refresh(resume)
        run = await db.get(ResumeOptimizationRun, job_id)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await decide_run(
                resume_id,
                job_id,
                Decisions(
                    accept_patch_ids=[run.result["patches"][0]["patch_id"]],
                    expected_content_revision=resume.content_revision,
                    expected_source_sha256=digest(source),
                    merge_disjoint=True,
                ),
                db,
                user_id,
            )
        assert exc.value.status_code == 409 and resume.latex_content == source

    database(concurrent)


@pytest.mark.parametrize(
    "attack,expected_status",
    [
        ("source", 409),
        ("revision", 409),
        ("hash", 409),
        ("anonymous", 422),
        ("family", 422),
        ("other-owner", 404),
        ("spend", 422),
        ("no-key", 503),
    ],
)
def test_generic_semantic_admission_rejects_before_quota_or_dispatch(admitted, monkeypatch, attack, expected_status):
    from fastapi import HTTPException

    from app.api import job_routes as routes

    _, args, user_id, resume_id, _, _ = admitted
    quota, dispatch = AsyncMock(return_value=None), AsyncMock()
    monkeypatch.setattr(routes, "_resolve_user_plan", AsyncMock(return_value="free"))
    monkeypatch.setattr(routes.api_key_service, "get_user_provider", AsyncMock(return_value=None))
    monkeypatch.setattr(routes, "_consume_job_quota", quota)
    monkeypatch.setattr(routes, "submit_async", dispatch)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "" if attack == "no-key" else "admission-test-key")
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "")
    metadata = {
        "resume_id": resume_id,
        "optimization_engine": "semantic_v1",
        "optimization_effort": "quick",
        "expected_content_revision": 1,
        "expected_source_sha256": args["document"]["source_sha256"],
    }
    source = args["document"]["_source"]
    if attack == "source":
        source += "\n% forged"
    if attack == "revision":
        metadata["expected_content_revision"] = 2
    if attack == "hash":
        metadata["expected_source_sha256"] = "0" * 64
    if attack == "spend":
        metadata["max_cost_usd"] = 1
    caller = None if attack == "anonymous" else str(uuid4()) if attack == "other-owner" else user_id
    request = routes.JobSubmissionRequest(
        job_type="llm_optimization" if attack == "family" else "combined",
        latex_content=source,
        job_description="Python required",
        metadata=metadata,
    )

    async def submit(db):
        with pytest.raises(HTTPException) as exc:
            await routes.submit_job(request, Obj(client=Obj(host="127.0.0.1")), db, caller)
        assert exc.value.status_code == expected_status

    database(submit)
    quota.assert_not_awaited()
    dispatch.assert_not_awaited()


def test_generic_semantic_admission_strips_autosave_bypass_metadata(admitted, monkeypatch):
    from app.api import job_routes as routes

    _, args, user_id, resume_id, _, _ = admitted
    quota, dispatch = AsyncMock(return_value=None), AsyncMock()
    monkeypatch.setattr(routes, "_resolve_user_plan", AsyncMock(return_value="free"))
    monkeypatch.setattr(routes.api_key_service, "get_user_provider", AsyncMock(return_value=None))
    monkeypatch.setattr(routes, "_consume_job_quota", quota)
    monkeypatch.setattr(routes, "submit_async", dispatch)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "admission-test-key")
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "")
    for name in ("_write_initial_redis_state", "_mark_dispatch_started", "_mark_dispatch_accepted"):
        monkeypatch.setattr(routes, name, AsyncMock(return_value=True))
    metadata = {
        "resume_id": resume_id,
        "optimization_engine": "semantic_v1",
        "optimization_effort": "quick",
        "expected_content_revision": 1,
        "expected_source_sha256": args["document"]["source_sha256"],
        "persist_optimized_resume": True,
        "expected_latex_content": "forged",
        "skip_auto_save": False,
        "branch": "draft",
    }

    async def submit(db):
        response = await routes.submit_job(
            routes.JobSubmissionRequest(
                job_type="combined",
                latex_content=args["document"]["_source"],
                job_description="Python required",
                metadata=metadata,
            ),
            Obj(client=Obj(host="127.0.0.1")),
            db,
            user_id,
        )
        assert response.success
        arbiter = await db.scalar(select(JobFinalization).where(JobFinalization.job_id == response.job_id))
        assert arbiter and not arbiter.resume_apply_requested

    database(submit)
    quota.assert_awaited_once()
    dispatch.assert_awaited_once()
    dispatched = dispatch.call_args.kwargs["metadata"]
    assert dispatched["branch"] == "candidate" and dispatched["skip_auto_save"] is True
    assert "persist_optimized_resume" not in dispatched and "expected_latex_content" not in dispatched


RESERVATION = {"input_tokens": 20, "output_tokens": 20, "cost_usd": 0.0001}


def test_one_intent_wins_concurrently_and_complete_is_reused(admitted):
    ledger, _, _, _, _, _ = admitted

    def begin():
        try:
            return ledger.begin("section.0", {"nodes": ["a"]}, RESERVATION)
        except StageCheckpointError:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: begin(), range(2)))
    assert results.count(None) == 1 and results.count("blocked") == 1
    output = {"patches": [], "missing_evidence": []}
    ledger.complete("section.0", output=output, usage={"input_tokens": 10, "output_tokens": 10, "cost_usd": 0.00001})
    restored = ledger.begin("section.0", {"nodes": ["a"]}, RESERVATION)
    assert restored["output"] == output
    with pytest.raises(StageCheckpointError):
        ledger.begin("section.0", {"nodes": ["changed"]}, RESERVATION)


def test_ambiguous_outcome_never_repaid_and_usage_ceiling_charged(admitted):
    ledger, args, *_ = admitted
    ledger.begin("section.0", {}, RESERVATION)
    ledger.fail("section.0")
    with pytest.raises(StageCheckpointError):
        ledger.begin("section.0", {}, RESERVATION)
    restored = ledger.create_or_restore(**args)
    assert restored["budget"]["usage_unknown"]
    assert restored["budget"]["cost_used"] == RESERVATION["cost_usd"]


def test_stale_owner_and_cancelled_owner_cannot_complete(admitted):
    ledger, _, _, _, job_id, client = admitted
    ledger.begin("section.0", {}, RESERVATION)
    client.hset(lifecycle_key(job_id), "epoch", "2")
    with pytest.raises(StageCheckpointError):
        ledger.complete("section.0", output={}, usage=None)
    client.hset(lifecycle_key(job_id), mapping={"epoch": 1, "cancel_requested": 1})
    with pytest.raises(StageCheckpointError):
        ledger.begin("section.1", {}, RESERVATION)


def test_durable_context_and_output_corruption_fail_closed(admitted):
    ledger, args, _, _, job_id, _ = admitted
    bad = copy.deepcopy(args)
    bad["context"]["version"] = "changed"
    with pytest.raises(StageCheckpointError):
        ledger.create_or_restore(**bad)
    ledger.begin("section.0", {}, RESERVATION)
    ledger.complete("section.0", output={"value": "original"}, usage=None)

    async def corrupt(db):
        await db.execute(
            update(ResumeOptimizationStage)
            .where(ResumeOptimizationStage.run_id == job_id)
            .values(output={"value": "tampered"})
        )

    database(corrupt)
    with pytest.raises(StageCheckpointError):
        ledger.begin("section.0", {}, RESERVATION)


def test_run_deadline_not_reset_and_source_revision_trigger_covers_all_writers(admitted):
    ledger, args, _, resume_id, _, _ = admitted
    first = ledger.create_or_restore(**args)
    second = ledger.create_or_restore(**args)
    assert first["budget"]["deadline_at"] == second["budget"]["deadline_at"]

    async def edit(db):
        row = await db.get(Resume, resume_id)
        row.latex_content += "\n% edit"
        row.content_revision = 999  # trigger defeats a forged revision
        await db.flush()
        await db.refresh(row)
        revision = row.content_revision
        row.title = "Title only"
        await db.flush()
        await db.refresh(row)
        return revision, row.content_revision

    assert database(edit) == (2, 2)


def test_export_receipt_invalidated_by_later_source_edit(admitted):
    ledger, _, user_id, resume_id, job_id, _ = admitted

    async def accept(db):
        run = await db.get(ResumeOptimizationRun, job_id)
        resume = await db.get(Resume, resume_id)
        sha = digest(resume.latex_content)
        run.status = "completed"
        result = {"candidate_source_sha256": sha}
        run.result = {**result, "result_sha256": stage_fingerprint(result)}
        arbiter = await db.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        arbiter.state = "completed"
        run.decisions = {
            "complete_acceptance": True,
            "accepted_source_sha256": sha,
            "accepted_content_revision": resume.content_revision,
        }
        await db.flush()
        before = await is_candidate_export_accepted(db, job_id, user_id, sha)
        resume.latex_content += "\n% later edit"
        await db.flush()
        await db.refresh(resume)
        after = await is_candidate_export_accepted(db, job_id, user_id, sha)
        return before, after

    assert database(accept) == (True, False)


def test_export_recheck_refreshes_identity_map_after_external_edit(admitted):
    _, _, user_id, resume_id, job_id, _ = admitted

    async def check(db):
        run = await db.get(ResumeOptimizationRun, job_id)
        resume = await db.get(Resume, resume_id)
        sha = digest(resume.latex_content)
        run.status = "completed"
        result = {"candidate_source_sha256": sha}
        run.result = {**result, "result_sha256": stage_fingerprint(result)}
        run.decisions = {
            "complete_acceptance": True,
            "accepted_source_sha256": sha,
            "accepted_content_revision": resume.content_revision,
        }
        arbiter = await db.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        arbiter.state = "completed"
        await db.commit()
        assert await is_candidate_export_accepted(db, job_id, user_id, sha)
        # Keep strongly referenced ORM rows across the simulated storage wait.
        # READ COMMITTED alone does not refresh SQLAlchemy's identity map.
        async with async_sessionmaker(db.bind, expire_on_commit=False)() as writer:
            await writer.execute(
                update(Resume).where(Resume.id == resume_id).values(latex_content=resume.latex_content + "\n% external")
            )
            await writer.commit()
        assert not await is_candidate_export_accepted(db, job_id, user_id, sha)
        assert resume.content_revision == 2

    database(check)


def test_expired_job_cannot_offer_or_record_candidate_acceptance(admitted):
    from fastapi import HTTPException

    _, args, user_id, resume_id, job_id, _ = admitted
    optimize(admitted)

    async def expired(db):
        arbiter = await db.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        arbiter.state = "completed"
        arbiter.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        response = await get_run(resume_id, job_id, db, user_id)
        assert response["acceptance_ready"] is False
        assert response["job_status"] == "unavailable"
        run = await db.get(ResumeOptimizationRun, job_id)
        with pytest.raises(HTTPException) as exc:
            await decide_run(
                resume_id,
                job_id,
                Decisions(
                    accept_patch_ids=[run.result["patches"][0]["patch_id"]],
                    expected_content_revision=1,
                    expected_source_sha256=args["document"]["source_sha256"],
                ),
                db,
                user_id,
            )
        assert exc.value.status_code == 409
        resume = await db.get(Resume, resume_id)
        assert resume.content_revision == 1

    database(expired)


@pytest.mark.parametrize("excluded", ["none", "user", "resume", "job", "expiry", "cancel", "pending"])
def test_user_wording_history_is_durably_scoped(admitted, excluded):
    from app.services.resume_engine.memory import load_choices

    _, args, user_id, resume_id, job_id, _ = admitted
    node = next(n for n in args["document"]["nodes"] if n["ai_editable"])

    async def check(db):
        run = await db.get(ResumeOptimizationRun, job_id)
        run.status = "completed"
        result = {"patches": [{"patch_id": "memory-fixture", "node_id": node["node_id"],
                              "expected_node_revision": node["node_revision"], "text": "Developed Python services"}]}
        run.result = {**result, "result_sha256": stage_fingerprint(result)}
        run.decisions = {"patches": {"memory-fixture": "rejected"}}
        arbiter = await db.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        arbiter.state = "completed"
        if excluded == "expiry":
            arbiter.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        if excluded == "cancel":
            arbiter.cancel_requested = True
        if excluded == "pending":
            arbiter.state = "pending"
        await db.flush()
        memory = await load_choices(db, user_id=str(uuid4()) if excluded == "user" else user_id,
                                   resume_id=str(uuid4()) if excluded == "resume" else resume_id,
                                   job_id=job_id if excluded == "job" else "new-run",
                                   document=args["document"], requirements=args["context"]["requirements"])
        assert bool(memory["choices"]) is (excluded == "none")

    database(check)
