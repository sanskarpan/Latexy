"""The local warmed engine must not override a custom sandbox image."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("root_value", "backend_value", "explicit", "expected"),
    [
        (None, None, None, "latexy-tex-engine:local"),
        ("texlive/texlive:latest", None, None, "latexy-tex-engine:local"),
        ('"custom-root:test"', None, None, "custom-root:test"),
        ("custom-root:test", "'custom-backend:test'", None, "custom-backend:test"),
        ("custom-root:test", "custom-backend:test", "custom-process:test", "custom-process:test"),
        (None, None, "texlive/texlive:latest", "texlive/texlive:latest"),
        ("custom-root:test", "texlive/texlive:latest", None, "latexy-tex-engine:local"),
    ],
)
def test_local_tex_image_precedence(root_value, backend_value, explicit, expected, tmp_path):
    repository = Path(__file__).resolve().parents[2]
    (tmp_path / "backend").mkdir()
    for path, value in [(tmp_path / ".env", root_value), (tmp_path / "backend/.env", backend_value)]:
        if value is not None:
            path.write_text(f"LATEX_DOCKER_IMAGE={value}\n")
    source = (repository / "scripts/dev.sh").read_text().split("# ── Main", 1)[0]
    environment = dict(os.environ, LOCAL_TEX_FIXTURE=str(tmp_path), LOCAL_TEX_PYTHON=sys.executable)
    environment.pop("LATEX_DOCKER_IMAGE", None)
    if explicit is not None:
        environment["LATEX_DOCKER_IMAGE"] = explicit
    process = subprocess.run(
        [
            "bash", "-c",
            'source /dev/stdin; PROJECT_ROOT="$LOCAL_TEX_FIXTURE"; resolve_dev_tex_image "$LOCAL_TEX_PYTHON"',
        ],
        input=source,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert process.stdout == expected
