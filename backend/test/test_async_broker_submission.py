"""Broker admission stays responsive without weakening dispatch uncertainty."""
import asyncio
import threading
from unittest.mock import MagicMock

import pytest

from app.core import modal_dispatch as dispatch


async def test_submission_keeps_loop_responsive_and_preserves_arguments():
    entered = threading.Event()
    release = threading.Event()

    def slow_submission(value, *, priority):
        entered.set()
        assert release.wait(3)
        return (value, priority)

    task = asyncio.create_task(dispatch.submit_async(slow_submission, "job", priority=4))
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()
        assert not task.done()
        # This coroutine executes while the broker SDK is still waiting.
        await asyncio.sleep(0)
    finally:
        release.set()
    assert await task == ("job", 4)


async def test_cancelled_caller_retains_permit_until_actual_dispatch_finishes(monkeypatch):
    monkeypatch.setattr(dispatch, "_SUBMISSION_CONCURRENCY", 1)
    dispatch._submission_limits.pop(asyncio.get_running_loop(), None)
    entered = threading.Event()
    release = threading.Event()
    second_started = threading.Event()

    def first_submission():
        entered.set()
        assert release.wait(3)

    first = asyncio.create_task(dispatch.submit_async(first_submission))
    while not entered.is_set():
        await asyncio.sleep(0.005)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(dispatch.submit_async(second_started.set))
    try:
        await asyncio.sleep(0.025)
        assert not second_started.is_set()
    finally:
        release.set()
    await second
    assert second_started.is_set()
    dispatch._submission_limits.pop(asyncio.get_running_loop(), None)


async def test_dispatch_failure_reaches_admission_recovery():
    submission = MagicMock(side_effect=RuntimeError("broker acknowledgement lost"))
    with pytest.raises(RuntimeError, match="acknowledgement lost"):
        await dispatch.submit_async(submission)
    submission.assert_called_once_with()


def test_worker_modal_spawn_remains_synchronous(monkeypatch):
    import sys

    sdk = MagicMock()
    monkeypatch.setitem(sys.modules, "modal", sdk)
    payload = {"job_id": "job"}
    dispatch.spawn("run_latex_task", payload)
    sdk.Function.from_name.assert_called_once_with("latexy-backend", "run_latex_task")
    sdk.Function.from_name.return_value.spawn.assert_called_once_with(payload)
