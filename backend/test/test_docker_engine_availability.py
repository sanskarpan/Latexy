"""A Docker client installation alone is not a working TeX sandbox."""

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import latex_service


def test_missing_docker_cli_does_not_probe_daemon():
    with (
        patch.object(latex_service.shutil, "which", return_value=None),
        patch.object(latex_service.subprocess, "run") as run,
    ):
        assert latex_service.docker_engine_available() is False
    run.assert_not_called()


@pytest.mark.parametrize("returncode, available", [(0, True), (1, False), (125, False)])
def test_docker_capability_checks_configured_image_and_bounded_environment(returncode, available):
    with (
        patch.object(latex_service.shutil, "which", return_value="/usr/local/bin/docker"),
        patch.object(latex_service.settings, "LATEX_DOCKER_IMAGE", "local-tex:test"),
        patch.object(latex_service, "engine_env", return_value={"PATH": "/bin"}),
        patch.object(
            latex_service.subprocess, "run", return_value=SimpleNamespace(returncode=returncode)
        ) as run,
    ):
        assert latex_service.docker_engine_available() is available
    run.assert_called_once_with(
        ["docker", "image", "inspect", "local-tex:test"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
        env={"PATH": "/bin"},
        check=False,
    )


@pytest.mark.parametrize(
    "error", [FileNotFoundError(), PermissionError(), subprocess.TimeoutExpired("docker", 5)]
)
def test_docker_capability_fails_closed_for_unavailable_daemon(error):
    with (
        patch.object(latex_service.shutil, "which", return_value="/usr/local/bin/docker"),
        patch.object(latex_service.subprocess, "run", side_effect=error),
    ):
        assert latex_service.docker_engine_available() is False
