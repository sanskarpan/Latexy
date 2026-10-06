"""Contract tests for the closed Arabic/Hebrew LaTeX setup."""

import shutil
import subprocess

import pytest

from app.services.rtl_latex import (
    configure_rtl_latex,
    expected_rtl_target,
    normalize_rtl_language_code,
    rtl_font_for,
    uses_rtl,
)

SOURCE = r"""\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{geometry}
\usepackage{polyglossia}
\setmainlanguage{english}
\begin{document}
\textenglish{Latin product name Acme Corp} — العربية — עברית
\end{document}"""


@pytest.mark.parametrize(
    ("code", "target", "font"),
    [
        ("ar", "arabic", "Noto Naskh Arabic"),
        ("AR", "arabic", "Noto Naskh Arabic"),
        ("he", "hebrew", "Noto Sans Hebrew"),
        (" HE ", "hebrew", "Noto Sans Hebrew"),
    ],
)
def test_only_closed_rtl_contract_is_exposed(code: str, target: str, font: str) -> None:
    assert normalize_rtl_language_code(code) == code.strip().lower()
    assert uses_rtl(code)
    assert expected_rtl_target(code) == target
    assert rtl_font_for(code) == font


@pytest.mark.parametrize(
    "code",
    ["", "fr", "ar-SA", "he-IL", "ar_XX", "../../etc/passwd", "ar;rm -rf /"],
)
def test_unknown_or_unsafe_codes_are_rejected(code: str) -> None:
    assert normalize_rtl_language_code(code) is None
    assert not uses_rtl(code)


@pytest.mark.parametrize(
    ("code", "font_command", "target", "font"),
    [
        ("ar", r"\arabicfont", "arabic", "Noto Naskh Arabic"),
        ("he", r"\hebrewfont", "hebrew", "Noto Sans Hebrew"),
    ],
)
def test_configuration_preserves_mixed_text_and_unrelated_preamble(
    code: str, font_command: str, target: str, font: str
) -> None:
    source = SOURCE.replace(
        r"\begin{document}",
        r"""\newfontfamily\attackerfont{AttackerFont}
\begin{document}""",
    )
    configured = configure_rtl_latex(source, code)

    assert r"\usepackage[utf8]{inputenc}" not in configured
    assert r"\usepackage[T1]{fontenc}" not in configured
    assert r"\usepackage{polyglossia}" in configured
    assert r"\usepackage{geometry}" in configured
    assert rf"\setmainlanguage{{{target}}}" in configured
    assert r"\setotherlanguage{english}" in configured
    assert rf"\newfontfamily{font_command}[Script={target.title()},RawFeature={{fallback=latexy-rtl-latin}}" in configured
    assert r'luaotfload.add_fallback("latexy-rtl-latin"' in configured
    assert "AttackerFont" not in configured
    assert r"\textenglish{Latin product name Acme Corp}" in configured
    assert "العربية" in configured
    assert "עברית" in configured


@pytest.mark.parametrize("code", ["ar", "he"])
def test_configuration_is_idempotent(code: str) -> None:
    configured = configure_rtl_latex(SOURCE, code)
    assert configure_rtl_latex(configured, code) == configured


def test_configuration_does_not_rewrite_body_or_verbatim_like_text() -> None:
    source = SOURCE.replace(
        r"\end{document}",
        r"""\begin{verbatim}
\newfontfamily\literalfont{KeepThisBodyText}
\setmainfont{KeepThisBodyFont}
\end{verbatim}
\end{document}""",
    )
    configured = configure_rtl_latex(source, "ar")
    assert r"\newfontfamily\literalfont{KeepThisBodyText}" in configured
    assert r"\setmainfont{KeepThisBodyFont}" in configured


def test_configuration_removes_multiline_conflicting_preamble_declarations() -> None:
    source = SOURCE.replace(
        r"\usepackage{polyglossia}",
        r"""\usepackage[
english
]{polyglossia}
\newfontfamily\attackerfont[
Script=Arabic
]{AttackerFont}""",
    )
    configured = configure_rtl_latex(source, "ar")
    assert "AttackerFont" not in configured
    assert r"\attackerfont" not in configured
    assert configured.count(r"\usepackage{polyglossia}") == 1
    assert "Script=Arabic" in configured


def test_multiline_documentclass_and_commented_commands_are_structural_only() -> None:
    source = r"""% \begin{document} (commented example)
\documentclass[
  11pt,
  letterpaper
]{article}
% \usepackage{polyglossia} (must remain a comment)
\usepackage[
  utf8
]{inputenc}
\begin{document}
\begin{verbatim}
\setmainlanguage{english}
\end{verbatim}
العربية
\end{document}
"""
    configured = configure_rtl_latex(source, "ar")
    assert "11pt" in configured and "letterpaper" in configured
    assert "% \\usepackage{polyglossia} (must remain a comment)" in configured
    assert "\\usepackage[\n  utf8\n]{inputenc}" not in configured
    assert "\\setmainlanguage{english}" in configured
    body_start = configured.index("\\begin{verbatim}")
    assert configured.index("\\setmainlanguage{english}", body_start) > body_start


def test_configuration_rejects_incomplete_or_unsupported_output() -> None:
    with pytest.raises(ValueError, match="document class"):
        configure_rtl_latex("العربية", "ar")
    with pytest.raises(ValueError, match="document environment"):
        configure_rtl_latex(r"""\documentclass{article}
\section{العربية}""", "ar")
    with pytest.raises(ValueError, match="Unsupported RTL"):
        configure_rtl_latex(SOURCE, "fr")


@pytest.mark.parametrize(
    ("code", "font", "arabic", "hebrew"),
    [
        ("ar", "Noto Naskh Arabic", "السيرة الذاتية", "עברית"),
        ("he", "Noto Sans Hebrew", "العربية", "קורות חיים"),
    ],
)
@pytest.mark.skipif(
    shutil.which("lualatex") is None or shutil.which("pdftotext") is None,
    reason="LuaHBTeX and pdftotext are required for the RTL compile probe",
)
def test_lualatex_rtl_compile_and_pdf_text_layer(
    tmp_path, code: str, font: str, arabic: str, hebrew: str
) -> None:
    font_probe = subprocess.run(
        ["fc-match", "-f", "%{family}", font], capture_output=True, text=True, check=False
    )
    if font not in font_probe.stdout:
        pytest.skip(f"developer host does not carry deployment font {font!r}")

    source = configure_rtl_latex(
        SOURCE.replace("العربية", arabic).replace("עברית", hebrew), code
    )
    tex = tmp_path / "rtl.tex"
    tex.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [
            "lualatex",
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "rtl.tex",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-5000:]
    pdf = tmp_path / "rtl.pdf"
    assert pdf.is_file()
    extracted = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", str(pdf), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    import unicodedata

    # Poppler may return Arabic presentation forms. Require the exact words
    # after Unicode compatibility normalization, preserving their order.
    assert arabic in unicodedata.normalize("NFKC", extracted)
    assert hebrew in extracted
    assert "Acme Corp" in extracted
