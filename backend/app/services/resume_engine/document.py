"""Snapshot projection of literal itemize bullets; never a general TeX parser.

IDs identify an immutable source snapshot, not persistent saved document nodes.
Only single-line literal bullets are editable. All other bytes remain opaque.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResumeNode:
    node_id: str
    revision: str
    section: str
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class ResumeSnapshot:
    revision: str
    source: str
    nodes: tuple[ResumeNode, ...]


def project_literal_bullets(source: str, target_sections: list[str] | None = None) -> ResumeSnapshot:
    """Project only unambiguous literal itemize bodies in a document.

    Catcodes, macro-generated itemize/item commands and verbatim can change TeX
    meaning: reject that source before any compact provider call. Escaped/special
    text, nested groups, multiline bodies and unfamiliar list environments are
    deliberately left opaque. Bounds are offsets into the original string.
    """
    revision = digest(source)
    unsupported = re.search(
        r"\\(?:catcode|def|gdef|edef|xdef|newcommand|renewcommand|providecommand|DeclareRobustCommand|newenvironment|renewenvironment|let|verb|input|include|csname)\b"
        r"|\\[A-Za-z]*(?:[Cc]ommand|[Ee]nvironment)\b"
        r"|\\begin\{(?:verbatim|lstlisting|minted)\}", source
    )
    if unsupported or source.count(r"\begin{document}") != 1 or source.count(r"\end{document}") != 1:
        return ResumeSnapshot(revision, source, ())
    selected = {s.strip().casefold() for s in target_sections or []}
    section = ""
    environments: list[str] = []
    document = False
    nodes: list[ResumeNode] = []
    lines = source.splitlines(keepends=True)
    # Precompute following nonempty lines once. Scanning a fresh suffix per
    # line makes sparse/blank large documents quadratic before admission.
    following = [""] * len(lines)
    next_text = ""
    for index in range(len(lines) - 1, -1, -1):
        following[index] = next_text
        if lines[index].strip():
            next_text = lines[index].strip()
    offset = 0
    for index, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if stripped == r"\begin{document}":
            document = True
        if stripped == r"\end{document}":
            document = False
        heading = re.fullmatch(r"\s*\\section\*?\{([A-Za-z][A-Za-z ]{0,79})\}.*", line)
        if heading and "%" not in line:
            section = heading.group(1).strip()
        begin = re.fullmatch(r"\s*\\begin\{([a-zA-Z]+)\}\s*", line)
        end = re.fullmatch(r"\s*\\end\{([a-zA-Z]+)\}\s*", line)
        if begin:
            environments.append(begin.group(1))
        elif end:
            if not environments or environments[-1] != end.group(1):
                return ResumeSnapshot(revision, source, ())
            environments.pop()
        match = re.fullmatch(r"\s*\\item[ \t]+([^\\{}%$&#_^~\x00-\x1f]+?)[ \t]*", line)
        next_nonempty = following[index]
        boundary = next_nonempty.startswith(r"\item ") or next_nonempty == r"\end{itemize}"
        if (document and environments == ["document", "itemize"] and section and match and boundary
                and (not selected or section.casefold() in selected)):
            text = match.group(1)
            if (text.strip() and len(text) <= 1000
                    and not any(unicodedata.category(char).startswith("C") or unicodedata.category(char) in {"Zl", "Zp"} for char in text)):
                start = offset + match.start(1)
                nodes.append(ResumeNode(f"bullet-{start}", digest(text), section, text, start, start + len(text)))
        offset += len(raw)
    if environments:
        return ResumeSnapshot(revision, source, ())
    return ResumeSnapshot(revision, source, tuple(nodes))
