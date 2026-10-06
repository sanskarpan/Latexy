"""Closed locale contract for the built-in EuroPass/europecv template.

The ``europecv`` class ships in Debian's ``texlive-latex-extra`` (and is
therefore present in both the Modal and self-hosted images).  Its language
definitions are class options, not arbitrary TeX input.  Keep this mapping
closed so template creation cannot turn a locale value into a package option
or a file lookup.
"""

from __future__ import annotations

import re

# europecv's Debian/CTAN definitions compile under the LuaLaTeX worker for this
# closed set of EU languages plus Catalan.  The upstream locale files for
# Latvian, Slovenian, Maltese, and Dutch contain malformed legacy commands,
# while Romanian's class option calls \usepackage during option processing;
# those are rejected rather than shipping a source patch or silently falling
# back to English. Irish and Croatian definitions are absent entirely.
EUROPECV_LOCALES: dict[str, str] = {
    "bg": "bulgarian",
    "ca": "catalan",
    "cs": "czech",
    "da": "danish",
    "de": "german",
    "el": "greek",
    "en": "english",
    "es": "spanish",
    "et": "estonian",
    "fi": "finnish",
    "fr": "french",
    "hu": "hungarian",
    "it": "italian",
    "lt": "lithuanian",
    "pl": "polish",
    "pt": "portuguese",
    "sk": "slovak",
    "sv": "swedish",
}

EUROPECV_LOCALE_ALIASES = {
    **{code: code for code in EUROPECV_LOCALES},
    "fr-fr": "fr",
    "en-gb": "en",
    "en-ie": "en",
    "pt-pt": "pt",
    "pt-br": "pt",
    "el-gr": "el",
}

_CLASS_RE = re.compile(
    r"(?m)^(?P<prefix>\\documentclass(?:\[[^\]\r\n]{0,2000}\])?[ \t]*\{[^}\r\n]+\})"
    r"(?P<suffix>[ \t]*(?:%[^\r\n]*)?(?:\r?\n|$))"
)
_BABEL_ENGLISH_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)\\usepackage\[(?P<options>[^\]]*)\]\{babel\}[ \t]*(?:\r?\n|$)"
)


def normalize_europecv_locale(locale: str) -> str | None:
    """Return the canonical closed locale code, or ``None``."""

    if not isinstance(locale, str):
        return None
    value = locale.strip().casefold().replace("_", "-")
    return EUROPECV_LOCALE_ALIASES.get(value)


def is_europecv_source(latex_content: str) -> bool:
    """Recognise the real europecv class; ordinary templates are untouched."""

    return bool(re.search(r"(?m)^\s*\\documentclass(?:\[[^\]]*\])?\s*\{europecv\}", latex_content))


def configure_europecv_latex(latex_content: str, locale: str) -> tuple[str, str]:
    """Set one supported europecv class locale and force LuaLaTeX.

    Returns ``(source, compiler)``.  The rewrite changes only the class option
    list and never interpolates user data into TeX package names or commands.
    """

    normalized = normalize_europecv_locale(locale)
    if normalized is None:
        raise ValueError(f"Unsupported europecv locale: {locale!r}")
    language = EUROPECV_LOCALES[normalized]

    match = _CLASS_RE.search(latex_content)
    if not match or not re.search(r"\\documentclass(?:\[[^\]]*\])?\s*\{europecv\}", match.group(0)):
        raise ValueError("europecv source must use the europecv document class")

    options_match = re.search(r"\\documentclass\[([^\]]*)\]", match.group("prefix"))
    options = [item.strip() for item in (options_match.group(1).split(",") if options_match else []) if item.strip()]
    options = [item for item in options if item.casefold() not in set(EUROPECV_LOCALES.values())]
    options.append(language)
    class_line = re.sub(
        r"\\documentclass(?:\[[^\]]*\])?",
        lambda _match: "\\documentclass[" + ",".join(options) + "]",
        match.group("prefix"),
        count=1,
    )
    configured = latex_content[: match.start()] + class_line + match.group("suffix") + latex_content[match.end() :]

    def rewrite_babel(babel_match: re.Match[str]) -> str:
        options = {item.strip().casefold() for item in babel_match.group("options").split(",") if item.strip()}
        if "english" not in options:
            return babel_match.group(0)
        # europecv's class definition files provide the translated labels
        # themselves.  Only the Greek definition uses Babel's
        # ``\\foreignlanguage``; the other locale definitions do not need a
        # locale .ldf, and asking Babel to load one would make the template
        # depend on undeclared Debian language packages (for example
        # texlive-lang-french).  Keep the base language for those locales and
        # retain Greek's explicit dependency, which is in the image contract.
        babel_options = "english,greek" if normalized == "el" else "english"
        return f"{babel_match.group('indent')}\\usepackage[{babel_options}]{{babel}}\n"

    configured, babel_count = _BABEL_ENGLISH_RE.subn(rewrite_babel, configured, count=1)
    babel_options = "english,greek" if normalized == "el" else "english"
    if babel_count != 1 or f"\\usepackage[{babel_options}]{{babel}}" not in configured:
        raise ValueError("europecv source must load babel with an English base language")
    return configured, "lualatex"
