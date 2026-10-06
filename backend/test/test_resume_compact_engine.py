"""Adversarial contract checks for the opt-in literal patch engine."""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

from app.services.resume_engine.document import project_literal_bullets
from app.services.resume_engine.optimizer import CompactBudget, optimize_snapshot
from app.services.resume_engine.patches import CompactOptimizationCancelled, CompactOptimizationError, apply_patches

SOURCE = "\\documentclass{article}\r\n\\begin{document}\r\n\\section*{Experience}\r\n\\begin{itemize}\r\n  \\item Built Python tools for 12 customers.\r\n\\end{itemize}\r\n\\end{document}\r\n"


def payload(snapshot, text="Developed Python tools for 12 customers."):
    node = snapshot.nodes[0]
    return {"base_revision": snapshot.revision, "changes": [{
        "node_id": node.node_id, "expected_node_revision": node.revision,
        "operation": "replace_text", "text": text,
        "evidence_ids": [node.node_id], "reason_code": "clarity",
    }]}


def test_projection_and_patch_preserve_crlf_and_every_opaque_byte():
    snapshot = project_literal_bullets(SOURCE)
    assert len(snapshot.nodes) == 1
    result, changes = apply_patches(snapshot, json.dumps(payload(snapshot)))
    assert result == SOURCE.replace("Built Python tools", "Developed Python tools")
    assert changes[0]["evidence_ids"] == [snapshot.nodes[0].node_id]
    assert project_literal_bullets(SOURCE).nodes == snapshot.nodes


@pytest.mark.parametrize("prefix", [
    r"\renewcommand{\item}{hidden}", r"\input{other.tex}", r"\catcode`\%=12",
    r"\def\items{hidden}", r"\begin{verbatim}",
    r"\RenewDocumentCommand{\item}{m}{replacement}",
    r"\NewExpandableDocumentCommand{\item}{m}{replacement}",
    r"\ProvideDocumentEnvironment{itemize}{}{}{}",
])
def test_unsupported_source_never_exposes_nodes(prefix):
    assert not project_literal_bullets(prefix + "\n" + SOURCE).nodes


@pytest.mark.parametrize("body", [
    r"Built \textbf{Python} tools.", "Built tools.\nContinuation has facts.",
    r"Built 25\% more tools.", r"Built $math$ tools.", r"Built tools. % annotation",
])
def test_unknown_and_multiline_bullets_remain_opaque(body):
    source = SOURCE.replace("Built Python tools for 12 customers.", body)
    assert not project_literal_bullets(source).nodes


def test_selected_sections_deny_other_targets():
    assert not project_literal_bullets(SOURCE, ["Education"]).nodes
    assert project_literal_bullets(SOURCE, ["experience"]).nodes


def test_large_sparse_projection_has_linear_traversal():
    source = SOURCE.replace("\\begin{itemize}\r\n", "\\begin{itemize}\r\n" + "\n" * 50_000)
    started = time.perf_counter()
    snapshot = project_literal_bullets(source)
    assert len(snapshot.nodes) == 1
    # Loose guard catches the former multi-second O(n²) suffix scan while
    # allowing slower shared Windows CI hosts.
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize("field,value", [
    ("text", "Developed Python tools for 20 customers."),
    ("text", "Developed Kubernetes tools for 12 customers."),
    ("text", "Developed Python tools for 12 customers and managed teams."),
    ("text", r"Developed \input{secret} tools for 12 customers."),
    ("text", "Developed Python tools for 12 customers.\nInjected line"),
    ("text", "Developed Python\u200b tools for 12 customers."),
    ("text", "Developed Python\u202e tools for 12 customers."),
    ("text", "Developed Python\u2028 tools for 12 customers."),
    ("text", "Developed Python\u2029 tools for 12 customers."),
    ("node_id", "other-owner-node"), ("expected_node_revision", "0" * 64),
    ("evidence_ids", ["another-bullet"]), ("operation", "delete"),
])
def test_invalid_factual_syntax_scope_and_revision_edits_fail_closed(field, value):
    snapshot = project_literal_bullets(SOURCE)
    response = payload(snapshot)
    response["changes"][0][field] = value
    with pytest.raises(CompactOptimizationError):
        apply_patches(snapshot, json.dumps(response))


def test_missing_protected_source_words_and_negation_rejected():
    snapshot = project_literal_bullets(SOURCE.replace("Built Python", "Did not build Python"))
    with pytest.raises(CompactOptimizationError):
        apply_patches(snapshot, json.dumps(payload(snapshot, "Developed Python tools for 12 customers.")))


@pytest.mark.parametrize("original,replacement", [
    ("Improved revenue from 10 to 20.", "Enhanced revenue from 20 to 10."),
    ("Built Python not Java tools.", "Developed Java not Python tools."),
    ("Built Python tools.", "Developed Python tools efficiently."),
    ("Built Python tools.", "Successfully developed Python tools."),
    ("Built Python, not Java, tools.", "Developed Python not, Java, tools."),
    ("Built Python and Java tools.", "Developed Python or Java tools."),
])
def test_relations_negation_order_connectives_and_unsupported_intensifiers_are_protected(original, replacement):
    snapshot = project_literal_bullets(SOURCE.replace("Built Python tools for 12 customers.", original))
    with pytest.raises(CompactOptimizationError):
        apply_patches(snapshot, json.dumps(payload(snapshot, replacement)))


def test_duplicate_targets_and_wrong_base_revision_rejected():
    snapshot = project_literal_bullets(SOURCE)
    response = payload(snapshot)
    response["changes"] *= 2
    with pytest.raises(CompactOptimizationError):
        apply_patches(snapshot, json.dumps(response))
    response = payload(snapshot)
    response["base_revision"] = "0" * 64
    with pytest.raises(CompactOptimizationError):
        apply_patches(snapshot, json.dumps(response))


def test_empty_changes_is_valid_and_does_not_reformat():
    snapshot = project_literal_bullets(SOURCE)
    assert apply_patches(snapshot, json.dumps({"base_revision": snapshot.revision, "changes": []})) == (SOURCE, [])


@pytest.mark.parametrize("invisible", ["\u200b", "\u202e", "\u2028", "\u2029"])
def test_invisible_controls_and_line_separators_are_not_projected(invisible):
    assert not project_literal_bullets(SOURCE.replace("Python", "Python" + invisible)).nodes


def fake_client(response, finish="stop", refusal=None):
    client = MagicMock()
    client.chat.completions.create.return_value = iter([
        NS(usage=None, choices=[NS(delta=NS(content=response, refusal=refusal), finish_reason=finish)]),
        NS(usage=NS(total_tokens=80), choices=[]),
    ])
    return client


def run(snapshot, client, **kwargs):
    factory = MagicMock(return_value=client)
    result = optimize_snapshot(snapshot, client_factory=factory, api_key="tenant-key", model="existing-model",
        base_url=None, count_tokens=lambda text: len(text.split()), cancelled=lambda: False, **kwargs)
    return result, factory


def test_single_paid_call_no_full_preamble_and_no_capability_assumptions():
    snapshot = project_literal_bullets(SOURCE)
    client = fake_client(json.dumps(payload(snapshot)))
    result, factory = run(snapshot, client)
    assert "Developed Python" in result.latex
    assert result.tokens == 80
    factory.assert_called_once()
    assert factory.call_args.kwargs["max_retries"] == 0
    assert 0 < factory.call_args.kwargs["timeout"] <= 15
    client.chat.completions.create.assert_called_once()
    sent = client.chat.completions.create.call_args.kwargs
    assert "\\documentclass" not in sent["messages"][1]["content"]
    assert "response_format" not in sent and "extra_body" not in sent
    client.close.assert_called_once()


@pytest.mark.parametrize("finish,refusal", [("length", None), ("content_filter", None), ("stop", "refused")])
def test_truncation_and_refusal_do_not_apply_or_repeat_paid_calls(finish, refusal):
    snapshot = project_literal_bullets(SOURCE)
    client = fake_client(json.dumps(payload(snapshot)), finish, refusal)
    with pytest.raises(CompactOptimizationError):
        run(snapshot, client)
    client.chat.completions.create.assert_called_once()
    client.close.assert_called_once()


def test_input_budget_and_cancellation_prevent_provider_dispatch():
    snapshot = project_literal_bullets(SOURCE)
    factory = MagicMock()
    with pytest.raises(CompactOptimizationError):
        optimize_snapshot(snapshot, client_factory=factory, api_key="key", model="model", base_url=None,
            count_tokens=lambda _: 9000, cancelled=lambda: False)
    factory.assert_not_called()
    with pytest.raises(CompactOptimizationCancelled):
        optimize_snapshot(snapshot, client_factory=factory, api_key="key", model="model", base_url=None,
            count_tokens=lambda _: 1, cancelled=lambda: True)
    factory.assert_not_called()


def test_network_failure_is_terminal_and_sdk_retries_are_disabled():
    snapshot = project_literal_bullets(SOURCE)
    client = MagicMock()
    client.chat.completions.create.side_effect = TimeoutError("network timed out")
    with pytest.raises(CompactOptimizationError):
        run(snapshot, client)
    client.chat.completions.create.assert_called_once()
    client.close.assert_called_once()


def test_stream_chunks_use_bounded_cancel_reads_and_mandatory_commit_checks(monkeypatch):
    import app.services.render_engine.cancellation as cancellation
    import app.services.resume_engine.optimizer as optimizer
    snapshot = project_literal_bullets(SOURCE)
    response = json.dumps(payload(snapshot))
    clock = [1.0]
    monkeypatch.setattr(optimizer.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cancellation.time, "monotonic", lambda: clock[0])
    checks = MagicMock(return_value=False)
    client = MagicMock()
    client.chat.completions.create.return_value = iter([
        NS(usage=None, choices=[NS(delta=NS(content=char, refusal=None), finish_reason=None)])
        for char in response
    ] + [NS(usage=None, choices=[NS(delta=NS(content=None, refusal=None), finish_reason="stop")])])
    optimize_snapshot(snapshot, client_factory=lambda **_: client, api_key="key", model="model", base_url=None,
        count_tokens=lambda text: len(text.split()), cancelled=checks)
    # Preflight, first chunk, completed response, and post-validation commit.
    assert checks.call_count == 4


def test_stream_deadline_stops_before_applying_a_complete_patch(monkeypatch):
    import app.services.resume_engine.optimizer as optimizer
    snapshot = project_literal_bullets(SOURCE)
    clock = [1.0]
    monkeypatch.setattr(optimizer.time, "monotonic", lambda: clock[0])
    client = MagicMock()
    def stream():
        clock[0] = 20.0
        yield NS(usage=None, choices=[NS(delta=NS(content=json.dumps(payload(snapshot)), refusal=None), finish_reason="stop")])
    client.chat.completions.create.return_value = stream()
    with pytest.raises(CompactOptimizationError, match="deadline"):
        optimize_snapshot(snapshot, client_factory=lambda **_: client, api_key="key", model="model", base_url=None,
            count_tokens=lambda text: len(text.split()), cancelled=lambda: False)
    client.chat.completions.create.assert_called_once()
    client.close.assert_called_once()


def test_deadline_watchdog_is_armed_before_blocked_request_headers():
    snapshot = project_literal_bullets(SOURCE)
    released = threading.Event()
    client = MagicMock()
    client.close.side_effect = released.set
    def create(**_):
        assert released.wait(1.0), "watchdog must close client during request headers"
        return iter([])
    client.chat.completions.create.side_effect = create
    with pytest.raises(CompactOptimizationError, match="deadline"):
        run(snapshot, client, budget=CompactBudget(deadline_seconds=.03))
    client.chat.completions.create.assert_called_once()


def test_deadline_watchdog_closes_a_silent_response_stream():
    snapshot = project_literal_bullets(SOURCE)
    released = threading.Event()
    class SilentStream:
        def __iter__(self):
            return self
        def __next__(self):
            assert released.wait(1.0), "watchdog must close silent response"
            raise StopIteration
        def close(self):
            released.set()
    client = MagicMock()
    client.chat.completions.create.return_value = SilentStream()
    with pytest.raises(CompactOptimizationError, match="deadline"):
        run(snapshot, client, budget=CompactBudget(deadline_seconds=.03))
    client.chat.completions.create.assert_called_once()


def test_combined_worker_uses_opt_in_validated_patch_and_retains_byok_isolation(monkeypatch):
    import app.workers.orchestrator as orchestrator
    snapshot = project_literal_bullets(SOURCE)
    client = fake_client(json.dumps(payload(snapshot)))
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(orchestrator.settings, "RESUME_COMPACT_PATCHES_ENABLED", True)
    monkeypatch.setattr(orchestrator.settings, "OPENAI_BASE_URL", "https://platform.invalid")
    monkeypatch.setattr(orchestrator.settings, "OPENAI_API_KEY", "platform-key")
    monkeypatch.setattr(orchestrator.openai, "OpenAI", factory)
    monkeypatch.setattr(orchestrator, "is_cancelled", lambda _: False)
    events = MagicMock()
    monkeypatch.setattr(orchestrator, "publish_event", events)
    result = orchestrator._run_llm_stage("job", SOURCE, None, "balanced", "tenant-key", model="gpt-4o-mini")
    assert result[0] == SOURCE.replace("Built Python", "Developed Python")
    assert "base_url" not in factory.call_args.kwargs
    assert [call.args[1] for call in events.call_args_list] == ["job.progress", "llm.complete"]
    assert events.call_args_list[-1].args[2]["source_revision"] == snapshot.revision


@pytest.mark.parametrize("invalid", [False, True])
def test_standalone_worker_fences_result_and_never_retries_a_paid_compact_call(monkeypatch, invalid):
    import app.workers.llm_worker as worker
    snapshot = project_literal_bullets(SOURCE)
    raw = json.dumps(payload(snapshot, "Developed unsupported technology." if invalid else "Developed Python tools for 12 customers."))
    client = fake_client(raw)
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(worker.settings, "RESUME_COMPACT_PATCHES_ENABLED", True)
    monkeypatch.setattr(worker.settings, "OPENAI_BASE_URL", "")
    monkeypatch.setattr(worker.openai, "OpenAI", factory)
    monkeypatch.setattr(worker, "admit_worker", lambda *_: True)
    monkeypatch.setattr(worker, "get_worker_redis", lambda: object())
    monkeypatch.setattr(worker, "is_cancelled", lambda _: False)
    events = MagicMock(return_value=True)
    results = MagicMock(return_value=True)
    refunds = MagicMock()
    monkeypatch.setattr(worker, "publish_event", events)
    monkeypatch.setattr(worker, "publish_job_result", results)
    monkeypatch.setattr(worker, "_refund_optimization_quota_once", refunds)
    monkeypatch.setattr(worker, "clear_quota_refund_receipt", MagicMock())
    result = worker.optimize_resume_task.run(SOURCE, job_id="compact-job", user_api_key="tenant-key", quota_refund={"marker": True})
    assert result["success"] is not invalid
    client.chat.completions.create.assert_called_once()
    results.assert_called_once()
    assert events.call_args_list[-1].args[1] == ("job.failed" if invalid else "job.completed")
    assert refunds.call_count == int(invalid)


def test_legacy_combined_tokens_flush_before_complete_and_preserve_content(monkeypatch):
    import app.workers.orchestrator as worker
    monkeypatch.setattr(worker.settings, "RESUME_COMPACT_PATCHES_ENABLED", False)
    monkeypatch.setattr(worker.settings, "OPENAI_BASE_URL", "")
    raw = "<<<LATEX>>>" + SOURCE + "<<<END_LATEX>>><<<CHANGES>>>[]<<<END_CHANGES>>>"
    client = fake_client(raw)
    monkeypatch.setattr(worker.openai, "OpenAI", MagicMock(return_value=client))
    monkeypatch.setattr(worker, "is_cancelled", lambda _: False)
    events = MagicMock()
    monkeypatch.setattr(worker, "publish_event", events)
    monkeypatch.setattr(worker.llm_service, "_create_optimization_prompt", lambda *_, **__: "legacy prompt")
    result = worker._run_llm_stage("job", SOURCE, None, "balanced", "tenant-key")
    assert result[0] == SOURCE.strip()
    types = [call.args[1] for call in events.call_args_list]
    assert "llm.token" in types and types[-1] == "llm.complete"
    assert "".join(call.args[2]["token"] for call in events.call_args_list if call.args[1] == "llm.token") == SOURCE
