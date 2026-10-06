"""Contract tests for the deterministic B54a CJK LaTeX setup."""

import shutil
import subprocess

import pytest

from app.services.cjk_latex import (
    cjk_font_for,
    configure_cjk_latex,
    expected_cjk_target,
    normalize_cjk_language_code,
    uses_cjk,
)

SOURCE = r"""\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{geometry}
\usepackage{xeCJK}
\begin{document}
Latin English 日本語 中文 한국어
\end{document}"""


@pytest.mark.parametrize(
    ("code", "font"),
    [
        ("zh", "Noto Sans CJK SC"),
        ("zh-CN", "Noto Sans CJK SC"),
        ("zh-TW", "Noto Sans CJK TC"),
        ("ja", "Noto Sans CJK JP"),
        ("ko", "Noto Sans CJK KR"),
    ],
)
def test_supported_codes_select_only_pinned_region_font(code: str, font: str):
    normalized = normalize_cjk_language_code(code)
    assert normalized is not None
    assert uses_cjk(code)
    assert cjk_font_for(code) == font
    assert expected_cjk_target(code) is not None


@pytest.mark.parametrize("code", ["", "fr", "zh-evil", "zh_CN", "../../etc/passwd", "ja;rm -rf /"])
def test_unknown_or_unsafe_codes_are_rejected(code: str):
    assert normalize_cjk_language_code(code) is None
    assert not uses_cjk(code)


def test_configuration_is_luahbtex_mixed_script_safe_and_idempotent():
    configured = configure_cjk_latex(
        SOURCE.replace(
            r"\begin{document}",
            "\\setmainjfont{AttackerFont}\n\\setCJKmainfont{OtherFont}\n\\begin{document}",
        ),
        "ja",
    )

    assert r"\usepackage[utf8]{inputenc}" not in configured
    assert r"\usepackage[T1]{fontenc}" not in configured
    assert r"\usepackage{xeCJK}" not in configured
    assert r"\usepackage{geometry}" in configured
    assert r"\usepackage{luatexja-fontspec}" in configured
    assert r"\setmainjfont{Noto Sans CJK JP}" in configured
    assert "AttackerFont" not in configured
    assert "OtherFont" not in configured
    assert "Latin English 日本語 中文 한국어" in configured
    assert configure_cjk_latex(configured, "ja") == configured


def test_body_commands_are_not_rewritten():
    source = SOURCE.replace(
        "Latin English 日本語 中文 한국어",
        r"\usepackage{xeCJK} literal body text",
    )
    configured = configure_cjk_latex(source, "ja")
    assert r"\usepackage{xeCJK} literal body text" in configured


def test_unrelated_latin_font_and_language_configuration_is_preserved():
    source = SOURCE.replace(
        r"\usepackage{geometry}",
        "\\usepackage{geometry}\n\\usepackage[english,french]{babel}\n"
        "\\usepackage{fontspec}\n\\setmainfont{Latin Modern Sans}",
    )
    configured = configure_cjk_latex(source, "ja")
    assert r"\usepackage[english,french]{babel}" in configured
    assert r"\usepackage{fontspec}" in configured
    assert r"\setmainfont{Latin Modern Sans}" in configured


def test_multiline_preamble_declarations_are_replaced_without_touching_body():
    source = SOURCE.replace(
        r"\usepackage{xeCJK}",
        "\\usepackage[\n  CJKchecksingle\n]{xeCJK}",
    ).replace(
        r"\documentclass{article}",
        "\\documentclass[\n  11pt\n]{article}",
    )
    configured = configure_cjk_latex(source, "ja")
    assert "CJKchecksingle" not in configured
    assert "11pt" in configured
    assert r"\usepackage{luatexja-fontspec}" in configured


def test_multiline_documentclass_and_commented_commands_are_structural_only():
    source = r"""% \begin{document} (commented example)
\documentclass[
  11pt,
  letterpaper
]{article}
% \usepackage{xeCJK} (must remain a comment)
\usepackage[
  utf8
]{inputenc}
\begin{document}
\begin{verbatim}
\usepackage{xeCJK}
\end{verbatim}
中文
\end{document}
"""
    configured = configure_cjk_latex(source, "zh-CN")
    assert "11pt" in configured and "letterpaper" in configured
    assert "% \\usepackage{xeCJK} (must remain a comment)" in configured
    assert "\\usepackage[\n  utf8\n]{inputenc}" not in configured
    assert "\\usepackage{xeCJK}" in configured
    assert configured.index("\\begin{verbatim}") < configured.index("\\usepackage{xeCJK}", configured.index("\\begin{verbatim}"))


def test_replaced_package_comments_are_preserved():
    source = SOURCE.replace(r"\usepackage{xeCJK}", r"\usepackage{xeCJK} % CJK engine")
    configured = configure_cjk_latex(source, "ja")
    assert "% CJK engine" in configured


@pytest.mark.parametrize(
    ("code", "required"),
    [
        ("zh-CN", r"\usepackage[fontset=none,scheme=plain]{ctex}"),
        ("zh-TW", r"\setCJKmainfont{Noto Sans CJK TC}"),
        ("ja", r"\usepackage{luatexja-fontspec}"),
        ("ko", r"\usepackage{luatexko}"),
    ],
)
def test_each_script_uses_its_language_specific_line_breaking_stack(code: str, required: str):
    configured = configure_cjk_latex(SOURCE, code)
    assert required in configured
    if code == "ko":
        assert r"\setmainhangulfont{Noto Sans CJK KR}" in configured
        assert r"\setmainhanjafont{Noto Sans CJK KR}" in configured


def test_configuration_rejects_incomplete_latex():
    with pytest.raises(ValueError, match="document class"):
        configure_cjk_latex("日本語", "ja")
    with pytest.raises(ValueError, match="document environment"):
        configure_cjk_latex("\\documentclass{article}\n日本語", "ja")
    with pytest.raises(ValueError, match="Unsupported CJK"):
        configure_cjk_latex(SOURCE, "fr")


@pytest.mark.skipif(
    shutil.which("lualatex") is None or shutil.which("fc-match") is None,
    reason="LuaHBTeX and fontconfig are required for the CJK compile probe",
)
def test_luahbtex_cjk_compile_uses_hosted_font_when_available(tmp_path):
    """Exercise the real engine where the image's Noto package is installed."""
    font_probe = subprocess.run(
        ["fc-match", "Noto Sans CJK JP"], capture_output=True, text=True, check=False
    )
    if "Noto Sans CJK JP" not in font_probe.stdout:
        pytest.skip("developer host does not carry the deployment Noto CJK font")

    source = configure_cjk_latex(SOURCE, "ja")
    tex = tmp_path / "cjk.tex"
    tex.write_text(source, encoding="utf-8")
    result = subprocess.run(
        ["lualatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "cjk.tex"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    assert (tmp_path / "cjk.pdf").is_file()
    assert "Missing character" not in (result.stdout + result.stderr)


@pytest.mark.skipif(shutil.which("lualatex") is None, reason="LuaHBTeX is required for the CJK matrix")
@pytest.mark.parametrize(
    ("code", "deployment_font", "host_font", "text"),
    [
        ("zh-CN", "Noto Sans CJK SC", "Heiti SC", "中文简历，平台工程师。"),
        ("zh-TW", "Noto Sans CJK TC", "Heiti TC", "中文履歷，平台工程師。"),
        ("ja", "Noto Sans CJK JP", "Hiragino Sans", "日本語の履歴書。"),
        ("ko", "Noto Sans CJK KR", "Apple SD Gothic Neo", "한국어 이력서입니다."),
    ],
)
def test_each_cjk_script_compiles_with_mixed_latin_and_extractable_source(
    tmp_path, code: str, deployment_font: str, host_font: str, text: str
):
    """Run all script-specific packages locally, substituting only host fonts.

    CI/Modal runs the same test with the pinned Noto family.  A developer Mac
    has equivalent Apple fonts but not the deployment package, so this still
    exercises the package/JFM path without pretending the font assets match.
    """
    font_probe = subprocess.run(["fc-match", host_font], capture_output=True, text=True, check=False)
    if host_font not in font_probe.stdout:
        pytest.skip(f"developer host does not carry {host_font}")
    source = configure_cjk_latex(
        SOURCE.replace("日本語 中文 한국어", text), code
    ).replace(deployment_font, host_font)
    tex = tmp_path / f"{code.replace('-', '_')}.tex"
    tex.write_text(source, encoding="utf-8")
    result = subprocess.run(
        ["lualatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", tex.name],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    assert tex.with_suffix(".pdf").is_file()
    assert "Missing character" not in (result.stdout + result.stderr)
    if shutil.which("pdftotext"):
        extracted = subprocess.run(
            ["pdftotext", str(tex.with_suffix(".pdf")), "-"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert text in extracted
