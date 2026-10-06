"""B54c contract tests for one LuaHBTeX document containing many scripts."""

from __future__ import annotations

import shutil
import subprocess
import unicodedata

import pytest

from app.services.multilingual_latex import (
    MULTILINGUAL_ENGINE,
    compiler_for_multilingual,
    configure_multilingual_latex,
    detect_multilingual_language_codes,
    normalize_multilingual_language_code,
)

SOURCE = r"""\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{geometry}
\begin{document}
English résumé. 日本語 العربية עברית हिंदी
\end{document}"""


def test_allowlist_has_no_user_package_or_font_surface() -> None:
    assert normalize_multilingual_language_code("JA") == "ja"
    assert normalize_multilingual_language_code("ar") == "ar"
    assert normalize_multilingual_language_code("hi") == "hi"
    for value in ("fr", "ar-SA", "xx", "Noto Sans CJK JP", "../../etc/passwd", "ja;rm -rf /"):
        assert normalize_multilingual_language_code(value) is None


def test_script_detection_is_a_hint_and_does_not_accept_arbitrary_locale_tags() -> None:
    detected = detect_multilingual_language_codes("English العربية עברית हिंदी 日本語の 한국어")
    assert set(detected) == {"ar", "he", "hi", "ja", "ko"}
    # Ideographs are intentionally ambiguous; the caller must supply zh/ja.
    assert "zh" in detect_multilingual_language_codes("中文")
    # Hanja within otherwise Korean text must keep the explicit Korean profile;
    # adding an ambiguous Chinese profile would make this valid document fail.
    assert detect_multilingual_language_codes("한국어 履歷") == ("ko",)


def test_mixed_setup_is_structural_deterministic_and_idempotent() -> None:
    configured = configure_multilingual_latex(SOURCE, ["ja", "ar", "he", "hi"])
    assert compiler_for_multilingual(["ja", "ar", "he", "hi"]) == MULTILINGUAL_ENGINE
    assert "\\usepackage{luatexja-fontspec}" in configured
    assert "Noto Sans CJK JP" in configured
    assert "\\usepackage{polyglossia}" in configured
    assert "Noto Naskh Arabic" in configured
    assert "Noto Sans Hebrew" in configured
    assert "Renderer=HarfBuzz,Script=Devanagari" in configured
    assert "Noto Sans Devanagari" in configured
    assert "BoldFont={Noto Sans Devanagari Bold}" in configured
    assert "ItalicFeatures={FakeSlant=0.15}" in configured
    assert "BoldItalicFont={Noto Sans Devanagari Bold}" in configured
    # Polyglossia owns language switching whenever RTL is present, so the
    # standalone Babel/onchar contract is intentionally not emitted here.
    assert r"\setmainfont{Latin Modern Roman}" in configured
    assert r"\newfontfamily\hindifont[" in configured
    assert r"\usepackage{babel}" not in configured
    assert "\\usepackage{geometry}" in configured
    assert "\\usepackage[utf8]{inputenc}" not in configured
    assert "\\usepackage[T1]{fontenc}" not in configured
    assert configure_multilingual_latex(configured, ["ja", "ar", "he", "hi"]) == configured


def test_body_and_verbatim_text_are_not_rewritten() -> None:
    source = SOURCE.replace(
        "English résumé. 日本語 العربية עברית हिंदी",
        r"\begin{verbatim}\usepackage{ctex} Noto Sans CJK JP\end{verbatim}",
    )
    configured = configure_multilingual_latex(source, "zh-CN")
    assert r"\usepackage{ctex} Noto Sans CJK JP" in configured


def test_invalid_or_incomplete_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="document class"):
        configure_multilingual_latex("العربية", "ar")
    with pytest.raises(ValueError, match="document environment"):
        configure_multilingual_latex("\\documentclass{article}\nالعربية", "ar")
    with pytest.raises(ValueError, match="Unsupported multilingual"):
        configure_multilingual_latex(SOURCE, "fr")
    with pytest.raises(ValueError, match="Only one CJK"):
        configure_multilingual_latex(SOURCE, ["ja", "zh"])
    with pytest.raises(ValueError, match="Only one Devanagari"):
        configure_multilingual_latex(SOURCE, ["hi", "mr"])


@pytest.mark.skipif(
    shutil.which("lualatex") is None or shutil.which("pdftotext") is None or shutil.which("fc-match") is None,
    reason="LuaHBTeX, pdftotext, and fontconfig are required for the deployment compile probe",
)
def test_luahbtex_mixed_cjk_rtl_compile_and_text_extraction(tmp_path) -> None:
    required_fonts = (
        "Noto Sans CJK JP",
        "Noto Naskh Arabic",
        "Noto Sans Hebrew",
        "Noto Sans Devanagari",
    )
    for family in required_fonts:
        probe = subprocess.run(["fc-match", family], capture_output=True, text=True, check=False)
        if family not in probe.stdout:
            pytest.skip(f"developer host does not carry deployment font {family}")

    source = r"""\documentclass{article}
\begin{document}
\textenglish{English product name.} 日本語の履歴書。
\textarabic{السيرة الذاتية} \texthebrew{קורות חיים} \texthindi{हिंदी परिचय}
\end{document}"""
    tex = tmp_path / "mixed.tex"
    tex.write_text(configure_multilingual_latex(source, ["ja", "ar", "he", "hi"]), encoding="utf-8")
    result = subprocess.run(
        ["lualatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", tex.name],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-5000:]
    extracted = subprocess.run(
        ["pdftotext", str(tmp_path / "mixed.pdf"), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # HarfBuzz/ToUnicode may expose Arabic presentation forms in extraction;
    # compare the canonical characters rather than a renderer-specific glyph
    # encoding while retaining the exact script-content assertion.
    extracted = unicodedata.normalize("NFKC", extracted)
    assert "English product name" in extracted
    assert "日本語" in extracted
    assert "السيرة" in extracted
    assert "קורות" in extracted
    assert "हिंदी" in extracted
