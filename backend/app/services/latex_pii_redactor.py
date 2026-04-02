"""
PII Redactor for LaTeX resumes (Feature 47).
Applies regex-based redaction to email, phone, LinkedIn, and GitHub
occurrences in LaTeX source. The original LaTeX is never modified —
this is applied at compile-time for anonymous share view only.
"""
import re

# ── Redaction patterns ─────────────────────────────────────────────────────

REDACT_PATTERNS = [
    # Email addresses
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', '████@████'),
    # LinkedIn profile URLs
    (r'linkedin\.com/in/[A-Za-z0-9_%-]+', 'linkedin.com/in/████'),
    # GitHub profile URLs
    (r'github\.com/[A-Za-z0-9_-]+', 'github.com/████'),
    # International phone: +CC NNN NNN NNNN (e.g. +1 555-123-4567, +44 20 1234 5678)
    (r'\+\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}', '███-████-████'),
    # US/CA with parenthesised area code: (NNN) NNN-NNNN
    (r'\(\d{3}\)[\s\-.]?\d{3}[\s\-.]?\d{4}', '███-████-████'),
]

WATERMARK_PREAMBLE = r"""
\usepackage{draftwatermark}
\SetWatermarkText{ANONYMIZED}
\SetWatermarkScale{0.8}
\SetWatermarkColor[gray]{0.93}
"""


def redact(latex_content: str) -> str:
    """
    Return a copy of *latex_content* with PII replaced by block characters.
    Injects a draftwatermark preamble before \\begin{document}.
    The input string is never mutated.
    """
    result = latex_content
    for pattern, replacement in REDACT_PATTERNS:
        result = re.sub(pattern, replacement, result)
    # Inject watermark preamble immediately before \begin{document}
    result = result.replace(
        r'\begin{document}',
        WATERMARK_PREAMBLE + r'\begin{document}',
        1,  # only first occurrence
    )
    return result
