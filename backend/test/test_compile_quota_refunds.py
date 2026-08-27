"""Regression coverage for failed/cancelled compilation quota refunds."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.api.public_api_routes import V1CompileRequest, compile_v1
from app.api.routes import compile_latex_endpoint
from app.services.entitlement_service import QuotaTicket
from app.workers import latex_worker

VALID_LATEX = r"\documentclass{article}\begin{document}Hello\end{document}"


def _ticket() -> QuotaTicket:
    return QuotaTicket(
        dimension="compilations",
        user_id="user-123",
        period="20260827",
        used=1,
        limit=3,
        allowed=True,
        window="day",
    )


class TestAtomicWorkerRefund:
    def test_refunds_once_with_job_scoped_marker(self):
        redis = MagicMock()
        redis.eval.side_effect = [1, 0]
        payload = _ticket().refund_payload()

        with patch("app.workers.latex_worker.get_worker_redis", return_value=redis):
            assert latex_worker._refund_compile_quota_once("job-1", payload) is True
            assert latex_worker._refund_compile_quota_once("job-1", payload) is False

        first = redis.eval.call_args_list[0].args
        assert first[2] == "latexy:quota:compilations:user-123:20260827"
        assert first[3] == "latexy:quota-refund:compilations:job-1"

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            {"dimension": "optimizations", "user_id": "u", "period": "202608", "cost": 1},
            {"dimension": "compilations", "user_id": "u", "period": "bad", "cost": 1},
            {"dimension": "compilations", "user_id": "u", "period": "202608", "cost": 0},
        ],
    )
    def test_rejects_unmetered_or_malformed_payloads(self, payload):
        with patch("app.workers.latex_worker.get_worker_redis") as get_redis:
            assert latex_worker._refund_compile_quota_once("job-1", payload) is False
        get_redis.assert_not_called()

    def test_terminal_validation_failure_refunds(self):
        payload = _ticket().refund_payload()
        with (
            patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=False),
            patch("app.workers.latex_worker.publish_event"),
            patch("app.workers.latex_worker.publish_job_result"),
            patch("app.workers.latex_worker.reconcile_compilation_record"),
            patch("app.workers.latex_worker._refund_compile_quota_once") as refund,
        ):
            result = latex_worker.compile_latex_task(
                "invalid", job_id="job-failed", quota_refund=payload
            )

        assert result["success"] is False
        refund.assert_called_once_with("job-failed", payload)

    def test_successful_compile_does_not_refund(self):
        proc = MagicMock(returncode=0)
        proc.stdout = iter(["Output written on resume.pdf (1 page, 1 byte).\n"])
        payload = _ticket().refund_payload()
        with (
            patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=True),
            patch("app.workers.latex_worker.subprocess.Popen", return_value=proc),
            patch("app.workers.latex_worker.subprocess.run", return_value=MagicMock(returncode=1)),
            patch("app.workers.latex_worker.docker_engine_available", return_value=False),
            patch("app.workers.latex_worker.assert_local_engine_allowed"),
            patch("app.workers.latex_worker.is_cancelled", return_value=False),
            patch("app.workers.latex_worker.find_recorder_read_escape", return_value=None),
            patch("app.workers.latex_worker.Path.mkdir"),
            patch("app.workers.latex_worker.Path.write_text"),
            patch("app.workers.latex_worker.Path.exists", return_value=True),
            patch("app.workers.latex_worker.Path.stat", return_value=MagicMock(st_size=1)),
            patch("app.workers.latex_worker.cache_compile_output", return_value=b"pdf"),
            patch("app.workers.latex_worker.publish_event"),
            patch("app.workers.latex_worker.publish_job_result"),
            patch("app.workers.latex_worker.reconcile_compilation_record"),
            patch("app.workers.latex_worker._refund_compile_quota_once") as refund,
        ):
            result = latex_worker.compile_latex_task(
                VALID_LATEX, job_id="job-success", quota_refund=payload
            )

        assert result["success"] is True
        refund.assert_not_called()

    def test_cancelled_compile_refunds(self):
        proc = MagicMock(returncode=1)
        proc.stdout = iter(["compiling\n"])
        payload = _ticket().refund_payload()
        with (
            patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=True),
            patch("app.workers.latex_worker.subprocess.Popen", return_value=proc),
            patch("app.workers.latex_worker.docker_engine_available", return_value=False),
            patch("app.workers.latex_worker.assert_local_engine_allowed"),
            patch("app.workers.latex_worker.is_cancelled", return_value=True),
            patch("app.workers.latex_worker.Path.mkdir"),
            patch("app.workers.latex_worker.Path.write_text"),
            patch("app.workers.latex_worker.publish_event"),
            patch("app.workers.latex_worker.publish_job_result"),
            patch("app.workers.latex_worker.cache_compile_log"),
            patch("app.workers.latex_worker.reconcile_compilation_record"),
            patch("app.workers.latex_worker._refund_compile_quota_once") as refund,
        ):
            result = latex_worker.compile_latex_task(
                VALID_LATEX, job_id="job-cancelled", quota_refund=payload
            )

        assert result["cancelled"] is True
        refund.assert_called_once_with("job-cancelled", payload)

    def test_retrying_compile_does_not_refund(self):
        payload = _ticket().refund_payload()
        with (
            patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=True),
            patch("app.workers.latex_worker.Path.mkdir", side_effect=OSError("temporary")),
            patch("app.workers.latex_worker.publish_event"),
            patch.object(latex_worker.compile_latex_task, "retry", side_effect=RuntimeError("retry scheduled")),
            patch("app.workers.latex_worker._refund_compile_quota_once") as refund,
            pytest.raises(RuntimeError, match="retry scheduled"),
        ):
            latex_worker.compile_latex_task(
                VALID_LATEX, job_id="job-retrying", quota_refund=payload
            )

        refund.assert_not_called()

    def test_dispatch_preserves_refund_payload(self):
        payload = _ticket().refund_payload()
        with patch.object(latex_worker.compile_latex_task, "apply_async") as dispatch:
            latex_worker.submit_latex_compilation(
                VALID_LATEX, job_id="job-queued", quota_refund=payload
            )
        assert dispatch.call_args.kwargs["kwargs"]["quota_refund"] == payload


@pytest.mark.asyncio
class TestMeteredCompileSurfaces:
    async def test_job_submit_attaches_ticket(
        self, client: AsyncClient, auth_headers: dict
    ):
        ticket = _ticket()
        with (
            patch("app.api.job_routes._consume_job_quota", AsyncMock(return_value=ticket)),
            patch("app.api.job_routes.submit_latex_compilation") as submit,
        ):
            response = await client.post(
                "/jobs/submit",
                json={"job_type": "latex_compilation", "latex_content": VALID_LATEX},
                headers=auth_headers,
            )
        assert response.status_code == 200
        assert submit.call_args.kwargs["quota_refund"] == ticket.refund_payload()

    async def test_watermarked_submit_attaches_ticket(
        self, client: AsyncClient, auth_headers: dict
    ):
        ticket = _ticket()
        with (
            patch("app.api.job_routes._consume_job_quota", AsyncMock(return_value=ticket)),
            patch("app.api.job_routes.submit_latex_compilation") as submit,
        ):
            response = await client.post(
                "/jobs/compile-watermarked",
                json={"latex_content": VALID_LATEX, "watermark": "DRAFT"},
                headers=auth_headers,
            )
        assert response.status_code == 200
        assert submit.call_args.kwargs["quota_refund"] == ticket.refund_payload()

    async def test_developer_compile_attaches_ticket(self):
        ticket = _ticket()
        api_key = SimpleNamespace(user_id="user-123", id="key-1")
        with (
            patch("app.api.public_api_routes._authorize", AsyncMock(return_value=("free", ticket))),
            patch("app.api.public_api_routes._write_initial_redis_state", AsyncMock()),
            patch("app.api.public_api_routes.submit_latex_compilation") as submit,
        ):
            response = await compile_v1(
                V1CompileRequest(latex_content=VALID_LATEX), api_key=api_key, db=MagicMock()
            )
        assert response.status == "queued"
        assert submit.call_args.kwargs["quota_refund"] == ticket.refund_payload()

    async def test_synchronous_compile_refunds_failed_result(self):
        ticket = _ticket()
        failed = SimpleNamespace(success=False, job_id="job-sync")
        with (
            patch("app.api.routes._resolve_user_plan", AsyncMock(return_value="free")),
            patch("app.api.routes.entitlement_service.enforce_quota", AsyncMock(return_value=ticket)),
            patch("app.api.routes.entitlement_service.refund_quota", AsyncMock()) as refund,
            patch("app.api.routes.latex_service.validate_latex_content", return_value=True),
            patch("app.api.routes.latex_service.compile_latex", AsyncMock(return_value=failed)),
        ):
            result = await compile_latex_endpoint(
                latex_content=VALID_LATEX,
                file=None,
                user_id="user-123",
                db=MagicMock(),
            )
        assert result is failed
        refund.assert_awaited_once_with(ticket)
