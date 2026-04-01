"""
LaTeX-aware prose extractor for spell/grammar checking (Feature 35).

extract_prose(latex_content) strips LaTeX markup and returns a list of
ProseSegment objects.  Each segment records the extracted text *and* the
original line/column where that text started, so LanguageTool offsets can
be mapped back to exact Monaco positions.

Design:
  - One-pass line scanner with a lightweight state machine.
  - Preserves text inside prose-bearing commands: \\textbf{}, \\textit{},
    \\emph{}, \\underline{}, \\section{}, \\subsection{}, \\subsubsection{},
    \\chapter{}, \\title{}, \\author{}.
  - Strips inline math ($...$), display math ($$...$$, \\[...\\]),
    comments (% ...), LaTeX commands without prose content, and structural
    environments (equation, figure, table, align, tikzpicture, lstlisting).
  - Preserves plain prose lines (e.g. after \\item or in abstract/document).
"""

import re
from dataclasses import dataclass, field
from typing import List

# ── Types ───────────────────────────────────────────────────────────────────


@dataclass
class ProseSegment:
    """A contiguous span of plain-English text extracted from LaTeX source."""

    text: str
    start_line: int   # 1-indexed line in original LaTeX
    start_col: int    # 1-indexed column in original LaTeX
    prose_offset: int = field(default=0)  # absolute char offset in concatenated prose string


# ── Constants ───────────────────────────────────────────────────────────────

# Environments whose *content* should be entirely suppressed (non-prose)
_SUPPRESS_ENVS = {
    "equation", "equation*", "align", "align*", "alignat", "alignat*",
    "gather", "gather*", "multline", "multline*", "eqnarray", "eqnarray*",
    "math", "displaymath",
    "figure", "figure*", "table", "table*",
    "tikzpicture", "pgfpicture",
    "lstlisting", "verbatim", "Verbatim",
    "tabular", "tabular*", "array",
    "minipage",  # often layout, rarely pure prose
    "filecontents",
}

# Commands whose single {brace argument} is prose worth keeping
_PROSE_COMMANDS = {
    "textbf", "textit", "textsl", "textsc", "textrm", "textsf",
    "emph", "underline", "uline",
    "section", "section*", "subsection", "subsection*",
    "subsubsection", "subsubsection*", "paragraph", "paragraph*",
    "chapter", "chapter*", "title", "author", "date",
    "caption", "footnote",
    "mbox", "makebox", "fbox", "parbox",
}

# Regex: match one complete {balanced-brace} group (non-nested, fast enough for resumes)
_BRACES_RE = re.compile(r'\{([^{}]*)\}')
# Regex: strip remaining LaTeX commands that have no prose value
_CMD_RE = re.compile(r'\\[a-zA-Z@]+\*?(?:\[[^\]]*\])*(?:\{[^{}]*\})*')
# Inline math $...$ (non-greedy, stops at next $)
_INLINE_MATH_RE = re.compile(r'\$(?!\$).+?\$', re.DOTALL)
# Display math $$...$$
_DISPLAY_MATH_RE = re.compile(r'\$\$.*?\$\$', re.DOTALL)
# \[...\] display math
_BRACKET_MATH_RE = re.compile(r'\\\[.*?\\\]', re.DOTALL)
# \begin{env}...\end{env} for suppress envs (built lazily)
_ENV_PATTERN_CACHE: dict = {}


def _env_re(env: str) -> re.Pattern:
    if env not in _ENV_PATTERN_CACHE:
        escaped = re.escape(env)
        _ENV_PATTERN_CACHE[env] = re.compile(
            r'\\begin\{' + escaped + r'\*?\}.*?\\end\{' + escaped + r'\*?\}',
            re.DOTALL,
        )
    return _ENV_PATTERN_CACHE[env]


# ── Core extractor ─────────────────────────────────────────────────────────


def extract_prose(latex_content: str) -> List[ProseSegment]:
    """
    Extract plain-English prose segments from LaTeX source.

    Returns a list of ProseSegment objects sorted by start_line.
    The `prose_offset` field of each segment is set to the cumulative
    character offset in the concatenated prose string (used for back-mapping
    LanguageTool offsets to LaTeX positions).
    """
    segments: List[ProseSegment] = []
    prose_offset = 0

    lines = latex_content.split("\n")
    in_document = False
    suppress_depth = 0   # depth of suppressed environment nesting

    # For multi-line display math ($$...$$ or \[...\]) spanning multiple lines
    in_display_math = 0  # count of unclosed $$
    in_bracket_math = False

    i = 0
    while i < len(lines):
        raw_line = lines[i]
        line_no = i + 1  # 1-indexed

        # ── Preamble: skip until \begin{document} ────────────────────────
        if not in_document:
            if r"\begin{document}" in raw_line:
                in_document = True
                # Trim everything up to and including \begin{document}
                idx = raw_line.index(r"\begin{document}") + len(r"\begin{document}")
                raw_line = raw_line[idx:]
                # If nothing of interest remains on this line, move on
                if not raw_line.strip():
                    i += 1
                    continue
                # Otherwise fall through to process the remainder of this line
            else:
                i += 1
                continue

        # ── Strip comment (% not preceded by \) ───────────────────────────
        line = re.sub(r'(?<!\\)%.*$', '', raw_line)

        # ── Track display math \[...\] (multi-line) ───────────────────────
        if in_bracket_math:
            if r'\]' in line:
                in_bracket_math = False
            i += 1
            continue
        if r'\[' in line and r'\]' not in line:
            in_bracket_math = True
            i += 1
            continue

        # ── Track $$ display math (multi-line) ───────────────────────────
        dd_count = line.count('$$')
        if dd_count % 2 == 1:  # odd → toggles open/close
            if in_display_math:
                in_display_math -= 1
            else:
                in_display_math += 1
        if in_display_math:
            i += 1
            continue

        # ── \end{env} ────────────────────────────────────────────────────
        end_match = re.search(r'\\end\{([^}]+)\}', line)
        if end_match:
            env_name = end_match.group(1).rstrip('*')
            if env_name in _SUPPRESS_ENVS and suppress_depth > 0:
                suppress_depth -= 1

        # ── \begin{env} ─────────────────────────────────────────────────
        begin_match = re.search(r'\\begin\{([^}]+)\}', line)
        if begin_match:
            env_name = begin_match.group(1).rstrip('*')
            if env_name in _SUPPRESS_ENVS:
                suppress_depth += 1

        if suppress_depth > 0:
            i += 1
            continue

        # ── Strip single-line display math $$...$$ and \[...\] ───────────
        line = re.sub(r'\$\$.*?\$\$', ' ', line)
        line = re.sub(r'\\\[.*?\\\]', ' ', line)

        # ── Strip inline math $...$ ───────────────────────────────────────
        line = re.sub(r'(?<!\\)\$(?!\$).+?(?<!\\)\$', ' ', line)

        # ── Extract prose from prose-bearing commands ─────────────────────
        # e.g. \textbf{hello world} → emit "hello world" at the { position
        for cmd_match in re.finditer(r'\\(' + '|'.join(re.escape(c) for c in _PROSE_COMMANDS) + r')\*?\{([^{}]*)\}', line):
            prose_text = cmd_match.group(2).strip()
            if not prose_text:
                continue
            # column of the opening brace content
            col = raw_line.find(cmd_match.group(2), cmd_match.start())
            if col == -1:
                col = cmd_match.start(2)
            seg = ProseSegment(
                text=prose_text,
                start_line=line_no,
                start_col=col + 1,  # 1-indexed
                prose_offset=prose_offset,
            )
            segments.append(seg)
            prose_offset += len(prose_text) + 1  # +1 for space separator

        # ── Now strip all remaining commands to expose plain-prose lines ──
        stripped = re.sub(r'\\[a-zA-Z@]+\*?(?:\[[^\]]*\])*(?:\{[^{}]*\})*', ' ', line)
        # Remove remaining braces
        stripped = stripped.replace('{', ' ').replace('}', ' ')
        # Collapse whitespace
        stripped = ' '.join(stripped.split())

        if stripped and not stripped.isspace():
            # Only emit as a plain-prose segment if the line has non-command content
            # and is not just LaTeX boilerplate (heuristic: length > 3)
            if len(stripped) > 3:
                seg = ProseSegment(
                    text=stripped,
                    start_line=line_no,
                    start_col=1,
                    prose_offset=prose_offset,
                )
                segments.append(seg)
                prose_offset += len(stripped) + 1

        i += 1

    return segments


# ── Back-mapping: LT offset → LaTeX line/col ──────────────────────────────


def offset_to_latex_position(
    lt_offset: int,
    lt_length: int,
    segments: List[ProseSegment],
) -> tuple[int, int, int, int]:
    """
    Map a LanguageTool (offset, length) in the concatenated prose string
    to (start_line, start_col, end_line, end_col) in the original LaTeX.

    All returned values are 1-indexed (Monaco's coordinate system).
    Returns (1, 1, 1, 1) if the offset falls outside all segments.
    """
    if not segments:
        return (1, 1, 1, 1)

    # Binary search for the segment that contains lt_offset
    lo, hi = 0, len(segments) - 1
    seg = None
    while lo <= hi:
        mid = (lo + hi) // 2
        s = segments[mid]
        if s.prose_offset <= lt_offset < s.prose_offset + len(s.text):
            seg = s
            break
        elif lt_offset < s.prose_offset:
            hi = mid - 1
        else:
            lo = mid + 1

    if seg is None:
        return (1, 1, 1, 1)

    def _local_to_pos(local: int, seg: ProseSegment) -> tuple[int, int]:
        """Convert local offset within seg.text to (line, col) in original LaTeX."""
        prefix = seg.text[:local]
        newlines = prefix.count('\n')
        if newlines == 0:
            return seg.start_line, seg.start_col + local
        else:
            last_nl = prefix.rfind('\n')
            return seg.start_line + newlines, local - last_nl  # 1-indexed col

    local_start = lt_offset - seg.prose_offset
    local_end = min(local_start + lt_length, len(seg.text))

    start_line, start_col = _local_to_pos(local_start, seg)
    end_line, end_col = _local_to_pos(local_end, seg)

    return start_line, start_col, end_line, end_col
