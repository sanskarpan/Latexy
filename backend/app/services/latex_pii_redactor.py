"""LaTeX-safe PII redaction for anonymous resume shares.

The redacted source is a derived compile input; the saved resume is never
modified. Replacements deliberately use ASCII only so they remain valid under
pdfLaTeX as well as XeLaTeX/LuaLaTeX.
"""
import re

REDACT_PATTERNS = [
    # Email addresses
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', 'redacted@example.invalid'),
    # LinkedIn profile URLs
    (r'(?:www\.)?linkedin\.com/in/[A-Za-z0-9_%-]+', 'linkedin.com/in/redacted'),
    # GitHub profile URLs
    (r'(?:www\.)?github\.com/[A-Za-z0-9_-]+', 'github.com/redacted'),
    # International phone: +CC NNN NNN NNNN (e.g. +1 555-123-4567, +44 20 1234 5678)
    (r'\+\d{1,3}[\s\-.]?\(?\d{1,5}\)?(?:[\s\-.]?\d{2,5}){2,4}', '000-000-0000'),
    # US/CA with parenthesised area code: (NNN) NNN-NNNN
    (r'\(\d{3}\)[\s\-.]?\d{3}[\s\-.]?\d{4}', '000-000-0000'),
    # US/CA without parentheses. Separators are mandatory so years and IDs are
    # not mistaken for telephone numbers.
    (r'(?<!\d)\d{3}[\s\-.]\d{3}[\s\-.]\d{4}(?!\d)', '000-000-0000'),
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
    result = _redact_name_and_address(latex_content)
    for pattern, replacement in REDACT_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    # Inject watermark preamble immediately before \begin{document}
    if r'\SetWatermarkText{ANONYMIZED}' not in result:
        result = result.replace(
            r'\begin{document}',
            WATERMARK_PREAMBLE + r'\begin{document}',
            1,
        )
    return result


_NAME_COMMAND = re.compile(
    r"(\\(?:name|author|firstname|lastname)\s*\{)[^{}\n]{1,120}(\})",
    re.IGNORECASE,
)
_BOLD_VALUE = re.compile(r"(\\textbf\s*\{)([^{}\n]{1,120})(\})")
_ADDRESS_COMMAND = re.compile(
    r"(\\(?:address|location)\s*\{)[^{}\n]{1,200}(\})",
    re.IGNORECASE,
)
_LABELED_ADDRESS = re.compile(
    r"((?:Address|Location)\s*&\s*)[^\n]*?(?=\\\\|\n|$)",
    re.IGNORECASE,
)
_STREET_ADDRESS = re.compile(
    r"(?<!\w)\d{1,6}\s+[A-Za-z0-9 .,'-]{2,80}\s"
    r"(?:Street|St\.?|Road|Rd\.?|Avenue|Ave\.?|Lane|Ln\.?|Drive|Dr\.?|"
    r"Boulevard|Blvd\.?|Way|Court|Ct\.?)(?=\s*(?:\\quad|\\\\|$))",
    re.IGNORECASE,
)
_HEADER_LOCATION = re.compile(
    r"(?m)^([ \t]*)(?!\\)([A-Z][A-Za-z .'-]{1,60},\s*"
    r"(?:[A-Z]{2}|[A-Z][A-Za-z .'-]{2,40})(?:\s+(?:\d{4,6}(?:-\d{4})?|"
    r"[A-Z]\d[A-Z]\s?\d[A-Z]\d))?)"
    r"(?=\s*(?:\\quad|\\\\|$))"
)
_NON_NAME_LABELS = {
    "contact", "education", "experience", "professional experience",
    "professional summary", "summary", "skills", "projects", "publications",
}


def _looks_like_person_name(value: str) -> bool:
    """Conservatively identify the prominent first header value as a name."""
    plain = re.sub(r"\\[A-Za-z@*]+(?:\[[^]]*\])?", "", value)
    plain = re.sub(r"[{},]", " ", plain).strip()
    if plain.casefold() in _NON_NAME_LABELS:
        return False
    words = plain.split()
    if not 2 <= len(words) <= 6:
        return False
    return all(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ.'-]+", word) for word in words)


def _redact_name_and_address(latex_content: str) -> str:
    """Redact structured identity fields and common resume-header conventions."""
    result = _NAME_COMMAND.sub(r"\1Anonymous Candidate\2", latex_content)
    result = _ADDRESS_COMMAND.sub(r"\1Location withheld\2", result)
    result = _LABELED_ADDRESS.sub(r"\1Location withheld", result)
    result = _STREET_ADDRESS.sub("Location withheld", result)

    # Names and unlabelled city/state lines conventionally live before the first
    # resume section. Restrict heuristics to that header so employer and school
    # locations in the resume body remain useful to reviewers.
    section_match = re.search(r"\\section\*?\s*\{", result)
    boundary = section_match.start() if section_match else len(result)
    header, body = result[:boundary], result[boundary:]
    for match in _BOLD_VALUE.finditer(header):
        if _looks_like_person_name(match.group(2)):
            header = header[:match.start(2)] + "Anonymous Candidate" + header[match.end(2):]
            break
    header = _HEADER_LOCATION.sub(r"\1Location withheld", header)
    return header + body
