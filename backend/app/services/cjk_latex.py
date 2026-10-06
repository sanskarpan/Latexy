"""Deterministic CJK setup for translated and user-authored LaTeX.

The worker images deliberately contain the complete, offline CJK contract:
LuaHBTeX plus a language-specific adapter (``luatexja-fontspec`` for Japanese,
``ctex`` for Chinese, and ``luatexko`` for Korean) and regular Noto Sans CJK
families. This module only selects from that fixed contract; it never accepts a
font name or package name from a caller. Keeping the choice here also prevents
the translation route from claiming CJK support while leaving a pdfLaTeX
variant that cannot typeset Unicode text.
"""

from __future__ import annotations

import re

CJK_LANGUAGE_CODES = frozenset(
    {
        "zh",
        "zh-cn",
        "zh-hans",
        "zh-sg",
        "zh-tw",
        "zh-hant",
        "zh-hk",
        "ja",
        "ko",
    }
)

# The font family names are provided by Debian's fonts-noto-cjk package.  The
# region-specific families matter for punctuation and glyph forms even though
# all four cover the common CJK Unified Ideographs block.
CJK_FONT_BY_LANGUAGE = {
    "zh": "Noto Sans CJK SC",
    "zh-cn": "Noto Sans CJK SC",
    "zh-hans": "Noto Sans CJK SC",
    "zh-sg": "Noto Sans CJK SC",
    "zh-tw": "Noto Sans CJK TC",
    "zh-hant": "Noto Sans CJK TC",
    "zh-hk": "Noto Sans CJK TC",
    "ja": "Noto Sans CJK JP",
    "ko": "Noto Sans CJK KR",
}

CJK_TARGET_BY_LANGUAGE = {
    "zh": "chinese (simplified)",
    "zh-cn": "chinese (simplified)",
    "zh-hans": "chinese (simplified)",
    "zh-sg": "chinese (simplified)",
    "zh-tw": "chinese (traditional)",
    "zh-hant": "chinese (traditional)",
    "zh-hk": "chinese (traditional)",
    "ja": "japanese",
    "ko": "korean",
}

_DOCUMENT_CLASS_LINE = re.compile(
    r"^[ \t]*\\documentclass(?:\[[^\]]*\])?[ \t\r\n]*\{[^}\n]+\}"
    r"[ \t]*(?:%[^\n]*)?$",
    re.MULTILINE,
)
_PACKAGE_RE = re.compile(
    r"^(?P<indent>[ \t]*)\\usepackage(?P<options>\[[^\]]*\])?[ \t\r\n]*"
    r"\{(?P<packages>[^}\n]+)\}[ \t]*(?:%(?P<comment>[^\n]*))?$",
    re.MULTILINE,
)

# Encoding and CJK engine declarations are mutually exclusive with the pinned
# LuaHBTeX setup.  Do not remove arbitrary user packages or commands.
_CONFLICTING_PACKAGES = {
    "inputenc",
    "fontenc",
    "ctex",
    "xeCJK",
    "luatexja",
    "luatexja-fontspec",
    "luatexko",
}
_CJK_FONT_COMMAND_RE = re.compile(
    r"^[ \t]*\\(?:setmainjfont|setsansjfont|setmonojfont|setCJKmainfont|"
    r"setCJKsansfont|setCJKmonofont|setmainhangulfont|setsanshangulfont|"
    r"setmonohangulfont|setmainhanjafont|setsanshanjafont|setmonohanjafont)\b"
    r"(?:\[[^\]]*\])?[ \t\r\n]*\{[^}]*\}[ \t]*(?:%[^\n]*)?$|"
    r"^[ \t]*\\(?:newCJKfontfamily|newhangulfontfamily)\b"
    r"[ \t\r\n]*\{[^}]*\}(?:\[[^\]]*\])?[ \t\r\n]*\{[^}]*\}"
    r"(?:\[[^\]]*\])?[ \t]*(?:%[^\n]*)?$",
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


def normalize_cjk_language_code(language_code: str) -> str | None:
    """Return a supported lower-case BCP-47-ish code, or ``None``.

    This is intentionally a closed allow-list rather than accepting arbitrary
    locale tags.  It is used on user input before selecting a font or changing
    compiler metadata.
    """

    if not isinstance(language_code, str):
        return None
    normalized = language_code.strip().casefold()
    if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", normalized):
        return None
    return normalized if normalized in CJK_LANGUAGE_CODES else None


def uses_cjk(language_code: str) -> bool:
    return normalize_cjk_language_code(language_code) is not None


def expected_cjk_target(language_code: str) -> str | None:
    normalized = normalize_cjk_language_code(language_code)
    return CJK_TARGET_BY_LANGUAGE.get(normalized) if normalized else None


def cjk_font_for(language_code: str) -> str | None:
    normalized = normalize_cjk_language_code(language_code)
    return CJK_FONT_BY_LANGUAGE.get(normalized) if normalized else None


def configure_cjk_latex(latex_content: str, language_code: str) -> str:
    """Install the pinned LuaHBTeX CJK preamble while preserving user layout.

    The language-specific adapter handles script line breaking while the
    existing Latin font remains active for ASCII and a script-appropriate Noto
    CJK family handles CJK text. The function is structural and deterministic;
    it does not execute or download anything.
    """

    normalized = normalize_cjk_language_code(language_code)
    if normalized is None:
        raise ValueError("Unsupported CJK language code")
    if not _DOCUMENT_CLASS_LINE.search(latex_content):
        raise ValueError("Translated LaTeX is missing a document class")
    document_match = _DOCUMENT_BEGIN_LINE.search(latex_content)
    if document_match is None or _DOCUMENT_END_LINE.search(latex_content, document_match.end()) is None:
        raise ValueError("Translated LaTeX is missing the document environment")

    def remove_conflicting_package(match: re.Match[str]) -> str:
        packages = [part.strip() for part in match.group("packages").split(",")]
        remaining = [package for package in packages if package not in _CONFLICTING_PACKAGES]
        comment = f"%{match.group('comment')}" if match.group("comment") is not None else ""
        if not remaining:
            return comment
        if len(remaining) == len(packages):
            return match.group(0)
        return (
            f"{match.group('indent')}\\usepackage{match.group('options') or ''}"
            f"{{{','.join(remaining)}}}{comment}"
        )

    # Keep fontspec/babel/polyglossia declarations and their options intact:
    # they can carry unrelated Latin-language or font configuration.  Only
    # encoding and CJK-engine declarations are replaced because they are the
    # declarations that can select an incompatible engine/font stack.
    # Rewrite only the preamble.  A literal-looking command inside a document
    # body (including verbatim-like user content) must not be treated as a
    # package/font declaration.
    document_start = document_match.start()
    preamble = latex_content[:document_start]
    body = latex_content[document_start:]
    preamble = _PACKAGE_RE.sub(remove_conflicting_package, preamble)
    preamble = _CJK_FONT_COMMAND_RE.sub("", preamble)
    configured = preamble + body
    document_class = _DOCUMENT_CLASS_LINE.search(preamble)
    if document_class is None:  # pragma: no cover - guarded above
        raise ValueError("Translated LaTeX is missing a document class")

    font = CJK_FONT_BY_LANGUAGE[normalized]
    if normalized == "ko":
        # luatexko has dedicated Hangul/Hanja selectors and line-breaking
        # rules; luatexja is Japanese-specific and is not a Korean contract.
        setup = (
            r"\usepackage{luatexko}" + "\n"
            rf"\setmainhangulfont{{{font}}}" + "\n"
            rf"\setmainhanjafont{{{font}}}"
        )
    elif normalized.startswith("zh"):
        # ctex's LuaLaTeX adapter selects Chinese JFM punctuation/line
        # breaking. ``fontset=none`` prevents host-dependent font defaults.
        setup = r"\usepackage[fontset=none,scheme=plain]{ctex}" + "\n" + rf"\setCJKmainfont{{{font}}}"
    else:
        setup = r"\usepackage{luatexja-fontspec}" + "\n" + rf"\setmainjfont{{{font}}}"
    insertion = f"{document_class.group(0)}\n{setup}"
    configured = configured[: document_class.start()] + insertion + configured[document_class.end() :]
    return re.sub(r"\n{3,}", "\n\n", configured).strip()
