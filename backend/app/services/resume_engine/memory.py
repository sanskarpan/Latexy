"""Bounded user choices scoped to the same JD and unchanged semantic node.

Choices guide wording only. They never become facts or override current source.
The run freezes this projection so retries cannot acquire changed preferences.
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import func, select

from ...database.models import JobFinalization, ResumeOptimizationRun
from .acceptance import valid_run_result
from .semantic import node_hash

MAX_CHOICES = 16
MAX_ALTERNATIVE_CHARACTERS = 1000


def project_choices(runs, document: dict, requirements: dict) -> dict:
    nodes = {node["node_id"]: node for node in document["nodes"]}
    choices, seen = [], set()
    for run in runs:
        old_requirements = (run.context_payload or {}).get("requirements", {})
        if (old_requirements.get("jd_hash") != requirements["jd_hash"]
                or old_requirements.get("language") != requirements["language"]
                or old_requirements.get("version") != requirements["version"]
                or not valid_run_result(run.result)):
            continue
        decisions = (run.decisions or {}).get("patches", {})
        for patch in (run.result or {}).get("patches", [])[:100]:
            identity, alternative = patch.get("node_id"), patch.get("text")
            decision = decisions.get(patch.get("patch_id"))
            node = nodes.get(identity)
            if (node is None or not isinstance(alternative, str)
                    or len(alternative) > MAX_ALTERNATIVE_CHARACTERS
                    or decision not in {"accepted", "rejected"}):
                continue
            expected = (node_hash(identity, alternative) if decision == "accepted"
                        else patch.get("expected_node_revision"))
            if node["node_revision"] != expected:
                continue
            key = (identity, alternative)
            if key in seen:
                continue
            seen.add(key)
            choices.append({"node_id": identity, "node_revision": node["node_revision"],
                            "decision": decision, "alternative_text": alternative})
            if len(choices) == MAX_CHOICES:
                break
        if len(choices) == MAX_CHOICES:
            break
    return {"version": "choices-v1", "provenance": "user_wording_choice_not_factual_verification",
            "jd_hash": requirements["jd_hash"], "choices": choices}


async def load_choices(session, *, user_id: str, resume_id: str, job_id: str,
                       document: dict, requirements: dict) -> dict:
    rows = (await session.execute(select(ResumeOptimizationRun.result, ResumeOptimizationRun.decisions,
                                         ResumeOptimizationRun.context_payload["requirements"].label("requirements"))
        .join(JobFinalization, JobFinalization.job_id == ResumeOptimizationRun.job_id)
        .where(ResumeOptimizationRun.user_id == user_id, ResumeOptimizationRun.resume_id == resume_id,
               ResumeOptimizationRun.id != job_id, ResumeOptimizationRun.status.in_(["completed", "partial"]),
               func.pg_column_size(ResumeOptimizationRun.result) <= 65536,
               ResumeOptimizationRun.expires_at > func.clock_timestamp(), JobFinalization.user_id == user_id,
               JobFinalization.state == "completed", JobFinalization.cancel_requested.is_(False),
               JobFinalization.expires_at > func.clock_timestamp())
        .order_by(ResumeOptimizationRun.updated_at.desc(), ResumeOptimizationRun.id.desc()).limit(5)
        .execution_options(populate_existing=True))).all()
    return project_choices([SimpleNamespace(result=row.result, decisions=row.decisions,
                                           context_payload={"requirements": row.requirements}) for row in rows],
                           document, requirements)
