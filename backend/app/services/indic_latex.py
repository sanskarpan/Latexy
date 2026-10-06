"""Deterministic LaTeX setup for the Indic scripts Latexy actually supports."""

from __future__ import annotations

import re

DEVANAGARI_LANGUAGE_CODES = frozenset({"hi", "mr"})

# Noto Sans Devanagari ships real regular and bold faces in fonts-noto-core.
# It does not ship an italic face, so the hosted contract explicitly reuses
# the regular/bold face with a modest fake slant.  Naming BoldFont and the
# italic source faces keeps fontspec from probing absent shapes (or silently
# synthesising fake bold) while preserving HarfBuzz shaping and extraction.
DEVANAGARI_FONT = "Noto Sans Devanagari"
DEVANAGARI_FONT_OPTIONS = (
    "Renderer=HarfBuzz,Script=Devanagari,"
    "BoldFont={Noto Sans Devanagari Bold},"
    "ItalicFont={Noto Sans Devanagari},ItalicFeatures={FakeSlant=0.15},"
    "BoldItalicFont={Noto Sans Devanagari Bold},BoldItalicFeatures={FakeSlant=0.15}"
)

_PACKAGE_LINE = re.compile(
    r"^(?P<indent>[ \t]*)\\usepackage(?P<options>\[[^\]]*\])?"
    r"\{(?P<packages>[^}]+)\}[ \t]*$",
    re.MULTILINE,
)
_BABEL_FONT_LINE = re.compile(r"^[ \t]*\\babelfont(?:\[[^\]]*\])?\{[^\n]*$", re.MULTILINE)
_DOCUMENT_CLASS_LINE = re.compile(r"^[ \t]*\\documentclass(?:\[[^\]]*\])?\{[^}]+\}[ \t]*$", re.MULTILINE)

_DEVANAGARI_PREAMBLE = (
    r"\usepackage{fontspec}" + "\n"
    r"\usepackage[english,hindi,provide=*]{babel}" + "\n"
    r"\babelprovide[onchar=ids fonts]{english}" + "\n"
    rf"\babelfont[hindi]{{rm}}[{DEVANAGARI_FONT_OPTIONS}]{{{DEVANAGARI_FONT}}}" + "\n"
    r"\babelfont[english]{rm}{Latin Modern Roman}" + "\n"
    # Babel/fontspec registers the explicit bold face as series ``b``.
    # Selecting that series avoids harmless-but-noisy ``bx`` fallback logs.
    r"\renewcommand{\bfdefault}{b}" + "\n"
    # Standard LaTeX list labels are selected in the active language too;
    # keep their bullet glyph on the Latin font when the document is Hindi.
    r"\renewcommand{\labelitemi}{\foreignlanguage{english}{\textbullet}}" + "\n"
    r"\renewcommand{\labelitemii}{\foreignlanguage{english}{\textbullet}}" + "\n"
    r"\renewcommand{\labelitemiii}{\foreignlanguage{english}{\textbullet}}" + "\n"
    r"\renewcommand{\labelitemiv}{\foreignlanguage{english}{\textbullet}}" + "\n"
    # Babel's script switching covers letters/identifiers, not punctuation.
    # Map a literal bullet in translated body text to the Latin bullet glyph.
    r'\catcode"2022=\active' + "\n"
    r'\begingroup\lccode`\~="2022 \lowercase{\endgroup\def~}{\foreignlanguage{english}{\textbullet}}'
)


def uses_devanagari(language_code: str) -> bool:
    """Return whether a translation target uses the hosted Devanagari stack."""

    return language_code.strip().lower() in DEVANAGARI_LANGUAGE_CODES


def configure_devanagari_latex(latex_content: str) -> str:
    """Make a translated document safe to compile with LuaHBTeX.

    A source may be a pdfLaTeX document or may already carry a different
    babel/fontspec setup. Remove only mutually exclusive encoding/language
    declarations, then install Latexy's pinned hosted-font contract.
    """

    if not _DOCUMENT_CLASS_LINE.search(latex_content):
        raise ValueError("Translated LaTeX is missing a document class")
    if r"\begin{document}" not in latex_content or r"\end{document}" not in latex_content:
        raise ValueError("Translated LaTeX is missing the document environment")

    def remove_conflicting_package(match: re.Match[str]) -> str:
        conflicts = {"inputenc", "fontenc", "fontspec", "babel", "polyglossia"}
        packages = [part.strip() for part in match.group("packages").split(",")]
        remaining = [package for package in packages if package not in conflicts]
        if not remaining:
            return ""
        if len(remaining) == len(packages):
            return match.group(0)
        return f"{match.group('indent')}\\usepackage{match.group('options') or ''}{{{','.join(remaining)}}}"

    configured = _PACKAGE_LINE.sub(remove_conflicting_package, latex_content)
    configured = _BABEL_FONT_LINE.sub("", configured)
    document_class = _DOCUMENT_CLASS_LINE.search(configured)
    if document_class is None:  # pragma: no cover - guarded above
        raise ValueError("Translated LaTeX is missing a document class")

    insertion = f"{document_class.group(0)}\n{_DEVANAGARI_PREAMBLE}"
    configured = configured[: document_class.start()] + insertion + configured[document_class.end() :]
    return re.sub(r"\n{3,}", "\n\n", configured).strip()
