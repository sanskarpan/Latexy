"""Durable paid-stage intents, checked against Redis and the DB job arbiter."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ...core.config import settings
from ...database.models import JobFinalization, ResumeOptimizationRun, ResumeOptimizationStage, ResumeRequirementContext
from ...utils.db_url import normalize_database_url
from ...workers.job_lifecycle import current_owner, current_owner_epoch, lifecycle_key
from .budgets import BudgetExceeded, reconcile, reserve
from .stages import StageCheckpointError, stage_fingerprint

_CHECK_OWNER = """
local t=redis.call('TIME'); local now=tonumber(t[1])+tonumber(t[2])/1000000
if redis.call('HGET',KEYS[1],'status') ~= 'running' then return 0 end
if redis.call('HGET',KEYS[1],'owner') ~= ARGV[1] then return 0 end
if redis.call('HGET',KEYS[1],'epoch') ~= ARGV[2] then return 0 end
if redis.call('HGET',KEYS[1],'cancel_requested') == '1' then return 0 end
if tonumber(redis.call('HGET',KEYS[1],'lease_until') or '0') <= now then return 0 end
return 1
"""


class DurableOptimizationLedger:
    """No completed provider stage is repaid; ambiguous intents stop that stage.

    The caller captures the admitted Redis capability once. DB transactions lock
    the existing JobFinalization arbiter, so a replacement attempt cannot accept
    an obsolete owner's output. Redis continues to own admission/cancellation.
    """

    def __init__(self, redis, job_id: str, *, owner=None, epoch=None):
        self.redis = redis
        self.job_id = job_id
        self.owner = owner if owner is not None else current_owner(job_id)
        self.epoch = epoch if epoch is not None else current_owner_epoch(job_id)
        if not self.owner or type(self.epoch) is not int or self.epoch <= 0:
            raise StageCheckpointError("Semantic optimizer requires an admitted lifecycle capability")

    def check_owner(self):
        if self.redis.eval(_CHECK_OWNER, 1, lifecycle_key(self.job_id), self.owner, str(self.epoch)) != 1:
            raise StageCheckpointError("Optimization ownership expired or was cancelled")

    def _transaction(self, operation):
        self.check_owner()

        async def run():
            engine = create_async_engine(normalize_database_url(settings.DATABASE_URL), poolclass=NullPool)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with factory() as session:
                    arbiter = (
                        await session.execute(
                            select(JobFinalization).where(JobFinalization.job_id == self.job_id).with_for_update()
                        )
                    ).scalar_one_or_none()
                    valid = arbiter and arbiter.owner_token == self.owner and arbiter.owner_epoch == self.epoch
                    if not valid or arbiter.cancel_requested or arbiter.state != "pending":
                        raise StageCheckpointError("Durable optimization owner changed")
                    alive = await session.scalar(
                        select(JobFinalization.id).where(
                            JobFinalization.id == arbiter.id,
                            JobFinalization.lease_expires_at > text("clock_timestamp()"),
                        )
                    )
                    if not alive:
                        raise StageCheckpointError("Durable optimization lease expired")
                    result = await operation(session, arbiter)
                    self.check_owner()
                    await session.commit()
                    return result
            finally:
                await engine.dispose()

        return asyncio.run(run())

    def create_or_restore(
        self,
        *,
        user_id: str,
        resume_id: str,
        document: dict,
        context: dict,
        effort: str,
        provider: str,
        model: str,
        credential_scope: str,
        budget: dict,
    ) -> dict:
        fingerprint = stage_fingerprint(
            {
                "document": document,
                "context": context,
                "effort": effort,
                "provider": provider,
                "model": model,
                "credential_scope": credential_scope,
                "budget_policy": budget["policy"],
                "engine": "semantic-v1",
            }
        )

        async def operation(session, arbiter):
            if str(arbiter.user_id) != user_id or (arbiter.resume_id and str(arbiter.resume_id) != resume_id):
                raise StageCheckpointError("Optimization run owner/document differs from admission")
            row = (
                await session.execute(
                    select(ResumeOptimizationRun).where(ResumeOptimizationRun.id == self.job_id).with_for_update()
                )
            ).scalar_one_or_none()
            if row:
                if row.context_hash != fingerprint or row.user_id != user_id or row.resume_id != resume_id:
                    raise StageCheckpointError("Durable optimization context changed")
                if row.expires_at <= datetime.now(timezone.utc):
                    raise StageCheckpointError("Durable optimization run expired")
                if row.result is not None:
                    integrity = row.result.get("result_sha256")
                    unsigned = {key: value for key, value in row.result.items() if key != "result_sha256"}
                    if stage_fingerprint(unsigned) != integrity:
                        raise StageCheckpointError("Durable run result integrity failed")
                return {"result": row.result, "budget": row.budget, "status": row.status}
            # An absent durable run on redelivery cannot prove no paid work.
            if self.epoch > 1:
                raise StageCheckpointError("Cannot recreate a missing run after ownership takeover")
            # A takeover shares the original wall deadline; it never buys more
            # model time by recreating a monotonic deadline in another process.
            bounded_budget = {
                **budget,
                "deadline_at": budget.get("deadline_at", time.time() + budget["policy"]["deadline_seconds"]),
            }
            if len(json.dumps({"document": document, "context": context}, allow_nan=False).encode()) > 2_000_000:
                raise StageCheckpointError("Semantic context exceeds the durable snapshot limit")
            row = ResumeOptimizationRun(
                id=self.job_id,
                job_id=self.job_id,
                user_id=user_id,
                resume_id=resume_id,
                base_revision=document["content_revision"],
                source_sha256=document["source_sha256"],
                context_hash=fingerprint,
                effort=effort,
                provider=provider,
                model=model,
                credential_scope=credential_scope,
                snapshot=document,
                context_payload=context,
                budget=bounded_budget,
                status="running",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
            session.add(row)
            # Clean only this account's expired run context, never live jobs.
            await session.execute(
                delete(ResumeOptimizationRun).where(
                    ResumeOptimizationRun.user_id == user_id,
                    ResumeOptimizationRun.expires_at <= datetime.now(timezone.utc),
                    ResumeOptimizationRun.id != self.job_id,
                )
            )
            return {"result": None, "budget": bounded_budget, "status": "running"}

        return self._transaction(operation)

    def begin(self, stage_key: str, request: dict, reservation: dict) -> dict | None:
        input_hash = stage_fingerprint(request)

        async def operation(session, _):
            run = (
                await session.execute(
                    select(ResumeOptimizationRun).where(ResumeOptimizationRun.id == self.job_id).with_for_update()
                )
            ).scalar_one()
            previous = (
                await session.execute(
                    select(ResumeOptimizationStage)
                    .where(
                        ResumeOptimizationStage.run_id == self.job_id, ResumeOptimizationStage.stage_key == stage_key
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if previous:
                if previous.input_hash != input_hash:
                    raise StageCheckpointError("Paid stage input changed")
                if previous.status != "completed" or previous.output is None:
                    raise StageCheckpointError("Prior paid stage has an ambiguous or failed outcome")
                if stage_fingerprint(previous.output) != previous.output_hash:
                    raise StageCheckpointError("Durable stage output integrity failed")
                return {"output": previous.output, "usage": previous.usage}
            if run.status != "running":
                raise StageCheckpointError("Optimization run is already terminal")
            if time.time() >= run.budget["deadline_at"]:
                raise BudgetExceeded("Optimization deadline reached")
            run.budget = reserve(run.budget, **reservation)
            session.add(
                ResumeOptimizationStage(
                    run_id=self.job_id,
                    stage_key=stage_key,
                    input_hash=input_hash,
                    status="requesting",
                    owner_token=self.owner,
                    owner_epoch=self.epoch,
                    reserved_usage=reservation,
                )
            )
            return None

        return self._transaction(operation)

    def complete(self, stage_key: str, *, output: dict, usage: dict | None):
        encoded = json.dumps(output, allow_nan=False)
        if len(encoded.encode()) > 256_000:
            raise StageCheckpointError("Durable stage output is too large")

        async def operation(session, _):
            run = (
                await session.execute(
                    select(ResumeOptimizationRun).where(ResumeOptimizationRun.id == self.job_id).with_for_update()
                )
            ).scalar_one()
            row = (
                await session.execute(
                    select(ResumeOptimizationStage)
                    .where(
                        ResumeOptimizationStage.run_id == self.job_id, ResumeOptimizationStage.stage_key == stage_key
                    )
                    .with_for_update()
                )
            ).scalar_one()
            if row.status != "requesting" or row.owner_token != self.owner or row.owner_epoch != self.epoch:
                raise StageCheckpointError("Paid stage completion owner changed")
            run.budget = reconcile(run.budget, row.reserved_usage, usage)
            row.status, row.output, row.output_hash, row.usage = "completed", output, stage_fingerprint(output), usage
            row.completed_at = datetime.now(timezone.utc)

        self._transaction(operation)

    def fail(self, stage_key: str, *, error_code="provider_ambiguous", usage: dict | None = None):
        async def operation(session, _):
            run = (
                await session.execute(
                    select(ResumeOptimizationRun).where(ResumeOptimizationRun.id == self.job_id).with_for_update()
                )
            ).scalar_one()
            row = (
                await session.execute(
                    select(ResumeOptimizationStage)
                    .where(
                        ResumeOptimizationStage.run_id == self.job_id, ResumeOptimizationStage.stage_key == stage_key
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row and row.status == "requesting" and row.owner_token == self.owner and row.owner_epoch == self.epoch:
                run.budget = reconcile(run.budget, row.reserved_usage, usage)
                row.status, row.error_code, row.usage = "ambiguous", error_code[:64], usage
                row.completed_at = datetime.now(timezone.utc)

        self._transaction(operation)

    def finish(self, result: dict, status: str):
        if status not in {"completed", "partial", "failed", "cancelled"}:
            raise StageCheckpointError("Invalid run terminal state")
        if len(json.dumps(result, allow_nan=False).encode()) > 1_000_000:
            raise StageCheckpointError("Optimization result is too large")

        sealed_result = {**result, "result_sha256": stage_fingerprint(result)}

        async def operation(session, _):
            row = (
                await session.execute(
                    select(ResumeOptimizationRun).where(ResumeOptimizationRun.id == self.job_id).with_for_update()
                )
            ).scalar_one()
            if row.result is not None:
                if row.result != sealed_result:
                    raise StageCheckpointError("Durable run already has another result")
                return row.budget
            row.result, row.status = sealed_result, status
            return row.budget

        return self._transaction(operation)

    def requirements(self, *, user_id: str, extracted: dict) -> tuple[dict, bool]:
        cache_id = stage_fingerprint(
            {
                "user_id": user_id,
                "jd_hash": extracted["jd_hash"],
                "version": extracted["version"],
                "language": extracted["language"],
            }
        )

        async def operation(session, arbiter):
            if str(arbiter.user_id) != user_id:
                raise StageCheckpointError("Requirement cache owner changed")
            row = await session.get(ResumeRequirementContext, cache_id)
            now = datetime.now(timezone.utc)
            if row and row.expires_at > now:
                return row.requirements, True
            if row:
                row.requirements, row.expires_at = extracted, now + timedelta(days=7)
            else:
                session.add(
                    ResumeRequirementContext(
                        id=cache_id,
                        user_id=user_id,
                        jd_hash=extracted["jd_hash"],
                        version=extracted["version"],
                        language=extracted["language"],
                        requirements=extracted,
                        expires_at=now + timedelta(days=7),
                    )
                )
            # Bounded retention work is owner-scoped; account deletion cascades.
            await session.execute(
                delete(ResumeRequirementContext).where(
                    ResumeRequirementContext.user_id == user_id, ResumeRequirementContext.expires_at <= now
                )
            )
            return extracted, False

        return self._transaction(operation)

    def cache_requirement_refinement(self, *, user_id: str, job_description: str, extracted: dict, response: dict):
        """Only independently literal-validated JD goals enter this cache."""
        from .document import digest
        from .requirements import REFINEMENT_VERSION, refinement_cache_id, validate_refinement

        validate_refinement(response, extracted)
        cache_id = refinement_cache_id(user_id, job_description, extracted["language"])
        value = {"response": response, "version": REFINEMENT_VERSION,
                 "source_sha256": digest(job_description), "language": extracted["language"]}

        async def operation(session, arbiter):
            if str(arbiter.user_id) != user_id:
                raise StageCheckpointError("Requirement cache owner changed")
            expires = datetime.now(timezone.utc) + timedelta(days=7)
            statement = insert(ResumeRequirementContext).values(
                id=cache_id, user_id=user_id, jd_hash=extracted["jd_hash"], version=REFINEMENT_VERSION,
                language=extracted["language"], requirements=value, expires_at=expires,
            )
            await session.execute(statement.on_conflict_do_update(
                index_elements=[ResumeRequirementContext.id],
                set_={"requirements": value, "expires_at": expires},
            ))

        self._transaction(operation)
