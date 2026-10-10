"""Adversarial semantic identity, fact boundaries, budgets and transport tests."""

import copy
import json
import threading
import time
from types import SimpleNamespace as Obj

import pytest

from app.api.resume_engine_routes import GuestDocument, GuestPatch, patch_guest, project_guest
from app.core.config import settings
from app.services.resume_engine.budgets import BudgetExceeded, initial_budget, reconcile, reserve
from app.services.resume_engine.context import build_context
from app.services.resume_engine.document import digest
from app.services.resume_engine.provider import ProviderSpec, SemanticProvider, resolve_provider
from app.services.resume_engine.semantic import (
    DocumentConflict,
    UnsupportedDocument,
    apply_node_edits,
    project_managed_document,
)
from app.services.resume_engine.semantic_patches import PATCH_SCHEMA, apply_verdicts, validate_candidates
from app.services.resume_engine.starter import project_starter_fields


def document(bullet="Built Python services reducing latency from 20 to 10 ms"):
    return project_managed_document(
        document_id="resume",
        owner_scope="user",
        content_revision=1,
        structured_content={
            "basics": {"name": "Jane", "summary": "Software developer"},
            "experience": [
                {
                    "id": "role-a",
                    "title": "Engineer",
                    "company": "Acme",
                    "bullets": [bullet],
                    "bullet_ids": ["bullet-a"],
                },
                {
                    "id": "role-b",
                    "title": "Engineer",
                    "company": "Beta",
                    "bullets": ["Managed AWS deployments"],
                    "bullet_ids": ["bullet-b"],
                },
            ],
        },
        category="ats_safe",
    )


def test_bounded_planner_prioritizes_supported_job_relevance_with_stable_ties():
    from app.services.resume_engine.requirements import extract_requirements
    from app.services.resume_engine.service import plan_groups

    doc = document()
    groups = plan_groups(doc, None, "quick", extract_requirements("AWS required. Python preferred."))
    assert len(groups) == 2
    assert groups[0][0]["entry_id"] == "role-b"
    assert groups[1][0]["entry_id"] == "role-a"
    assert all(len({(node["section"], node["entry_id"]) for node in group}) == 1 for group in groups)
    summary = plan_groups(doc, ["SUMMARY"], "quick", extract_requirements("AWS required"))
    assert all(node["section"] == "summary" for group in summary for node in group)


def proposal(doc, text, node=None, fact=None):
    node = node or next(n for n in doc["nodes"] if n["kind"] == "bullet")
    context = build_context(doc, "Required Python. AWS preferred.")
    fact = fact or next(f["fact_id"] for f in context["facts"] if f["node_id"] == node["node_id"])
    return (
        {
            "patches": [
                {
                    "node_id": node["node_id"],
                    "expected_node_revision": node["node_revision"],
                    "text": text,
                    "evidence_ids": [fact],
                    "requirement_ids": [],
                    "reason": "Clearer phrasing",
                }
            ],
            "missing_evidence": [],
        },
        context,
        node,
    )


def test_ids_survive_text_edit_and_entry_reorder():
    before = document()
    structured = copy.deepcopy(before["_structured_content"])
    structured["experience"][0]["bullets"][0] = "Developed Python services"
    structured["experience"].reverse()
    after = project_managed_document(
        document_id="resume", owner_scope="user", content_revision=2, structured_content=structured, category="ats_safe"
    )
    old = next(n for n in before["nodes"] if n["entry_id"] == "role-a" and n["kind"] == "bullet")
    new = next(n for n in after["nodes"] if n["entry_id"] == "role-a" and n["kind"] == "bullet")
    assert old["node_id"] == new["node_id"] and old["node_revision"] != new["node_revision"]


def test_disjoint_merge_preserves_newer_neighbor_and_rejects_same_node():
    doc = document()
    one = next(n for n in doc["nodes"] if n["kind"] == "bullet")
    two = next(n for n in doc["nodes"] if n["node_id"] == "basics.name")
    _, changed = apply_node_edits(
        doc,
        [{"node_id": two["node_id"], "expected_node_revision": two["node_revision"], "text": "Jane Doe"}],
        expected_revision=1,
        expected_source=doc["source_sha256"],
    )
    current = project_managed_document(
        document_id="resume", owner_scope="user", content_revision=2, structured_content=changed, category="ats_safe"
    )
    patch = {
        "node_id": one["node_id"],
        "expected_node_revision": one["node_revision"],
        "text": "Developed Python services",
    }
    _, merged = apply_node_edits(
        current, [patch], expected_revision=1, expected_source=doc["source_sha256"], merge_disjoint=True
    )
    assert merged["basics"]["name"] == "Jane Doe"
    newer = project_managed_document(
        document_id="resume", owner_scope="user", content_revision=3, structured_content=merged, category="ats_safe"
    )
    with pytest.raises(DocumentConflict):
        apply_node_edits(newer, [patch], expected_revision=1, expected_source=doc["source_sha256"], merge_disjoint=True)


@pytest.mark.parametrize(
    "text",
    [
        "Developed Python services reducing latency from 10 to 20 ms",  # same numbers reversed
        "Led Python services reducing latency from 20 to 10 ms",  # elevated responsibility
        "Built Java services reducing latency from 20 to 10 ms",  # unsupported skill
        "Built Python services reducing latency from 20 to 10 ms efficiently",  # unsupported intensity
        "Built Python services reducing latency from 20 to 10 ms\u202e",  # bidi
    ],
)
def test_rejects_fact_inversions_and_inventions(text):
    doc = document()
    value, context, node = proposal(doc, text)
    valid, rejected = validate_candidates(value, doc, context, {node["node_id"]})
    assert not valid and len(rejected) == 1


def test_rejects_negation_inversion_and_role_cross_evidence():
    doc = document("Built Python services, not Java services")
    value, context, node = proposal(doc, "Built Java services, not Python services")
    # Independent verifier must reject semantic attribution even where anchors
    # alone cannot prove word equivalence. Named technology order is a guard.
    valid, _ = validate_candidates(value, doc, context, {node["node_id"]})
    assert not valid
    other_fact = next(f["fact_id"] for f in context["facts"] if f["entry_id"] == "role-b")
    value["patches"][0]["evidence_ids"] = [other_fact]
    valid, rejected = validate_candidates(value, doc, context, {node["node_id"]})
    assert not valid and "another role" in rejected[0]["reason"]


def test_substantive_rephrase_requires_explicit_independent_support():
    doc = document("Built Python services reducing latency from 20 to 10 ms")
    value, context, node = proposal(doc, "Developed Python services that reduced latency from 20 to 10 ms")
    valid, rejected = validate_candidates(value, doc, context, {node["node_id"]})
    assert len(valid) == 1 and not rejected
    assert apply_verdicts(valid, {"verdicts": []})[0] == []
    supported, _ = apply_verdicts(
        valid,
        {
            "verdicts": [
                {"patch_id": valid[0]["patch_id"], "supported": True, "reason": "Same scoped action and metric"}
            ]
        },
    )
    assert supported[0]["validation"] == "source_guard_and_independent_review"


def test_exact_source_discrepancy_is_never_overwritten():
    doc = document()
    with pytest.raises(UnsupportedDocument):
        project_managed_document(
            document_id="resume",
            owner_scope="user",
            content_revision=1,
            structured_content=doc["_structured_content"],
            category="ats_safe",
            source=doc["_source"] + "% custom",
        )


@pytest.mark.asyncio
async def test_guest_edits_keep_all_opaque_bytes_and_reject_stale_snapshot():
    source = "\\documentclass{article}\n\\begin{document}\n% untouched\n\\section{Experience}\n\\begin{itemize}\n\\item Built Python services\n\\end{itemize}\n\\end{document}\n"
    projected = await project_guest(GuestDocument(latex_content=source))
    node = projected["document"]["nodes"][0]
    body = GuestPatch(
        latex_content=source,
        expected_source_sha256=digest(source),
        patches=[
            {
                "node_id": node["node_id"],
                "expected_node_revision": node["node_revision"],
                "text": "Developed Python services",
            }
        ],
    )
    result = await patch_guest(body)
    assert result["latex_content"] == source.replace("Built Python services", "Developed Python services")
    assert result["document"]["source_mode"] == "imported" and not result["document"]["nodes"][0]["ai_editable"]
    from fastapi import HTTPException

    body.expected_source_sha256 = "0" * 64
    with pytest.raises(HTTPException) as exc:
        await patch_guest(body)
    assert exc.value.status_code == 409


def test_hard_budget_reservations_and_missing_usage():
    budget = initial_budget("quick", 0.001)
    reservation = {"input_tokens": 10, "output_tokens": 10, "cost_usd": 0.0004}
    budget = reserve(budget, **reservation)
    budget = reconcile(budget, reservation, None)
    assert budget["usage_unknown"] and budget["cost_used"] == 0.0004
    budget = reserve(budget, **reservation)
    with pytest.raises(BudgetExceeded):
        reserve(budget, **reservation)
    with pytest.raises(BudgetExceeded):
        reconcile(budget, reservation, {"input_tokens": 1, "output_tokens": 1, "cost_usd": True})


class FakeLedger:
    def __init__(self):
        self.job_id = "fake-semantic-job"
        self.intents = {}
        self.calls = 0
        self.redis = Obj(eval=lambda *args: 1)

    def begin(self, key, request, reservation):
        if key in self.intents:
            row = self.intents[key]
            if row.get("output") is None:
                raise RuntimeError("ambiguous stage")
            return row
        self.intents[key] = {"reservation": reservation}
        self.calls += 1

    def complete(self, key, output, usage):
        self.intents[key].update(output=output, usage=usage)

    def fail(self, key, **kwargs):
        self.intents[key]["failed"] = True

    def check_owner(self):
        return None


def chunks(value, finish="stop"):
    return iter(
        [
            Obj(usage=None, choices=[Obj(delta=Obj(content=json.dumps(value), refusal=None), finish_reason=finish)]),
            Obj(usage=Obj(prompt_tokens=30, completion_tokens=20), choices=[]),
        ]
    )


def test_provider_completed_stage_reuses_without_second_call():
    ledger = FakeLedger()
    calls = []
    client = Obj(
        chat=Obj(
            completions=Obj(create=lambda **kw: calls.append(kw) or chunks({"patches": [], "missing_evidence": []}))
        ),
        close=lambda: None,
    )
    provider = SemanticProvider(
        spec=ProviderSpec("openai", "gpt-4o-mini", None, 0.15, 0.6, True),
        api_key="test-key",
        ledger=ledger,
        deadline=time.monotonic() + 3,
        cancelled=lambda: False,
        owner_scope="test",
        client_factory=lambda **kw: client,
    )
    kwargs = dict(system="Only JSON", payload={"unicode": "你好"}, schema=PATCH_SCHEMA)
    first = provider.generate("one", **kwargs)
    second = provider.generate("one", **kwargs)
    assert len(calls) == ledger.calls == 1 and second[2] and not first[2]
    assert ledger.intents["one"]["reservation"]["input_tokens"] >= len(calls[0]["messages"][1]["content"].encode())
    assert calls[0]["stream_options"] == {"include_usage": True}
    provider.close()


def test_provider_watchdog_arms_before_headers_and_no_automatic_retry():
    ledger = FakeLedger()
    closed = threading.Event()
    calls = []

    def create(**kw):
        calls.append(kw)
        closed.wait(2)
        raise RuntimeError("transport closed")

    client = Obj(chat=Obj(completions=Obj(create=create)), close=closed.set)
    provider = SemanticProvider(
        spec=ProviderSpec("openai", "gpt-4o-mini", None, 0.15, 0.6, True),
        api_key="test-key",
        ledger=ledger,
        deadline=time.monotonic() + 0.05,
        cancelled=lambda: False,
        owner_scope="test",
        client_factory=lambda **kw: client,
    )
    started = time.monotonic()
    with pytest.raises(RuntimeError):
        provider.generate("headers", system="JSON", payload={}, schema=PATCH_SCHEMA)
    assert closed.is_set() and time.monotonic() - started < 1 and len(calls) == 1
    with pytest.raises((BudgetExceeded, RuntimeError)):
        provider.generate("headers", system="JSON", payload={}, schema=PATCH_SCHEMA)
    assert len(calls) == 1


def test_byok_never_inherits_platform_endpoint_or_fallback_price(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "platform-key")
    monkeypatch.setattr(settings, "OPENAI_MODEL", "custom-model")
    assert resolve_provider("byok-key", "gpt-4o-mini").base_url is None
    with pytest.raises(BudgetExceeded):
        resolve_provider("platform-key", "gpt-4o-mini")


STARTER = r"""\documentclass[11pt,a4paper]{article}
\usepackage[margin=0.72in]{geometry}
\usepackage{enumitem}
\setlist{nosep}
\begin{document}
\begin{center}
{\LARGE\textbf{Alex Morgan}} \\
\vspace{1mm}
Senior Software Engineer \\
Email: alex@example.com | linkedin.com/in/alexmorgan
\end{center}
\section*{Summary}
Engineer building reliable systems,
with source-grounded experience.
\section*{Experience}
\textbf{Staff Engineer, Northbeam Labs} \hfill 2022 - Present
\begin{itemize}
\item Built internal systems
\end{itemize}
\section*{Skills}
Python, SQL
\end{document}
"""


@pytest.mark.asyncio
async def test_shipped_starter_header_edits_preserve_layout_and_escape_literals():
    projected = await project_guest(GuestDocument(latex_content=STARTER))
    nodes = projected["document"]["nodes"]
    name = next(node for node in nodes if node["text"] == "Alex Morgan")
    assert any(node["text"] == "Senior Software Engineer" for node in nodes)
    assert any(node["section"] == "summary" for node in nodes)
    result = await patch_guest(
        GuestPatch(
            latex_content=STARTER,
            expected_source_sha256=digest(STARTER),
            patches=[
                {"node_id": name["node_id"], "expected_node_revision": name["node_revision"], "text": "Alex & Morgan"}
            ],
        )
    )
    assert result["latex_content"] == STARTER.replace("Alex Morgan", r"Alex \& Morgan")
    assert any(node["text"] == "Alex & Morgan" for node in result["document"]["nodes"])
    assert all(not node["ai_editable"] for node in nodes)


@pytest.mark.parametrize(
    "source",
    [
        STARTER.replace("margin=0.72in", "margin=1in"),
        STARTER.replace(r"\begin{document}", r"\newcommand{\textbf}[1]{hidden}\begin{document}"),
        STARTER.replace(r"\section*{Skills}", r"\RenewDocumentCommand{\textbf}{m}{hidden}\section*{Skills}"),
        STARTER.replace(r"\end{document}", r"\catcode`\X=0\end{document}"),
    ],
)
def test_starter_field_assumptions_do_not_extend_to_custom_tex(source):
    assert project_starter_fields(source) == []
