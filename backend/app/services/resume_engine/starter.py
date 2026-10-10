"""Literal fields in the exact shipped starter grammar, never arbitrary TeX."""

import re
import unicodedata

_LITERAL = r"(?:[^\\{}%$&#_^~\r\n\x00-\x1f]|\\[{}%$&#_])+"
_PARAGRAPH = r"(?:[^\\{}%$&#_^~\x00-\x09\x0b-\x1f]|\\[{}%$&#_])+"
_HEADER = re.compile(
    r"\A\s*\\documentclass\[11pt,a4paper\]\{article\}\s*"
    r"\\usepackage\[margin=0\.72in\]\{geometry\}\s*"
    r"\\usepackage\{enumitem\}\s*\\setlist\{nosep\}\s*"
    r"\\begin\{document\}\s*\\begin\{center\}\s*"
    r"\{\\LARGE\\textbf\{(?P<name>" + _LITERAL + r")\}\}\s*\\\\\s*"
    r"\\vspace\{1mm\}\s*(?P<label>" + _LITERAL + r")\s*\\\\\s*"
    r"(?P<contact>" + _LITERAL + r")\s*\\end\{center\}"
)
_COMMANDS = {
    "documentclass",
    "usepackage",
    "setlist",
    "begin",
    "end",
    "LARGE",
    "textbf",
    "vspace",
    "section",
    "hfill",
    "item",
}


def project_starter_fields(source: str) -> list[dict]:
    """Only exact source ranges containing plain literal text are exposed.

    A custom macro/preamble never inherits these assumptions. Whole-document
    command/environment whitelisting also blocks TeX definitions/catcodes that
    could change the meaning of an apparently familiar header command.
    """
    match = _HEADER.match(source)
    if not match or source.count(r"\begin{document}") != 1 or source.count(r"\end{document}") != 1:
        return []
    if any(command not in _COMMANDS for command in re.findall(r"\\([A-Za-z]+)", source)):
        return []
    if any(
        environment not in {"document", "center", "itemize"}
        for environment in re.findall(r"\\(?:begin|end)\{([^}]+)\}", source)
    ):
        return []
    nodes = []

    def add(kind, section, text, start, end):
        text = re.sub(r"\\([{}%$&#_])", r"\1", text)
        if (
            text.strip()
            and len(text) <= 4000
            and not any(
                unicodedata.category(c).startswith("C") and c != "\n" or unicodedata.category(c) in {"Zl", "Zp"}
                for c in text
            )
        ):
            nodes.append(
                {
                    "local_id": kind + "." + str(start),
                    "section": section,
                    "kind": "summary" if kind == "summary" else "field",
                    "text": text,
                    "start": start,
                    "end": end,
                }
            )

    for field in ("name", "label", "contact"):
        start, end = match.span(field)
        # Keep layout indentation/spacing outside the replacement span.
        raw = source[start:end]
        leading = len(raw) - len(raw.lstrip())
        add(field, "basics", raw.strip(), start + leading, end - (len(raw) - len(raw.rstrip())))
    for heading in re.finditer(r"(?m)^\\section\*?\{(Summary|Skills)\}\s*\r?\n", source[match.end() :]):
        section = heading.group(1).casefold()
        start = match.end() + heading.end()
        remainder = source[start:]
        boundary = re.search(r"(?m)^\\(?:section|end)\b", remainder)
        if not boundary:
            continue
        raw = remainder[: boundary.start()]
        if re.fullmatch(_PARAGRAPH, raw):
            leading = len(raw) - len(raw.lstrip())
            add(section, section, raw.strip(), start + leading, start + len(raw.rstrip()))
    for entry in re.finditer(
        r"(?m)^\\textbf\{(?P<title>" + _LITERAL + r")\}[ \t]*\\hfill[ \t]+(?P<dates>" + _LITERAL + r")[ \t]*$", source
    ):
        for field in ("title", "dates"):
            start, end = entry.span(field)
            raw = source[start:end]
            add(field, "experience", raw.strip(), start, end - (len(raw) - len(raw.rstrip())))
    return nodes
