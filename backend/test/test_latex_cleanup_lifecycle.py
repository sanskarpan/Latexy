"""Lifecycle tests for request-scheduled LaTeX artifact cleanup."""

from __future__ import annotations

import asyncio

import pytest

from app.services.latex_service import LaTeXService


@pytest.mark.asyncio
async def test_shutdown_cancels_and_awaits_delayed_cleanup(tmp_path) -> None:
    service = LaTeXService()
    started = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def _blocking_cleanup(_job_dir, _delay) -> None:
        started.set()
        try:
            await asyncio.sleep(3600)
        finally:
            await asyncio.sleep(0)
            cleanup_finished.set()

    service.cleanup_temp_files_delayed = _blocking_cleanup
    task = service.schedule_temp_cleanup(tmp_path / "job-1", delay=3600)
    await started.wait()

    await service.shutdown_cleanup_tasks()

    assert task.done()
    assert cleanup_finished.is_set()
    assert service._cleanup_tasks == set()


@pytest.mark.asyncio
async def test_finished_cleanup_removes_itself_from_registry(tmp_path) -> None:
    service = LaTeXService()

    async def _instant_cleanup(_job_dir, _delay) -> None:
        return None

    service.cleanup_temp_files_delayed = _instant_cleanup
    task = service.schedule_temp_cleanup(tmp_path / "job-2", delay=0)
    await task
    await asyncio.sleep(0)

    assert service._cleanup_tasks == set()
