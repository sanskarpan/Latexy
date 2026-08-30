"""Subprocess ownership tests for the legacy LaTeX compiler adapter."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.latex_compiler import LaTeXCompiler


def _compiler() -> LaTeXCompiler:
    compiler = object.__new__(LaTeXCompiler)
    compiler.latex_command = "pdflatex"
    compiler.docker_image = "texlive:test"
    return compiler


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", ["_compile_local", "_compile_with_docker"])
async def test_timeout_kills_and_reaps_subprocess(method_name: str) -> None:
    process = MagicMock()
    process.returncode = None
    process.communicate = MagicMock(return_value=asyncio.Future())
    process.wait = AsyncMock(return_value=-9)

    with (
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)),
        patch("asyncio.wait_for", AsyncMock(side_effect=asyncio.TimeoutError)),
    ):
        result = await getattr(_compiler(), method_name)(Path("/tmp/job"), 1)

    assert result == (False, "Compilation timeout after 1 seconds")
    process.kill.assert_called_once_with()
    process.wait.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", ["_compile_local", "_compile_with_docker"])
async def test_cancellation_kills_and_reaps_subprocess(method_name: str) -> None:
    process = MagicMock()
    process.returncode = None
    process.communicate = MagicMock(return_value=asyncio.Future())
    process.wait = AsyncMock(return_value=-9)

    with (
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)),
        patch("asyncio.wait_for", AsyncMock(side_effect=asyncio.CancelledError)),
        pytest.raises(asyncio.CancelledError),
    ):
        await getattr(_compiler(), method_name)(Path("/tmp/job"), 1)

    process.kill.assert_called_once_with()
    process.wait.assert_awaited_once_with()
