"""HTTP-boundary terminal/dispatch guarantees for document conversion.

The upload route must keep the durable finalization row when a broker/Modal
response is ambiguous, because only the worker or cleanup may decide the
terminal outcome. A failure proven to occur before dispatch must instead
refund and remove the reservation. These tests mock the broker and database;
they do not need Redis or PostgreSQL.
"""

import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from app.api import format_routes
from app.services.format_detection import ResumeFormat
from app.workers.converter_worker import submit_document_conversion
from app.workers.job_lifecycle import lifecycle_key


def _upload():
    return UploadFile(
        filename="resume.txt",
        file=io.BytesIO(b"Synthetic resume"),
        headers={"content-type": "text/plain"},
    )


def _db():
    db = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.rollback = AsyncMock()
    plan_result = MagicMock()
    plan_result.scalar_one_or_none.return_value = "free"
    db.execute = AsyncMock(return_value=plan_result)
    return db


def _patches(db, row, *, submit=None, write_state=None):
    parser = SimpleNamespace(
        parse=AsyncMock(return_value=SimpleNamespace(to_dict=lambda: {"raw_text": "Synthetic resume"}))
    )
    ticket = MagicMock()
    ticket.refund_payload.return_value = {
        "dimension": "ai_assists",
        "user_id": "synthetic-owner",
        "period": "202611",
        "cost": 1,
    }
    redis = MagicMock()
    redis.delete = AsyncMock()

    context = {
        "read_upload_capped": AsyncMock(return_value=b"Synthetic resume"),
        "format_detection_service.detect_format": MagicMock(return_value=ResumeFormat.TEXT),
        "format_detection_service.validate_file_size": MagicMock(return_value=(True, "")),
        "parser_factory.get_parser": MagicMock(return_value=parser),
        "api_key_service.get_user_provider": AsyncMock(return_value=None),
        "entitlement_service.enforce_quota": AsyncMock(return_value=ticket),
        "entitlement_service.refund_quota": AsyncMock(),
        "submit_async": submit or AsyncMock(return_value=None),
        "get_redis_client": AsyncMock(return_value=redis),
        "_new_finalization_row": MagicMock(return_value=row),
        "_write_initial_redis_state": write_state or AsyncMock(),
        "_mark_dispatch_started": AsyncMock(),
        "_mark_dispatch_accepted": AsyncMock(),
        "_delete_initial_redis_state": AsyncMock(),
    }
    return context, ticket, redis


def _enter(context):
    stack = []
    for name, value in context.items():
        target = f"app.api.job_routes.{name}" if name.startswith("_") else f"app.api.format_routes.{name}"
        patcher = patch(target, value)
        patcher.start()
        stack.append(patcher)
    return stack


def test_modal_dispatch_failure_propagates_to_the_route(monkeypatch):
    monkeypatch.setenv("DEPLOY_TARGET", "modal")
    quota_refund = {"dimension": "ai_assists", "user_id": "synthetic-owner", "cost": 1}
    with patch(
        "app.core.modal_dispatch.spawn",
        side_effect=RuntimeError("synthetic modal unavailable"),
    ) as spawn:
        with pytest.raises(RuntimeError, match="synthetic modal unavailable"):
            submit_document_conversion(
                extracted_data={"raw_text": "Synthetic resume"},
                source_format="text",
                job_id="synthetic-conversion-job",
                user_id="synthetic-owner",
                quota_refund=quota_refund,
            )

    spawn.assert_called_once()
    function_name, payload = spawn.call_args.args
    assert function_name == "run_document_conversion_task"
    assert payload["job_id"] == "synthetic-conversion-job"
    assert payload["quota_refund"] == quota_refund


@pytest.mark.asyncio
async def test_ambiguous_dispatch_preserves_durable_row_instead_of_failing_job():
    db, row = _db(), MagicMock(name="finalization-row")
    context, ticket, _redis = _patches(
        db,
        row,
        submit=AsyncMock(side_effect=RuntimeError("synthetic lost broker response")),
    )
    stack = _enter(context)
    try:
        response = await format_routes.upload_for_conversion(
            file=_upload(),
            source_hint=None,
            source_platform=None,
            user_id="synthetic-owner",
            db=db,
        )
    finally:
        for patcher in reversed(stack):
            patcher.stop()

    assert response.success is True
    uuid.UUID(response.job_id)
    db.add.assert_called_once_with(row)
    db.commit.assert_awaited()
    context["_mark_dispatch_started"].assert_awaited_once_with(response.job_id)
    context["_mark_dispatch_accepted"].assert_not_awaited()
    context["_delete_initial_redis_state"].assert_not_awaited()
    context["entitlement_service.refund_quota"].assert_not_awaited()
    db.delete.assert_not_awaited()

    submit_kwargs = context["submit_async"].await_args.kwargs
    assert submit_kwargs["job_id"] == response.job_id
    assert submit_kwargs["quota_refund"] == ticket.refund_payload.return_value


@pytest.mark.asyncio
async def test_pre_dispatch_failure_refunds_and_removes_reservation():
    db, row = _db(), MagicMock(name="finalization-row")
    write_state = AsyncMock(side_effect=RuntimeError("synthetic queue state failure"))
    context, ticket, redis = _patches(db, row, write_state=write_state)
    stack = _enter(context)
    try:
        with pytest.raises(HTTPException) as exc:
            await format_routes.upload_for_conversion(
                file=_upload(),
                source_hint=None,
                source_platform=None,
                user_id="synthetic-owner",
                db=db,
            )
    finally:
        for patcher in reversed(stack):
            patcher.stop()

    assert exc.value.status_code == 500
    context["entitlement_service.refund_quota"].assert_awaited_once_with(ticket)
    db.delete.assert_awaited_once_with(row)
    context["_delete_initial_redis_state"].assert_awaited_once()
    context["_mark_dispatch_started"].assert_not_awaited()
    context["_mark_dispatch_accepted"].assert_not_awaited()
    context["submit_async"].assert_not_awaited()
    job_id = context["_new_finalization_row"].call_args.args[0]
    redis.delete.assert_awaited_once_with(lifecycle_key(job_id))
