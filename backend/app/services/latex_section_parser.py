"""
LaTeX section parser — extract and reorder \\section{} blocks.

Used by Feature 53 (AI Section Reordering) and Feature 69 (Resume Merger).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass
class LatexSection:
    name: str        # e.g. "Experience", "Skills"
    start_line: int  # 1-indexed
    end_line: int    # 1-indexed, inclusive
    content: str     # full block including the \\section{} line


# Match \\section{Name} or \\section*{Name} on a non-commented line
_SECTION_RE = re.compile(r'^[^%]*\\section\*?\{([^}]*)\}')
_END_DOC_RE = re.compile(r'\\end\{document\}')


def extract_sections(latex_content: str) -> tuple[str, List[LatexSection]]:
    """
    Split a LaTeX document into its preamble and section blocks.

    Returns:
        preamble (str): everything before the first \\section{}
        sections (List[LatexSection]): one entry per \\section{} block,
            each block ends just before the next \\section{} or \\end{document}

    If no \\section{} is found the full source is returned as preamble with an
    empty section list.
    """
    lines = latex_content.split("\n")

    # Collect (0-based line index, section name) for every \\section line
    section_starts: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m:
            section_starts.append((i, m.group(1).strip()))

    if not section_starts:
        return latex_content, []

    # Preamble = lines before the first section
    preamble = "\n".join(lines[: section_starts[0][0]])

    # Find \\end{document} (last occurrence wins)
    end_doc_idx = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if _END_DOC_RE.search(lines[i]):
            end_doc_idx = i
            break

    sections: List[LatexSection] = []
    for pos, (start_idx, name) in enumerate(section_starts):
        # The raw end is just before the next section or \\end{document}
        if pos + 1 < len(section_starts):
            raw_end = section_starts[pos + 1][0] - 1
        else:
            raw_end = end_doc_idx - 1

        # Strip trailing blank lines from the block
        while raw_end > start_idx and not lines[raw_end].strip():
            raw_end -= 1

        content = "\n".join(lines[start_idx : raw_end + 1])
        sections.append(
            LatexSection(
                name=name,
                start_line=start_idx + 1,
                end_line=raw_end + 1,
                content=content,
            )
        )

    return preamble, sections


def reorder_sections(latex_content: str, new_order: List[str]) -> str:
    """
    Reorder \\section{} blocks in *latex_content* according to *new_order*.

    - Sections listed in *new_order* appear first, in that order.
    - Sections not listed are appended afterwards in their original order.
    - The preamble and \\end{document} (+ any trailing lines) are preserved.
    - Case-insensitive name matching.

    Returns the full reconstructed LaTeX source.
    """
    preamble, sections = extract_sections(latex_content)

    if not sections:
        return latex_content

    lines = latex_content.split("\n")

    # Collect \\end{document} and any trailing lines
    end_doc_idx = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if _END_DOC_RE.search(lines[i]):
            end_doc_idx = i
            break
    trailing = "\n".join(lines[end_doc_idx:])  # "\\end{document}..."

    # Build a case-insensitive name → section lookup
    name_map: dict[str, LatexSection] = {s.name.lower(): s for s in sections}

    seen: set[str] = set()
    ordered: list[LatexSection] = []

    for name in new_order:
        key = name.lower()
        if key in name_map and key not in seen:
            ordered.append(name_map[key])
            seen.add(key)

    # Append any sections not covered by new_order
    for s in sections:
        if s.name.lower() not in seen:
            ordered.append(s)
            seen.add(s.name.lower())

    # Reconstruct: preamble + blank line + sections separated by blank lines + trailing
    body = "\n\n".join(s.content.rstrip() for s in ordered)

    parts: list[str] = []
    if preamble:
        parts.append(preamble.rstrip())
    parts.append(body)
    if trailing:
        parts.append(trailing)

    return "\n".join(parts) + "\n"
