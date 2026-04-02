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
    # Conservative phone: 7+ digit groups with common separators
    (r'\+?[\d][\d\s\-().]{6,14}[\d]', '███-████-████'),
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
    Injects a draftwatermark after \\begin{document}.
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
