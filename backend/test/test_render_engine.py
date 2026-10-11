"""Rendering cache isolation and bounded cancellation behavior."""
import base64
import json
from unittest.mock import MagicMock, patch

from app.services.render_engine.cancellation import CancellationPoll
from app.workers import latex_worker, orchestrator

SOURCE = r"\documentclass{article}\begin{document}Hello\end{document}"


def test_cancellation_poll_bounds_reads_and_retains_cancellation():
    check = MagicMock(side_effect=[False, True])
    with patch("app.services.render_engine.cancellation.time.monotonic", side_effect=[1.0, 1.01, 1.09, 1.11, 1.12]):
        poll = CancellationPoll(check)
        assert [poll() for _ in range(5)] == [False, False, False, True, True]
    assert check.call_count == 2


def test_combined_cache_uses_prepared_source_and_skips_compiler(monkeypatch):
    context = {}
    encoded = base64.b64encode(b"%PDF-cached")
    redis = MagicMock()
    redis.get.return_value = encoded
    monkeypatch.setattr(orchestrator, "get_worker_redis", lambda: redis)
    restore = MagicMock(return_value={"page_count": 2, "success": True})
    monkeypatch.setattr(orchestrator, "restore_compile_cache", restore)
    spawn = MagicMock()
    monkeypatch.setattr(orchestrator.subprocess, "Popen", spawn)
    settings = {"extra_packages": ["xcolor"], "draft_mode": True}
    result = orchestrator._run_latex_stage(
        "new", SOURCE, extra_packages=["xcolor"], draft_mode=True,
        compile_settings=settings, owner_scope="user:one", cache_context=context,
    )
    prepared = latex_worker._inject_draft_graphics(latex_worker._inject_packages(SOURCE, ["xcolor"]))
    expected = latex_worker.compile_cache_key(prepared, "pdflatex", {
        **settings, "main_file": "resume.tex", "latexmk_flags": [], "halt_on_error": True,
    }, "user:one")
    assert context["key"] == expected
    restore.assert_called_once_with(expected, "new")
    assert result == (True, 0.0, "", 2, b"%PDF-cached")
    spawn.assert_not_called()


def test_render_cache_cannot_inherit_optimizer_or_ats_decisions():
    redis = MagicMock()
    redis.get.return_value = "old"
    redis.mget.return_value = [base64.b64encode(b"%PDF"), None, None, json.dumps({
        "success": True, "page_count": 1, "compiler": "pdflatex",
        "ats_score": 99, "optimized_latex": "different request", "changes_made": ["private"],
        "auto_fit": True, "fitted_latex": "different request",
    })]
    with patch.object(latex_worker, "get_worker_redis", return_value=redis), patch.object(latex_worker, "write_owned_artifacts", return_value=True):
        result = latex_worker.restore_compile_cache("tenant-key", "new")
    assert result["page_count"] == 1
    assert result["job_id"] == "new"
    assert not ({"ats_score", "optimized_latex", "changes_made", "auto_fit", "fitted_latex"} & result.keys())
