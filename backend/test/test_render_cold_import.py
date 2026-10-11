"""Renderer service imports must work before eager worker package initialization."""
import subprocess
import sys
from pathlib import Path


def test_passes_import_in_clean_python_process():
    result = subprocess.run([sys.executable, "-c",
        "import sys; from app.services.render_engine.passes import RenderPassError; "
        "assert issubclass(RenderPassError, ValueError); "
        "assert 'app.workers.latex_worker' not in sys.modules"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
