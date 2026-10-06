"""Closed, deterministic LaTeX setup for Arabic and Hebrew documents.

Translation targets are the only callers of this module.  The compiler stack
is deliberately fixed: LuaHBTeX, ``fontspec`` and ``polyglossia``.  Neither a
locale, font family, package name nor TeX command is accepted from a request.
This keeps RTL setup reproducible in the worker images and prevents a
translation response from selecting arbitrary host resources.
"""

from __future__ import annotations

import re

RTL_LANGUAGE_CODES = frozenset({"ar", "he"})

RTL_TARGET_BY_LANGUAGE = {
    "ar": "arabic",
    "he": "hebrew",
}

# These are the fonts installed by the deployment images.  They are selected
# only by the closed language-code map above; user input never reaches TeX.
RTL_FONT_BY_LANGUAGE = {
    "ar": "Noto Naskh Arabic",
    "he": "Noto Sans Hebrew",
}
RTL_FONT_COMMAND_BY_LANGUAGE = {
    "ar": "arabicfont",
    "he": "hebrewfont",
}

_DOCUMENT_CLASS_LINE = re.compile(
    r"^[ \t]*\\documentclass(?:\[[^\]]*\])?[ \t\r\n]*\{[^}\n]+\}[ \t]*(?:\n|$)", re.MULTILINE
)
_PACKAGE_LINE = re.compile(
    r"^(?P<indent>[ \t]*)\\usepackage(?P<options>\[[^\]]*\])?"
    r"\s*\{(?P<packages>[^}]+)\}[ \t]*(?:\n|$)",
    re.MULTILINE,
)

# These packages provide competing engine/encoding/language setup.  Remove
# only these declarations; unrelated user packages and layout commands stay
# intact.  The generated fixed setup is inserted immediately after the class.
_CONFLICTING_PACKAGES = {
    "inputenc",
    "fontenc",
    "fontspec",
    "babel",
    "polyglossia",
    "bidi",
    "luabidi",
}
_CONFLICTING_COMMANDS = re.compile(
    r"^[ \t]*\\(?:setmainlanguage|setotherlanguage|setdefaultlanguage|"
    r"setmainfont|setsansfont|setmonofont)(?:\s*\[[^\]]*\])?"
    r"\s*\{[^}\n]*\}[ \t]*(?:%[^\n]*)?(?:\n|$)|"
    r"^[ \t]*\\(?:newfontfamily|newfontface)\\[A-Za-z@]+"
    r"(?:\s*\[[^\]]*\])?\s*\{[^}\n]*\}[ \t]*(?:\n|$)",
    re.MULTILINE,
)

_DOCUMENT_BEGIN_LINE = re.compile(
    r"^[ \t]*\\begin\{document\}[ \t]*(?:%[^\n]*)?(?:\n|$)",
    re.MULTILINE,
)
_DOCUMENT_END_LINE = re.compile(
    r"^[ \t]*\\end\{document\}[ \t]*(?:%[^\n]*)?(?:\n|$)",
    re.MULTILINE,
)
_GENERATED_FALLBACK_LINES = re.compile(
    r"^[ \t]*\\directlua\{luaotfload\.add_fallback\("
    r'"latexy-rtl-latin(?:-bold|[-]italic|[-]bolditalic)?", '
    r'\{"lmroman10-(?:regular|bold|italic|bolditalic)\.otf:mode=harf"\}\)\}'
    r"[ \t]*(?:\n|$)",
    re.MULTILINE,
)


def normalize_rtl_language_code(language_code: str) -> str | None:
    """Return a supported lower-case code, or ``None`` for every other code."""

    if not isinstance(language_code, str):
        return None
    normalized = language_code.strip().casefold()
    # Keep this contract intentionally small.  Region aliases are not needed
    # by the translation UI and would imply locale-specific language rules we
    # have not measured.  In particular, do not accept arbitrary BCP-47 tags.
    return normalized if normalized in RTL_LANGUAGE_CODES else None


def uses_rtl(language_code: str) -> bool:
    return normalize_rtl_language_code(language_code) is not None


def expected_rtl_target(language_code: str) -> str | None:
    normalized = normalize_rtl_language_code(language_code)
    return RTL_TARGET_BY_LANGUAGE.get(normalized) if normalized else None


def rtl_font_for(language_code: str) -> str | None:
    normalized = normalize_rtl_language_code(language_code)
    return RTL_FONT_BY_LANGUAGE.get(normalized) if normalized else None


def configure_rtl_latex(latex_content: str, language_code: str) -> str:
    """Configure a complete translated document for one measured RTL target.

    Polyglossia supplies directionality while fontspec/HarfBuzz shapes Arabic
    and Hebrew. Explicit English is retained as a secondary language so callers
    can mark Latin product names, URLs and technical terms with
    ``\\textenglish{...}`` inside an otherwise RTL document. Raw Latin glyphs
    have a deterministic fallback, but Unicode script changes alone do not
    establish a bidirectional paragraph boundary. Existing non-language
    packages and body text are preserved. Reapplying the function is idempotent.
    """

    normalized = normalize_rtl_language_code(language_code)
    if normalized is None:
        raise ValueError("Unsupported RTL language code")
    if not _DOCUMENT_CLASS_LINE.search(latex_content):
        raise ValueError("Translated LaTeX is missing a document class")
    document_match = _DOCUMENT_BEGIN_LINE.search(latex_content)
    if document_match is None or _DOCUMENT_END_LINE.search(latex_content, document_match.end()) is None:
        raise ValueError("Translated LaTeX is missing the document environment")

    document_marker = document_match.start()
    if document_marker < 0:  # pragma: no cover - guarded above
        raise ValueError("Translated LaTeX is missing the document environment")
    preamble, body = latex_content[:document_marker], latex_content[document_marker:]

    def remove_conflicting_package(match: re.Match[str]) -> str:
        packages = [part.strip() for part in match.group("packages").split(",")]
        remaining = [package for package in packages if package not in _CONFLICTING_PACKAGES]
        if not remaining:
            return ""
        if len(remaining) == len(packages):
            return match.group(0)
        return (
            f"{match.group('indent')}\\usepackage{match.group('options') or ''}"
            f"{{{','.join(remaining)}}}"
        )

    configured_preamble = _PACKAGE_LINE.sub(remove_conflicting_package, preamble)
    configured_preamble = _CONFLICTING_COMMANDS.sub("", configured_preamble)
    # Reconfiguration must not accumulate the deterministic fallback
    # declarations generated below.  Restrict this removal to the exact
    # names/files we own; arbitrary user \directlua code remains untouched.
    configured_preamble = _GENERATED_FALLBACK_LINES.sub("", configured_preamble)
    document_class = _DOCUMENT_CLASS_LINE.search(configured_preamble)
    if document_class is None:  # pragma: no cover - guarded above
        raise ValueError("Translated LaTeX is missing a document class")

    font = RTL_FONT_BY_LANGUAGE[normalized]
    target = RTL_TARGET_BY_LANGUAGE[normalized]
    font_command = RTL_FONT_COMMAND_BY_LANGUAGE[normalized]
    # Strip the line ending included by _DOCUMENT_CLASS_LINE and any blank
    # lines left by removed declarations so repeated configuration has one
    # stable representation.
    insertion = (
        f"{document_class.group(0).rstrip()}\n"
        r"\usepackage{fontspec}" + "\n"
        r"\usepackage{polyglossia}" + "\n"
        # Polyglossia selects the script font for an RTL paragraph.  Noto's
        # Arabic/Hebrew families intentionally do not contain Latin glyphs,
        # so register the bundled Latin Modern faces as LuaHBTeX fallbacks.
        # This keeps raw Latin glyphs from becoming missing-character boxes;
        # callers still need \textenglish for correct direction and extraction.
        # The filenames are provided by TeX Live's
        # lmodern package, which is present in the deployment image.
        r'\directlua{luaotfload.add_fallback("latexy-rtl-latin", {"lmroman10-regular.otf:mode=harf"})}' + "\n"
        r'\directlua{luaotfload.add_fallback("latexy-rtl-latin-bold", {"lmroman10-bold.otf:mode=harf"})}' + "\n"
        r'\directlua{luaotfload.add_fallback("latexy-rtl-latin-italic", {"lmroman10-italic.otf:mode=harf"})}' + "\n"
        r'\directlua{luaotfload.add_fallback("latexy-rtl-latin-bolditalic", {"lmroman10-bolditalic.otf:mode=harf"})}' + "\n"
        # Keep Latin glyphs out of the script-specific Noto family.  Without
        # an explicit Latin main font, LuaHBTeX reports missing glyphs for
        # product names, URLs, bullets and technical terms in RTL paragraphs.
        r"\setmainfont{Latin Modern Roman}" + "\n"
        rf"\setmainlanguage{{{target}}}" + "\n"
        r"\setotherlanguage{english}" + "\n"
        rf"\newfontfamily\{font_command}[Script={target.title()},RawFeature={{fallback=latexy-rtl-latin}},BoldFeatures={{RawFeature={{fallback=latexy-rtl-latin-bold}}}},ItalicFeatures={{RawFeature={{fallback=latexy-rtl-latin-italic}}}},BoldItalicFeatures={{RawFeature={{fallback=latexy-rtl-latin-bolditalic}}}}]{{{font}}}" + "\n"
    )
    configured_preamble = (
        configured_preamble[: document_class.start()]
        + insertion
        + configured_preamble[document_class.end() :].lstrip("\n")
    )
    configured = configured_preamble + body
    return re.sub(r"\n{3,}", "\n\n", configured).strip()
