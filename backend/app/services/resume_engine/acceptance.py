"""Authoritative candidate export receipt, separate from preview readiness."""

from datetime import datetime, timezone

from sqlalchemy import func, select

from ...database.models import JobFinalization, Resume, ResumeOptimizationRun
from .document import digest
from .semantic import DocumentConflict, node_hash
from .stages import stage_fingerprint


def validate_factual_dependencies(document: dict, context: dict, proposed: list[dict],
                                  candidates: list[dict], statuses: dict, *, effort: str) -> None:
    """Recheck reviewed evidence before merging any new accepted changes.

    A prior explicit acceptance from this same run can restate a frozen fact.
    An unrelated user/AI edit cannot silently substitute different evidence.
    Global/summary reviews depend on the entire original factual scope; Quick
    entry reviews depend on their entry scopes and explicit evidence IDs.
    """
    if not proposed:
        return
    facts = context.get("facts")
    if not isinstance(facts, list) or not facts or len(facts) > 400:
        raise DocumentConflict("Reviewed factual context is unavailable")
    nodes = {node["node_id"]: node for node in document["nodes"]}
    by_fact = {fact["fact_id"]: fact for fact in facts}
    scopes = {(nodes.get(patch["node_id"], {}).get("section"),
               nodes.get(patch["node_id"], {}).get("entry_id")) for patch in proposed}
    global_scope = effort != "quick" or ("summary", None) in scopes
    relevant = list(facts) if global_scope else [fact for fact in facts if (fact["section"], fact.get("entry_id")) in scopes]
    for patch in proposed:
        evidence = patch.get("evidence_ids")
        if not isinstance(evidence, list) or not evidence or any(identity not in by_fact for identity in evidence):
            raise DocumentConflict("Reviewed factual evidence is unavailable")
        relevant.extend(by_fact[identity] for identity in evidence)
    relevant_ids = {fact["node_id"] for fact in relevant}
    explicit_ids = {by_fact[identity]["node_id"] for patch in proposed for identity in patch["evidence_ids"]}
    current_ids = {identity for identity, node in nodes.items() if node["text"].strip()
                   and (global_scope or (node["section"], node.get("entry_id")) in scopes or identity in explicit_ids)}
    if current_ids != relevant_ids:
        raise DocumentConflict("Supporting experience changed; start a fresh review")
    accepted = {patch["node_id"]: patch for patch in candidates if statuses.get(patch["patch_id"]) == "accepted"}
    for fact in relevant:
        node = nodes.get(fact["node_id"])
        if node and node["node_revision"] == fact["node_revision"]:
            continue
        prior = accepted.get(fact["node_id"])
        if (node and prior and prior["expected_node_revision"] == fact["node_revision"]
                and node["text"] == prior["text"]
                and node["node_revision"] == node_hash(node["node_id"], prior["text"])):
            continue
        raise DocumentConflict("Supporting experience changed; start a fresh review")


def valid_run_result(result) -> bool:
    if not isinstance(result, dict):
        return False
    try:
        return result.get("result_sha256") == stage_fingerprint(
            {key: value for key, value in result.items() if key != "result_sha256"}
        )
    except (TypeError, ValueError):
        return False


async def is_candidate_export_accepted(db, run_id: str, user_id: str, source_sha256: str) -> bool:
    row = (
        await db.execute(
            select(ResumeOptimizationRun, Resume, JobFinalization)
            .join(Resume, Resume.id == ResumeOptimizationRun.resume_id)
            .join(JobFinalization, JobFinalization.job_id == ResumeOptimizationRun.job_id)
            .where(
                ResumeOptimizationRun.id == run_id, ResumeOptimizationRun.user_id == user_id, Resume.user_id == user_id
            )
            .where(JobFinalization.expires_at > func.clock_timestamp())
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if not row:
        return False
    run, resume, arbiter = row
    receipt = run.decisions or {}
    return (
        receipt.get("complete_acceptance") is True
        and valid_run_result(run.result)
        and arbiter.state == "completed"
        and not arbiter.cancel_requested
        and run.expires_at > datetime.now(timezone.utc)
        and run.status in {"completed", "partial"}
        and receipt.get("accepted_source_sha256") == source_sha256
        and (run.result or {}).get("candidate_source_sha256") == source_sha256
        and receipt.get("accepted_content_revision") == resume.content_revision
        and digest(resume.latex_content) == source_sha256
    )
