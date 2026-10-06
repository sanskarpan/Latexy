"""B54d contract tests for the real europecv class workflow."""

import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.europecv import (
    EUROPECV_LOCALES,
    configure_europecv_latex,
    is_europecv_source,
    normalize_europecv_locale,
)

SOURCE = (Path(__file__).resolve().parents[1] / "app" / "data" / "templates" / "regional" / "europecv.tex").read_text()


def test_real_europecv_source_is_not_a_generic_article_template():
    assert is_europecv_source(SOURCE)
    assert "\\documentclass" in SOURCE and "{europecv}" in SOURCE
    assert "\\begin{europecv}" in SOURCE


def test_locale_allowlist_accepts_supported_aliases_and_rejects_unavailable_languages():
    assert normalize_europecv_locale("FR") == "fr"
    assert normalize_europecv_locale("fr-FR") == "fr"
    assert normalize_europecv_locale("pt-PT") == "pt"
    assert normalize_europecv_locale("en_IE") == "en"
    assert normalize_europecv_locale("ga") is None  # europecv has no Irish definition
    assert normalize_europecv_locale("hr") is None  # europecv has no Croatian definition
    assert normalize_europecv_locale("nl") is None  # Debian's legacy file is malformed
    assert normalize_europecv_locale("ro") is None  # class option is not LuaLaTeX-safe
    assert normalize_europecv_locale("mt") is None  # Debian's legacy file is malformed
    assert normalize_europecv_locale("lv") is None  # Debian's legacy file is malformed
    assert normalize_europecv_locale("sl") is None  # Debian's legacy file is malformed
    assert normalize_europecv_locale("../../etc/passwd") is None


def test_locale_configuration_is_deterministic_and_forces_lualatex():
    french, compiler = configure_europecv_latex(SOURCE, "fr")
    assert compiler == "lualatex"
    assert "\\documentclass[totpages,helvetica,openbib,nologo,nobranding,notitle,french]{europecv}" in french
    assert "\\usepackage[english]{babel}" in french
    assert configure_europecv_latex(french, "fr") == (french, "lualatex")
    with pytest.raises(ValueError, match="Unsupported europecv"):
        configure_europecv_latex(SOURCE, "fr-FR-extra")


def test_every_closed_locale_uses_only_the_declared_babel_contract():
    for locale, language in EUROPECV_LOCALES.items():
        configured, compiler = configure_europecv_latex(SOURCE, locale)
        assert compiler == "lualatex"
        assert f",{language}]{{europecv}}" in configured
        expected_babel = "english,greek" if locale == "el" else "english"
        assert f"\\usepackage[{expected_babel}]{{babel}}" in configured


@pytest.mark.parametrize("locale", ["en", "fr", "pl", "el"])
def test_representative_locale_compiles_with_lualatex(tmp_path: Path, locale: str):
    lualatex = shutil.which("lualatex")
    if not lualatex:
        pytest.skip("LuaLaTeX is not installed in this development environment")
    source, compiler = configure_europecv_latex(SOURCE, locale)
    tex = tmp_path / "europecv.tex"
    tex.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [compiler, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", tex.name],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert (tmp_path / "europecv.pdf").is_file()


def test_compiled_pdf_extraction_contains_standard_and_candidate_text(tmp_path: Path):
    lualatex = shutil.which("lualatex")
    pdftotext = shutil.which("pdftotext")
    if not lualatex or not pdftotext:
        pytest.skip("LuaLaTeX and pdftotext are required for the extraction probe")
    source, _ = configure_europecv_latex(SOURCE, "fr")
    tex = tmp_path / "europecv.tex"
    tex.write_text(source, encoding="utf-8")
    subprocess.run(
        [lualatex, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", tex.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    extracted = subprocess.run(
        [pdftotext, "-layout", str(tmp_path / "europecv.pdf"), "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "Alex Morgan" in extracted
    assert "Données personnelles" in extracted or "Informations personnelles" in extracted
