"""Prepare LuaTeX font data during image setup, before accepting user jobs."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

FONT_CACHE_SOURCE = (
    r"\documentclass{article}\usepackage{fontspec}"
    r"\setmainfont{Latin Modern Roman}"
    r"\begin{document}Trusted LuaTeX font cache warmup\end{document}"
)
_CJK_FACE_PROBES = (
    ("Noto Sans CJK SC", "中文简体"),
    ("Noto Sans CJK TC", "中文繁體"),
    ("Noto Sans CJK JP", "日本語"),
    ("Noto Sans CJK KR", "한국어"),
)
FONT_CACHE_PROBES = (
    FONT_CACHE_SOURCE,
    *(
        r"\documentclass{article}\usepackage{fontspec}"
        r"\newfontfamily\WarmCjk{" + font + r"}"
        r"\begin{document}{\WarmCjk " + text + r"}\end{document}"
        for font, text in _CJK_FACE_PROBES
    ),
)
# The fonts-extra image can index thousands of fonts on a cold build host.
# This setup budget never changes a queued document's compilation deadline.
SETUP_TIMEOUT_SECONDS = 600


def warmup_environment(cache_dir: Path, config_dir: Path) -> dict[str, str]:
    """No application environment or configurable TeX search path reaches TeX."""
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/nonexistent",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TEXMFVAR": str(cache_dir),
        "TEXMFCONFIG": str(config_dir),
        "openin_any": "r",  # Trusted system font data required by luaotfload.
        "openout_any": "p",
        "shell_escape": "f",
        "max_print_line": "10000",
    }


def warm_cache(cache_dir: Path, config_dir: Path) -> None:
    deadline = time.monotonic() + SETUP_TIMEOUT_SECONDS
    cache_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    # Release each large Noto face's memory before preparing the next face.
    # All probes share one setup deadline and the same runtime-owned cache.
    for source in FONT_CACHE_PROBES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Trusted LuaTeX font-cache initialization timed out")
        with tempfile.TemporaryDirectory(prefix="latexy-trusted-lua-warmup-") as directory:
            workspace = Path(directory)
            (workspace / "warmup.tex").write_text(source, encoding="utf-8")
            try:
                result = subprocess.run(
                    ["lualatex", "-no-shell-escape", "-recorder", "-interaction=batchmode", "-halt-on-error", "warmup.tex"],
                    cwd=workspace,
                    env=warmup_environment(cache_dir, config_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=remaining,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise TimeoutError("Trusted LuaTeX font-cache initialization timed out") from None
            if result.returncode != 0 or not (workspace / "warmup.pdf").is_file():
                raise RuntimeError("Trusted LuaTeX font-cache initialization failed")


if __name__ == "__main__":
    warm_cache(
        Path(os.environ.get("TEXMFVAR", "/var/lib/texmf/latexy-cache")),
        Path(os.environ.get("TEXMFCONFIG", "/var/lib/texmf/latexy-config")),
    )
    print("Trusted LuaTeX font cache initialized.")
