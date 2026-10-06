"""Task signals must not retain credentials or invent unfenced outcomes."""

import io
import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from celery import Celery
from celery.app.trace import ExceptionInfo, build_tracer
from celery.worker.request import Request

from app.core import celery_app as signals
from app.workers import event_publisher, job_lifecycle


def _trace_with_backend(task, task_id, args, kwargs, *, app):
    """Execute Celery's production tracer while retaining backend results."""
    return build_tracer(task.name, task, app=app, eager=True, propagate=False)(
        task_id,
        args,
        kwargs,
        {"id": task_id, "argsrepr": "SECRET_ARGS", "kwargsrepr": "SECRET_KWARGS"},
    )


def test_celery_privacy_guards_are_idempotent():
    from celery import signals as celery_signals
    from celery.app import trace as celery_trace
    from celery.worker.request import Request

    signals._install_celery_trace_privacy_filter()
    signals._install_celery_event_privacy_guards()
    assert sum(isinstance(item, signals._CeleryTracePrivacyFilter) for item in celery_trace.logger.filters) == 1
    assert getattr(Request.__init__, "_latexy_privacy_guard", False) is True
    assert getattr(Request.send_event, "_latexy_privacy_guard", False) is True
    assert getattr(celery_signals.task_sent.send, "_latexy_privacy_guard", False) is True


def test_real_celery_success_trace_redacts_result_and_arguments(caplog):
    app = Celery("celery_trace_privacy_success", broker="memory://", backend="cache+memory://")
    app.conf.task_store_eager_result = True
    secret = "SECRET_EXTRACTED_TEXT"

    @app.task(name="celery_trace_privacy_success.echo")
    def echo(payload, content=None):
        return {"extracted_text": payload, "content": content}

    with caplog.at_level(logging.INFO, logger="celery.app.trace"):
        traced = _trace_with_backend(
            echo,
            "celery-trace-success",
            (secret,),
            {"content": secret},
            app=app,
        )

    expected = {"extracted_text": secret, "content": secret}
    assert traced.retval == expected
    assert app.backend.get_result("celery-trace-success") == expected
    assert secret not in caplog.text
    assert "SECRET_ARGS" not in caplog.text
    assert "SECRET_KWARGS" not in caplog.text


def test_real_celery_failure_trace_redacts_exception_and_arguments(caplog):
    app = Celery("celery_trace_privacy_failure", broker="memory://", backend="cache+memory://")
    app.conf.task_store_eager_result = True
    secret = "SECRET_PROVIDER_DIAGNOSTIC"

    @app.task(name="celery_trace_privacy_failure.fail")
    def fail(payload, content=None):
        raise ValueError(f"{payload} {content}")

    with caplog.at_level(logging.INFO):
        traced = _trace_with_backend(
            fail,
            "celery-trace-failure",
            (secret,),
            {"content": secret},
            app=app,
        )

    # Celery still returns/persists the real exception for retry/result
    # semantics; only the trace records are redacted.
    assert secret in str(traced.retval)
    assert secret in str(app.backend.get_result("celery-trace-failure"))
    assert secret not in caplog.text
    assert "SECRET_ARGS" not in caplog.text
    assert "SECRET_KWARGS" not in caplog.text


def test_real_celery_protocol_metadata_redacts_events_without_redacting_body():
    app = Celery("celery_protocol_privacy", broker="memory://", backend="cache+memory://")
    secret = "SECRET_PROTOCOL_PAYLOAD"
    message = app.amqp.as_task_v2(
        "celery-protocol-task",
        "celery_protocol_privacy.echo",
        args=(secret,),
        kwargs={"content": secret},
        create_sent_event=True,
    )

    assert message.headers["argsrepr"] == "<redacted>"
    assert message.headers["kwargsrepr"] == "<redacted>"
    assert message.sent_event["args"] == "<redacted>"
    assert message.sent_event["kwargs"] == "<redacted>"
    assert message.body[0] == (secret,)
    assert message.body[1] == {"content": secret}


def test_deprecated_task_sent_signal_redacts_payload_metadata():
    from celery import signals as celery_signals

    seen = {}
    secret = "SECRET_TASK_SENT"

    def receiver(sender=None, **kwargs):
        seen.update(kwargs)

    celery_signals.task_sent.connect(receiver, weak=False)
    try:
        celery_signals.task_sent.send(sender="privacy.task", args=(secret,), kwargs={"content": secret})
    finally:
        celery_signals.task_sent.disconnect(receiver)

    assert seen["args"] == "<redacted>"
    assert seen["kwargs"] == "<redacted>"


def test_real_worker_request_failure_log_redacts_exception(caplog):
    app = Celery("celery_request_privacy", broker="memory://", backend="cache+memory://")
    secret = "SECRET_WORKER_EXCEPTION"

    @app.task(name="celery_request_privacy.fail")
    def fail(payload):
        return payload

    message = SimpleNamespace(
        headers={
            "id": "celery-request-failure",
            "task": fail.name,
            "argsrepr": secret,
            "kwargsrepr": secret,
        },
        body=((secret,), {}, {}),
        content_type=None,
        content_encoding=None,
        payload=((secret,), {}, {}),
        delivery_info={},
        properties={},
    )
    request = Request(message, app=app, task=fail, decoded=True)
    with caplog.at_level(logging.ERROR):
        try:
            raise ValueError(secret)
        except ValueError:
            request.on_failure(ExceptionInfo(), send_failed_event=False)

    assert secret in str(app.backend.get_result("celery-request-failure"))
    assert secret not in caplog.text


def test_trace_privacy_filter_clears_stack_info_for_real_formatter():
    """Formatter output must not reintroduce source text via stack_info."""
    logger = logging.getLogger("celery.worker.request")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s|%(stack_info)s|%(exc_text)s"))
    previous_level = logger.level
    logger.setLevel(logging.ERROR)
    logger.addHandler(handler)
    secret = "SECRET_CALLER_STACK"
    try:
        # This exercises the installed Celery logger filter and a production
        # logging.Formatter, rather than asserting on filter configuration.
        logger.error("caller data %s", secret, stack_info=True)
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)

    rendered = stream.getvalue()
    assert secret not in rendered
    assert "celery_task_trace_internal|None|None" in rendered


@pytest.mark.parametrize("payload", [
    {"api_key": "private-token", "content": "private-resume", "private-key": "private-value"},
    ("private-token", "private-resume"),
    ["private-token"],
    "private-token",
])
def test_payload_diagnostics_never_retain_values(payload):
    summary = signals._safe_payload_repr(payload)
    assert "private" not in summary
    assert len(summary) <= 256


def test_payload_diagnostics_never_call_custom_repr():
    class UnsafeRepr:
        def __repr__(self):
            raise AssertionError("Caller values must not be inspected")

    assert signals._safe_payload_repr(UnsafeRepr()) == "<redacted payload>"
    assert "mapping" in signals._safe_payload_repr({"api_key": UnsafeRepr()})


@pytest.mark.parametrize("accepted", [True, False])
def test_signal_terminal_result_precedes_notification(monkeypatch, accepted):
    calls = []

    def result(*args, **kwargs):
        calls.append(("result", args, kwargs))
        return accepted

    def event(*args, **kwargs):
        calls.append(("event", args, kwargs))

    monkeypatch.setattr(event_publisher, "publish_job_result", result)
    monkeypatch.setattr(event_publisher, "publish_event", event)
    assert signals._recover_failed_job("job", "task", "compile", "Safe error") is accepted
    assert [call[0] for call in calls] == (["result", "event"] if accepted else ["result"])
    assert calls[0][2].get("force") is not True


def test_retry_exhaustion_keeps_secrets_out_of_dlq_logs_and_client(monkeypatch):
    redis = Mock()
    redis.exists.return_value = False
    monkeypatch.setattr(event_publisher, "get_worker_redis", lambda: redis)
    recovery = Mock(return_value=True)
    monkeypatch.setattr(signals, "_recover_failed_job", recovery)
    logger = Mock()
    monkeypatch.setattr(signals, "logger", logger)
    task = SimpleNamespace(
        name="app.workers.test", max_retries=2,
        request=SimpleNamespace(retries=2, delivery_info={}),
    )
    signals.on_task_failure(
        task_id="task", sender=task,
        exception=ValueError("private-error private-token private-resume"),
        args=("private-resume",),
        kwargs={"job_id": "job", "api_key": "private-token", "content": "private-resume"},
    )
    entry = json.loads(redis.lpush.call_args.args[1])
    assert entry["exception_type"] == "ValueError"
    assert entry["job_id"] == "job"
    assert "private" not in json.dumps(entry)
    assert "private" not in str(recovery.call_args)
    assert "private" not in str(logger.mock_calls)
    redis.ltrim.assert_called_once_with("latexy:dlq:app.workers.test", 0, 499)
    redis.expire.assert_called_once_with("latexy:dlq:app.workers.test", 7 * 86400)


@pytest.mark.parametrize("record_raises,stop_raises", [(False, False), (True, False), (False, True)])
def test_postrun_releases_only_matching_owner_even_on_signal_failure(monkeypatch, record_raises, stop_raises):
    record = Mock(side_effect=RuntimeError("metrics failed") if record_raises else None)
    stop = Mock(side_effect=RuntimeError("stop failed") if stop_raises else None)
    clear = Mock()
    monkeypatch.setattr(signals, "_record_task_postrun", record)
    monkeypatch.setattr(job_lifecycle, "stop_lease_heartbeat", stop)
    monkeypatch.setattr(job_lifecycle, "clear_current_owner", clear)
    if record_raises or stop_raises:
        with pytest.raises(RuntimeError):
            signals.on_task_postrun(task_id="task", kwargs={"job_id": "job"})
    else:
        signals.on_task_postrun(task_id="task", kwargs={"job_id": "job"})
    stop.assert_called_once_with("job")
    clear.assert_called_once_with("job")
