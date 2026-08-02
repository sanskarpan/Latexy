"""Layout-aware text reconstruction for PDF resumes.

``page.extract_text()`` flattens a page into lines of space-joined words, which
loses two things a resume depends on:

1. **Horizontal grouping.** A right-aligned date and the job title it sits beside
   arrive as ``"Senior Software Engineer, Razorpay Mar 2022 - Present"`` — one
   run of words with nothing marking where the title ends. A two-column skills
   block is worse: ``"Languages: Go, Python  Practices: Event sourcing"`` reads
   as a single sentence.
2. **Prominence.** Section headings are set in a larger or bolder font, and that
   is the most reliable signal of where a section starts. Flattened, ``SKILLS``
   is just another line.

pdfplumber already exposes everything needed — ``extract_words`` returns ``x0``,
``x1``, ``top``, ``size`` and ``fontname`` per word — so this module reconstructs
lines, splits them into cells on significant horizontal gaps, and identifies
headings by font prominence. No new dependency.

The output is still plain text: cells are joined with a separator so the LLM sees
the boundary, rather than being handed a structure it would have to be taught.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import List, Optional

from .base_parser import SECTION_PATTERNS

# Whitespace (in points) between two words that means "these belong to different
# cells" rather than "next word". Resume gutters and right-aligned date columns
# are comfortably wider than this; ordinary inter-word spacing at 9-12pt body
# text is 2-5pt.
CELL_GAP_PTS = 24.0

# Words on the same visual line never differ in `top` by more than this.
LINE_TOLERANCE_PTS = 3.0

# Cell separator in the reconstructed text. A pipe already appears in resume
# contact lines, so it reads naturally and needs no explanation in the prompt.
CELL_SEPARATOR = " | "

# A heading candidate is short. "Senior Software Engineer, Razorpay" is bold and
# larger than body text, but it is not a section heading.
MAX_HEADING_WORDS = 5


@dataclass
class LayoutLine:
    text: str
    cells: List[str]
    size: float
    bold: bool
    top: float
    x0: float
    is_heading: bool = False


@dataclass
class LayoutResult:
    text: str
    section_hints: List[str] = field(default_factory=list)
    pages: int = 0
    lines: List[LayoutLine] = field(default_factory=list)


def _split_cells(words: list) -> List[str]:
    """Split one visual line into cells wherever a wide gap appears."""
    ordered = sorted(words, key=lambda w: w["x0"])
    cells, current = [], [ordered[0]]
    for previous, word in zip(ordered, ordered[1:]):
        if word["x0"] - previous["x1"] > CELL_GAP_PTS:
            cells.append(current)
            current = [word]
        else:
            current.append(word)
    cells.append(current)
    return [" ".join(w["text"] for w in cell).strip() for cell in cells]


def _looks_like_section_heading(text: str, size: float, bold: bool, body_size: float) -> bool:
    """Whether a line is a section heading rather than prominent body text.

    Prominence alone is not enough — job titles are bold too. A heading must also
    read like one: a known section name, or a short all-caps line.
    """
    stripped = text.strip().rstrip(":").strip()
    if not stripped or len(stripped.split()) > MAX_HEADING_WORDS:
        return False

    prominent = bold or size > body_size + 0.4
    if not prominent:
        return False

    if SECTION_PATTERNS.match(stripped):
        return True
    # All-caps short lines are conventional section headings even when the exact
    # wording is not in the known vocabulary ("CORE COMPETENCIES").
    letters = [c for c in stripped if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def extract_layout_text(
    file_content: bytes, max_pages: int = 50
) -> Optional[LayoutResult]:
    """Reconstruct resume text with cell boundaries and heading detection.

    Returns ``None`` when the PDF yields no positioned words at all (a scanned
    page, or an encrypted one), so the caller can fall back to its existing path
    rather than treating an empty result as a successful parse.
    """
    import io

    import pdfplumber

    all_lines: List[LayoutLine] = []
    page_count = 0

    with pdfplumber.open(io.BytesIO(file_content)) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages[:max_pages]:
            words = page.extract_words(extra_attrs=["size", "fontname"])
            if not words:
                continue

            rows: dict = {}
            for word in words:
                key = round(word["top"] / LINE_TOLERANCE_PTS)
                rows.setdefault(key, []).append(word)

            for key in sorted(rows):
                row = rows[key]
                cells = _split_cells(row)
                if not any(cells):
                    continue
                all_lines.append(
                    LayoutLine(
                        text=CELL_SEPARATOR.join(c for c in cells if c),
                        cells=[c for c in cells if c],
                        size=max(w["size"] for w in row),
                        bold=any("Bold" in (w.get("fontname") or "") for w in row),
                        top=min(w["top"] for w in row),
                        x0=min(w["x0"] for w in row),
                    )
                )

    if not all_lines:
        return None

    body_size = statistics.median([ln.size for ln in all_lines])
    hints: List[str] = []
    for line in all_lines:
        # A heading is a single cell — a line split across columns is content.
        if len(line.cells) == 1 and _looks_like_section_heading(
            line.text, line.size, line.bold, body_size
        ):
            line.is_heading = True
            name = line.text.strip().rstrip(":").strip()
            if name.upper() not in {h.upper() for h in hints}:
                hints.append(name)

    # Blank line before each heading so section boundaries survive in plain text.
    rendered: List[str] = []
    for line in all_lines:
        if line.is_heading and rendered:
            rendered.append("")
        rendered.append(line.text)

    return LayoutResult(
        text=re.sub(r"\n{3,}", "\n\n", "\n".join(rendered)).strip(),
        section_hints=hints,
        pages=page_count,
        lines=all_lines,
    )
