"""Closed, deterministic LuaHBTeX setup for mixed-script documents.

This module is intentionally narrower than a general TeX package manager.  It
accepts only the language codes that have a corresponding font/package in the
worker image and emits one fixed preamble.  Translation is the current caller;
the compiler metadata returned for a configured document is always
``lualatex``.  No caller can provide a TeX package, font family, or raw TeX
fragment through this API.

The setup supports Latin text together with one CJK profile, one or both RTL
profiles, and one Devanagari profile.  CJK, RTL, and Devanagari text which is
embedded in an otherwise Latin paragraph should use the standard
``\textarabic``/``\texthebrew``/``\texthindi`` or language-specific commands
when script selection or direction matters; the preamble alone cannot infer
paragraph boundaries from Unicode code points.  This is a deliberate,
testable limit.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .cjk_latex import CJK_FONT_BY_LANGUAGE, normalize_cjk_language_code
from .indic_latex import DEVANAGARI_FONT, DEVANAGARI_FONT_OPTIONS, DEVANAGARI_LANGUAGE_CODES
from .rtl_latex import RTL_FONT_BY_LANGUAGE, normalize_rtl_language_code

MULTILINGUAL_ENGINE = "lualatex"

# Keep aliases in one closed map.  Values are the canonical codes accepted by
# the existing CJK/RTL services.  Latin locales are intentionally absent: they
# need no generated setup and are not a route to arbitrary Babel languages.
MULTILINGUAL_LANGUAGE_ALIASES = {
    **{code: code for code in CJK_FONT_BY_LANGUAGE},
    "zh-hans": "zh-hans",
    "zh-hant": "zh-hant",
    **{code: code for code in RTL_FONT_BY_LANGUAGE},
    **{code: code for code in DEVANAGARI_LANGUAGE_CODES},
}
SUPPORTED_MULTILINGUAL_LANGUAGE_CODES = frozenset(MULTILINGUAL_LANGUAGE_ALIASES)

_DOCUMENT_CLASS_LINE = re.compile(
    r"^[ \t]*\\documentclass(?:\[[^\]]*\])?[ \t\r\n]*\{[^}\n]+\}[ \t]*(?:%[^\n]*)?(?:\n|$)",
    re.MULTILINE,
)
_DOCUMENT_BEGIN_LINE = re.compile(r"^[ \t]*\\begin\{document\}[ \t]*(?:%[^\n]*)?(?:\n|$)", re.MULTILINE)
_DOCUMENT_END_LINE = re.compile(r"^[ \t]*\\end\{document\}[ \t]*(?:%[^\n]*)?(?:\n|$)", re.MULTILINE)
_PACKAGE_LINE = re.compile(
    r"^(?P<indent>[ \t]*)\\usepackage(?P<options>\[[^\]]*\])?[ \t\r\n]*"
    r"\{(?P<packages>[^}\n]+)\}[ \t]*(?:%[^\n]*)?(?:\n|$)",
    re.MULTILINE,
)
_CONFLICTING_PACKAGES = frozenset(
    {
        "inputenc",
        "fontenc",
        "fontspec",
        "babel",
        "polyglossia",
        "bidi",
        "luabidi",
        "ctex",
        "xeCJK",
        "luatexja",
        "luatexja-fontspec",
        "luatexko",
    }
)
_CONFLICTING_COMMANDS = re.compile(
    r"^[ \t]*\\(?:setmainlanguage|setdefaultlanguage|setotherlanguage)\{[^}\n]*\}[ \t]*(?:%[^\n]*)?(?:\n|$)|"
    r"^[ \t]*\\(?:setmainfont|setsansfont|setmonofont|setmainjfont|setsansjfont|setmonojfont|"
    r"setCJKmainfont|setCJKsansfont|setCJKmonofont|setmainhangulfont|setsanshangulfont|"
    r"setmonohangulfont|setmainhanjafont|setsanshanjafont|setmonohanjafont)"
    r"(?:\[[^\]]*\])?[ \t\r\n]*\{[^}\n]*\}[ \t]*(?:%[^\n]*)?(?:\n|$)",
    re.MULTILINE,
)

_GENERATED_BLOCK = re.compile(
    r"^[ \t]*% latexy multilingual setup begin\n.*?^[ \t]*% latexy multilingual setup end[ \t]*(?:\n|$)",
    re.MULTILINE | re.DOTALL,
)


def normalize_multilingual_language_code(language_code: str) -> str | None:
    """Return a canonical supported script code, or ``None``.

    This delegates to the existing B54a/B54b allowlists so the route cannot
    accidentally grow a second, broader locale contract.
    """

    if not isinstance(language_code, str):
        return None
    normalized = language_code.strip().casefold()
    if normalized in MULTILINGUAL_LANGUAGE_ALIASES:
        return MULTILINGUAL_LANGUAGE_ALIASES[normalized]
    # Preserve the exact closed behavior of the individual services if they
    # gain an alias in the future, without accepting arbitrary BCP-47 tags.
    return normalize_cjk_language_code(normalized) or normalize_rtl_language_code(normalized)


def _canonical_codes(language_codes: str | Iterable[str]) -> tuple[str, ...]:
    if isinstance(language_codes, str):
        language_codes = (language_codes,)
    result: list[str] = []
    for language_code in language_codes:
        normalized = normalize_multilingual_language_code(language_code)
        if normalized is None:
            raise ValueError(f"Unsupported multilingual language code: {language_code!r}")
        if normalized not in result:
            result.append(normalized)
    if not result:
        raise ValueError("At least one multilingual language code is required")
    cjk_codes = [code for code in result if normalize_cjk_language_code(code)]
    if len(cjk_codes) > 1:
        raise ValueError("Only one CJK language profile may be selected per document")
    indic_codes = [code for code in result if code in DEVANAGARI_LANGUAGE_CODES]
    if len(indic_codes) > 1:
        raise ValueError("Only one Devanagari language profile may be selected per document")
    return tuple(result)


def detect_multilingual_language_codes(text: str) -> tuple[str, ...]:
    """Detect script hints without treating arbitrary text as user config.

    CJK ideographs alone do not distinguish Chinese from Japanese, so callers
    must provide the target code for those documents.  Hiragana/Katakana and
    Hangul are unambiguous and are returned as ``ja``/``ko``.  Arabic and
    Hebrew are returned separately so a document can safely register both
    profiles.  Commands and the LaTeX preamble are ignored by virtue of the
    Unicode ranges being script-specific.
    """

    if not isinstance(text, str):
        return ()
    detected: list[str] = []
    if any("\u0590" <= char <= "\u05ff" for char in text):
        detected.append("he")
    if any("\u0600" <= char <= "\u08ff" for char in text):
        detected.append("ar")
    if any("\u3040" <= char <= "\u30ff" for char in text):
        detected.append("ja")
    if any("\uac00" <= char <= "\ud7af" for char in text):
        detected.append("ko")
    if any("\u0900" <= char <= "\u097f" for char in text):
        # Devanagari does not identify Hindi versus Marathi; the explicit
        # translation target remains authoritative for that distinction.
        detected.append("hi")
    if not {"ja", "ko"}.intersection(detected) and any(
        "\u3400" <= char <= "\u4dbf" or "\u4e00" <= char <= "\u9fff" for char in text
    ):
        # The caller's explicit CJK code wins when the text is ambiguous.
        detected.append("zh")
    return tuple(detected)


def compiler_for_multilingual(language_codes: str | Iterable[str]) -> str:
    """Return the only compiler supported by this generated setup."""

    _canonical_codes(language_codes)
    return MULTILINGUAL_ENGINE


def _remove_conflicting_packages(preamble: str) -> str:
    def replace(match: re.Match[str]) -> str:
        packages = [part.strip() for part in match.group("packages").split(",")]
        remaining = [package for package in packages if package not in _CONFLICTING_PACKAGES]
        if not remaining:
            return ""
        if len(remaining) == len(packages):
            return match.group(0)
        return f"{match.group('indent')}\\usepackage{match.group('options') or ''}{{{','.join(remaining)}}}\n"

    return _PACKAGE_LINE.sub(replace, preamble)


def _setup_block(codes: tuple[str, ...]) -> str:
    cjk = next((code for code in codes if normalize_cjk_language_code(code)), None)
    rtl = [code for code in codes if normalize_rtl_language_code(code)]
    indic = [code for code in codes if code in DEVANAGARI_LANGUAGE_CODES]
    lines = ["% latexy multilingual setup begin", r"\usepackage{fontspec}"]

    # ctex/luatexja/luatexko each owns script-specific line breaking.  They
    # all coexist with fontspec, and each package/font below is fixed by the
    # closed map above.
    if cjk:
        if cjk.startswith("zh"):
            lines.extend(
                [
                    r"\usepackage[fontset=none,scheme=plain]{ctex}",
                    rf"\setCJKmainfont{{{CJK_FONT_BY_LANGUAGE[cjk]}}}",
                ]
            )
        elif cjk == "ja":
            lines.extend([r"\usepackage{luatexja-fontspec}", rf"\setmainjfont{{{CJK_FONT_BY_LANGUAGE[cjk]}}}"])
        else:  # ko
            lines.extend(
                [
                    r"\usepackage{luatexko}",
                    rf"\setmainhangulfont{{{CJK_FONT_BY_LANGUAGE[cjk]}}}",
                    rf"\setmainhanjafont{{{CJK_FONT_BY_LANGUAGE[cjk]}}}",
                ]
            )

    if rtl:
        lines.append(r"\usepackage{polyglossia}")
        # English remains the default in a mixed document so Latin/CJK layout
        # is not silently reversed. RTL blocks should use polyglossia's
        # \textarabic/\texthebrew (or language environments) for direction.
        lines.append(r"\setmainfont{Latin Modern Roman}")
        lines.append(r"\setmainlanguage{english}")
        for code in rtl:
            target = "arabic" if code == "ar" else "hebrew"
            font_command = "arabicfont" if code == "ar" else "hebrewfont"
            font = RTL_FONT_BY_LANGUAGE[code]
            lines.append(rf"\setotherlanguage{{{target}}}")
            lines.append(rf"\newfontfamily\{font_command}[Script={target.title()}]{{{font}}}")

    if indic:
        # Babel's explicit language declaration is retained for the standalone
        # Indic path (and is the same fixed HarfBuzz setup as B10).  When RTL
        # is also present, polyglossia owns language switching and the fixed
        # Devanagari family is registered there instead of loading Babel and
        # polyglossia together.
        indic_target = "hindi" if indic[0] == "hi" else "marathi"
        if rtl:
            lines.append(rf"\setotherlanguage{{{indic_target}}}")
            lines.append(rf"\newfontfamily\{indic_target}font[{DEVANAGARI_FONT_OPTIONS}]{{{DEVANAGARI_FONT}}}")
        else:
            lines.append(rf"\usepackage[english,{indic_target},provide=*]{{babel}}")
            lines.append(r"\babelprovide[onchar=ids fonts]{english}")
            lines.append(
                rf"\babelfont[{indic_target}]{{rm}}[{DEVANAGARI_FONT_OPTIONS}]{{{DEVANAGARI_FONT}}}"
            )
            lines.append(r"\babelfont[english]{rm}{Latin Modern Roman}")
            lines.append(r"\renewcommand{\bfdefault}{b}")
            lines.extend(
                (
                    r"\renewcommand{\labelitemi}{\foreignlanguage{english}{\textbullet}}",
                    r"\renewcommand{\labelitemii}{\foreignlanguage{english}{\textbullet}}",
                    r"\renewcommand{\labelitemiii}{\foreignlanguage{english}{\textbullet}}",
                    r"\renewcommand{\labelitemiv}{\foreignlanguage{english}{\textbullet}}",
                    r'\catcode"2022=\active',
                    r'\begingroup\lccode`\~="2022 \lowercase{\endgroup\def~}{\foreignlanguage{english}{\textbullet}}',
                )
            )

    lines.append("% latexy multilingual setup end")
    return "\n".join(lines)


def configure_multilingual_latex(
    latex_content: str,
    language_codes: str | Iterable[str],
) -> str:
    """Rewrite only the preamble with the pinned mixed-script setup.

    The operation is deterministic and idempotent.  It never touches body or
    verbatim text, and only removes known engine/language declarations in the
    preamble.  Existing layout and unrelated package declarations survive.
    """

    codes = _canonical_codes(language_codes)
    if not isinstance(latex_content, str) or not _DOCUMENT_CLASS_LINE.search(latex_content):
        raise ValueError("Translated LaTeX is missing a document class")
    document_match = _DOCUMENT_BEGIN_LINE.search(latex_content)
    if document_match is None or _DOCUMENT_END_LINE.search(latex_content, document_match.end()) is None:
        raise ValueError("Translated LaTeX is missing the document environment")

    preamble = latex_content[: document_match.start()]
    body = latex_content[document_match.start() :]
    preamble = _GENERATED_BLOCK.sub("", preamble)
    preamble = _remove_conflicting_packages(preamble)
    preamble = _CONFLICTING_COMMANDS.sub("", preamble)
    document_class = _DOCUMENT_CLASS_LINE.search(preamble)
    if document_class is None:  # pragma: no cover - guarded above
        raise ValueError("Translated LaTeX is missing a document class")

    insertion = f"{document_class.group(0).rstrip()}\n{_setup_block(codes)}\n"
    configured = preamble[: document_class.start()] + insertion + preamble[document_class.end() :].lstrip("\n") + body
    return re.sub(r"\n{3,}", "\n\n", configured).strip()
