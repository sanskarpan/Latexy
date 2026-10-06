import re
import shutil
import subprocess

import pytest

from app.services.auto_fit_service import (
    AUTO_FIT_PROFILES,
    END_MARKER,
    START_MARKER,
    apply_auto_fit,
    profile_for_intensity,
    remove_auto_fit,
)

SOURCE = r"""\documentclass{article}
\begin{document}
Important resume content.
\end{document}
"""


def test_profiles_are_ordered_and_stop_at_a_legible_floor():
    assert [profile.intensity for profile in AUTO_FIT_PROFILES] == [25, 50, 75, 100]
    assert AUTO_FIT_PROFILES[-1].line_spread >= 0.88
    assert AUTO_FIT_PROFILES[-1].use_small_font is True


def test_apply_is_reversible_and_does_not_change_document_body():
    fitted = apply_auto_fit(SOURCE, AUTO_FIT_PROFILES[1])

    assert fitted.count(START_MARKER) == 1
    assert fitted.count(END_MARKER) == 1
    assert r"\linespread{0.94}" in fitted
    assert "Important resume content." in fitted
    assert remove_auto_fit(fitted) == SOURCE


def test_reapplying_replaces_instead_of_stacking_fit_blocks():
    first = apply_auto_fit(SOURCE, AUTO_FIT_PROFILES[0])
    second = apply_auto_fit(first, AUTO_FIT_PROFILES[-1])

    assert second.count(START_MARKER) == 1
    assert r"\linespread{0.88}" in second
    assert r"\linespread{0.97}" not in second
    assert r"\AtBeginDocument{\small}" in second


def test_slider_intensity_maps_up_to_a_bounded_profile():
    assert profile_for_intensity(1).intensity == 25
    assert profile_for_intensity(50).intensity == 50
    assert profile_for_intensity(51).intensity == 75
    assert profile_for_intensity(100).intensity == 100


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_real_tex_profile_can_recover_a_small_second_page(tmp_path):
    source = r"""\documentclass{article}
\begin{document}
First block\vspace*{105mm}\par
Second block\vspace*{105mm}\par
\end{document}
"""

    def compile_pages(name: str, content: str) -> int:
        (tmp_path / f"{name}.tex").write_text(content, encoding="utf-8")
        result = subprocess.run(
            [
                "pdflatex",
                "-no-shell-escape",
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"{name}.tex",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stdout[-2000:]
        matches = re.findall(r"Output written on .*?\((\d+) page", result.stdout)
        assert matches
        return int(matches[-1])

    assert compile_pages("original", source) == 2
    assert compile_pages("fitted", apply_auto_fit(source, AUTO_FIT_PROFILES[-1])) == 1
