"""Forking optimization routes reject unavailable renderers before side effects."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api import job_routes, resume_routes
from app.database.models import Resume
from app.services.render_engine import backend
from app.services.render_engine.modal_sandbox import ModalEngineUnavailable
from app.workers import orchestrator

USER_ID = "00000000-0000-0000-0000-000000000001"
RESUME_ID = "00000000-0000-0000-0000-000000000002"
SOURCE = r"\documentclass{article}\begin{document}Example resume\end{document}"


@pytest.fixture
def route_dependencies(monkeypatch):
    db = AsyncMock()
    db.add = MagicMock()
    plan = MagicMock()
    plan.scalar_one_or_none.return_value = "pro"
    db.execute.return_value = plan
    parent = SimpleNamespace(
        id=RESUME_ID, title="Original", latex_content=SOURCE, tags=["original"],
        resume_settings={"compiler": "lualatex", "main_file": "main.tex", "draft_mode": True},
        document_type="academic_cv",
    )
    verify = AsyncMock(return_value=parent)
    monkeypatch.setattr(resume_routes, "_verify_resume_ownership", verify)
    monkeypatch.setattr(job_routes, "_resolve_user_plan", AsyncMock(return_value="pro"))
    report = SimpleNamespace(is_academic_cv=True, confidence=1.0, to_dict=lambda: {
        "is_academic_cv": True, "detected_sections": ["research"], "estimated_pages": 2,
        "confidence": 1.0, "reasons": ["Research experience"],
    })
    monkeypatch.setattr(resume_routes.academic_cv_service, "detect", MagicMock(return_value=report))
    monkeypatch.setattr(resume_routes.academic_cv_service, "build_conversion_instructions",
                        MagicMock(return_value="Convert this academic CV for industry."))
    ticket = MagicMock()
    ticket.refund_payload.return_value = {"dimension": "optimizations", "user_id": USER_ID}
    quota = AsyncMock(return_value=ticket)
    monkeypatch.setattr(resume_routes.entitlement_service, "enforce_quota", quota)
    queued, started, accepted = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(job_routes, "_write_initial_redis_state", queued)
    monkeypatch.setattr(job_routes, "_mark_dispatch_started", started)
    monkeypatch.setattr(job_routes, "_mark_dispatch_accepted", accepted)
    submit = MagicMock()
    monkeypatch.setattr(orchestrator, "submit_optimize_and_compile", submit)
    return SimpleNamespace(db=db, parent=parent, verify=verify, quota=quota, ticket=ticket,
                           queued=queued, started=started, accepted=accepted, submit=submit)


async def invoke_route(route, db):
    if route == "quick_tailor":
        return await resume_routes.quick_tailor_resume(
            RESUME_ID, resume_routes.QuickTailorRequest(job_description="A senior engineering role"),
            db=db, user_id=USER_ID,
        )
    return await resume_routes.convert_academic_cv(
        RESUME_ID, resume_routes.AcademicCVConvertRequest(), db=db, user_id=USER_ID,
    )


@pytest.mark.parametrize("route", ["quick_tailor", "academic_convert"])
async def test_unavailable_renderer_rejects_before_fork_quota_or_dispatch(route, route_dependencies, monkeypatch):
    deps = route_dependencies
    resolve = MagicMock(side_effect=ModalEngineUnavailable("Renderer unavailable"))
    monkeypatch.setattr(backend, "resolve_backend", resolve)

    with pytest.raises(HTTPException) as error:
        await invoke_route(route, deps.db)

    assert error.value.status_code == 503
    resolve.assert_called_once_with("lualatex")
    deps.verify.assert_awaited_once_with(deps.db, RESUME_ID, USER_ID)
    deps.db.add.assert_not_called()
    deps.db.execute.assert_not_awaited()
    deps.db.flush.assert_not_awaited()
    deps.db.commit.assert_not_awaited()
    deps.quota.assert_not_awaited()
    deps.queued.assert_not_awaited()
    deps.started.assert_not_awaited()
    deps.accepted.assert_not_awaited()
    deps.submit.assert_not_called()


@pytest.mark.parametrize("route", ["quick_tailor", "academic_convert"])
@pytest.mark.parametrize("saved_compiler,expected_compiler", [
    ("lualatex", "lualatex"), ("xelatex", "xelatex"), (None, "pdflatex"), ("unknown", "pdflatex"),
])
async def test_available_renderer_preserves_fork_and_dispatch(
    route, saved_compiler, expected_compiler, route_dependencies, monkeypatch,
):
    deps = route_dependencies
    deps.parent.resume_settings["compiler"] = saved_compiler
    monkeypatch.setattr(resume_routes.settings, "DEFAULT_LATEX_COMPILER", "pdflatex")

    def resolve(compiler):
        assert compiler == expected_compiler
        deps.db.add.assert_not_called()
        deps.quota.assert_not_awaited()
        deps.submit.assert_not_called()
        return MagicMock()

    resolution = MagicMock(side_effect=resolve)
    monkeypatch.setattr(backend, "resolve_backend", resolution)
    response = await invoke_route(route, deps.db)

    resolution.assert_called_once_with(expected_compiler)
    fork = next(call.args[0] for call in deps.db.add.call_args_list if isinstance(call.args[0], Resume))
    assert fork.parent_resume_id == RESUME_ID
    assert fork.latex_content == SOURCE
    assert deps.parent.latex_content == SOURCE
    assert fork.resume_settings == deps.parent.resume_settings
    assert (response.fork_id if route == "quick_tailor" else response.variant_resume_id) == fork.id
    deps.db.commit.assert_awaited_once()
    deps.quota.assert_awaited_once_with("optimizations", user_id=USER_ID, plan="pro", job_id=response.job_id)
    deps.submit.assert_called_once()
    kwargs = deps.submit.call_args.kwargs
    assert kwargs["compiler"] == expected_compiler
    assert kwargs["compile_settings"] == {"main_file": "main.tex", "draft_mode": True}
    assert kwargs["latex_content"] == SOURCE
    assert kwargs["resume_id"] == fork.id
    assert kwargs["optimization_level"] == "aggressive"
    assert kwargs["quota_refund"] == deps.ticket.refund_payload.return_value
    deps.started.assert_awaited_once_with(response.job_id)
    deps.accepted.assert_awaited_once_with(response.job_id)
