"""Stable, allowlisted compile-error classes for analytics.

The database stores only the class returned by :func:`classify_compile_error`.
Raw compiler logs, error excerpts, document source and provider diagnostics
never leave the worker through this module.

Signals come from the existing compile/finalization paths:

* ``Compilation.error_message`` (the first ``!`` LaTeX line or a bounded
  worker message),
* ``JobFinalization.failure_code`` / terminal ``error_code`` values, and
* the terminal result payload produced by the LaTeX workers.

The classifier is deliberately conservative: a failure that does not match a
known signal becomes ``unknown`` instead of being forced into a class.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Mapping, Optional


class CompileErrorClass(StrEnum):
    """Persisted compile-error classes. The string values are the DB values."""

    SYNTAX = "syntax"
    MISSING_PACKAGE = "missing_package"
    TIMEOUT = "timeout"
    ENGINE = "engine"
    STORAGE = "storage"
    PDF_LIMIT = "pdf_limit"
    UNKNOWN = "unknown"


COMPILE_ERROR_CLASSES: tuple[str, ...] = tuple(item.value for item in CompileErrorClass)
ALLOWED_COMPILE_ERROR_CLASSES = frozenset(COMPILE_ERROR_CLASSES)
DEFAULT_COMPILE_ERROR_CLASS = CompileErrorClass.UNKNOWN.value

# Finalization codes are the strongest signal because they are emitted by the
# terminal arbiter rather than parsed from free text.
_FINALIZATION_CODE_CLASSES: dict[str, str] = {
    "compile_timeout": CompileErrorClass.TIMEOUT.value,
    "timeout": CompileErrorClass.TIMEOUT.value,
    "job_timeout": CompileErrorClass.TIMEOUT.value,
    "task_timeout": CompileErrorClass.TIMEOUT.value,
    "dispatch_timeout": CompileErrorClass.TIMEOUT.value,
    "lease_timeout": CompileErrorClass.TIMEOUT.value,
    "pdf_storage_failure": CompileErrorClass.STORAGE.value,
    "storage_failure": CompileErrorClass.STORAGE.value,
    "artifact_storage_failure": CompileErrorClass.STORAGE.value,
    "upload_failed": CompileErrorClass.STORAGE.value,
    "pdf_too_large": CompileErrorClass.PDF_LIMIT.value,
    "pdf_limit_exceeded": CompileErrorClass.PDF_LIMIT.value,
    "page_limit_exceeded": CompileErrorClass.PDF_LIMIT.value,
    "engine_read_escape": CompileErrorClass.ENGINE.value,
    "render_pass_failed": CompileErrorClass.ENGINE.value,
    "render_failed": CompileErrorClass.ENGINE.value,
    "renderer_failed": CompileErrorClass.ENGINE.value,
    "modal_engine_unavailable": CompileErrorClass.ENGINE.value,
    "engine_unavailable": CompileErrorClass.ENGINE.value,
    "engine_failed": CompileErrorClass.ENGINE.value,
    "engine_error": CompileErrorClass.ENGINE.value,
    "docker_unavailable": CompileErrorClass.ENGINE.value,
    "worker_failed": CompileErrorClass.UNKNOWN.value,
    "job_failed": CompileErrorClass.UNKNOWN.value,
    "internal": CompileErrorClass.UNKNOWN.value,
    "latex_error": CompileErrorClass.UNKNOWN.value,
}

# Order matters: explicit infrastructure failures win over generic "!" text.
_MESSAGE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        CompileErrorClass.TIMEOUT.value,
        re.compile(
            r"\b(?:compile[_ -]?timeout|timed?\s*out|timeout|time limit|"
            r"deadline exceeded|softtimelimit(?:exceeded)?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        CompileErrorClass.PDF_LIMIT.value,
        re.compile(
            r"\b(?:pdf[_ -]?too[_ -]?large|pdf\b[^\n]{0,80}\b(?:too large|size limit|"
            r"byte limit|exceeds|limit)|exceeds\b[^\n]{0,80}\bpdf|"
            r"page limit|too many pages|maximum\b[^\n]{0,40}\bpages)\b",
            re.IGNORECASE,
        ),
    ),
    (
        CompileErrorClass.STORAGE.value,
        re.compile(
            r"\b(?:pdf[_ -]?storage[_ -]?failure|storage failure|storage failed|"
            r"failed to (?:upload|store)|could not be durably stored|object storage|"
            r"artifact bytes unavailable|minio|s3|bucket|no space left|disk full|"
            r"read-only file system|upload (?:failed|error))\b",
            re.IGNORECASE,
        ),
    ),
    (
        CompileErrorClass.MISSING_PACKAGE.value,
        re.compile(
            r"(?:\bfile\b[^\n]{0,200}\bnot found|"
            r"\bi can't find file\b|"
            r"\bfont\b[^\n]{0,160}\b(?:not found|cannot be found|not loadable)|"
            r"\bpackage\b[^\n]{0,160}\b(?:not found|cannot be found|not installed|missing)|"
            r"\bmissing package\b|"
            r"\b(?:sty|cls|def|cfg|clo|bbx|cbx|lbx|bst)\b[^\n]{0,120}\bnot found|"
            r"\bkpathsea\b[^\n]{0,120}\bmktex)",
            re.IGNORECASE,
        ),
    ),
    (
        CompileErrorClass.ENGINE.value,
        re.compile(
            r"\b(?:engine[_ -]?read[_ -]?escape|render(?:er)?[_ -]?(?:pass|engine)?"
            r"[_ -]?(?:failed|failure|error|unavailable|crashed)|modal(?: engine)?"
            r"[_ -]?(?:unavailable|failed)|docker[^\n]{0,80}\b(?:unavailable|failed)|"
            r"container[^\n]{0,80}\b(?:failed|error|crashed)|sandbox[^\n]{0,80}"
            r"\b(?:failed|error|unavailable)|process[^\n]{0,80}\b(?:failed|crashed|killed)|"
            r"segmentation fault|signal \d+|out of memory|exited with code|"
            r"compilation process (?:failed|crashed)|dispatch did not|"
            r"worker (?:failed|crashed)|command not found|auxiliary artifacts? "
            r"(?:invalid|unavailable))\b",
            re.IGNORECASE,
        ),
    ),
    (
        CompileErrorClass.SYNTAX.value,
        re.compile(
            r"(?:^\s*!|"
            r"\b(?:undefined control sequence|missing \$ inserted|extra \}|missing \}|"
            r"missing \\begin|missing \\documentclass|invalid latex|"
            r"disallowed (?:file|shell)|misplaced|paragraph ended before|runaway argument|"
            r"illegal unit|missing number|double superscript|double subscript|"
            r"bad math environment delimiter|closing brace|unexpected token|"
            r"emergency stop|latex error|option clash for package|"
            r"command [^\n]{0,80} already defined|no room for a new)\b)",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
)


def normalize_compile_error_class(value: Any) -> str:
    """Return an allowlisted class, or ``unknown`` for anything else."""
    candidate = value.value if isinstance(value, CompileErrorClass) else value
    text = str(candidate or "").strip().lower()
    return text if text in ALLOWED_COMPILE_ERROR_CLASSES else DEFAULT_COMPILE_ERROR_CLASS


def _terminal_message(terminal_result: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(terminal_result, Mapping):
        return ""
    parts = [
        terminal_result.get("error"),
        terminal_result.get("error_message"),
        terminal_result.get("latex_error_line"),
    ]
    return "\n".join(str(part) for part in parts if part)


def classify_compile_error(
    error_message: Optional[str] = None,
    *,
    failure_code: Optional[str] = None,
    error_code: Optional[str] = None,
    terminal_result: Optional[Mapping[str, Any]] = None,
) -> str:
    """Classify a failed compile using only bounded worker signals.

    ``error_code``/``failure_code`` take precedence over free text because the
    finalization arbiter emits them from typed terminal decisions. The returned
    value is always one of :data:`COMPILE_ERROR_CLASSES`.
    """

    terminal_code = None
    if isinstance(terminal_result, Mapping):
        terminal_code = terminal_result.get("error_code") or terminal_result.get("failure_code")
    for code in (error_code, terminal_code, failure_code):
        normalized_code = str(code or "").strip().lower()
        mapped = _FINALIZATION_CODE_CLASSES.get(normalized_code)
        # Generic codes such as ``latex_error`` and ``worker_failed`` carry no
        # class by themselves; inspect the bounded message before falling back.
        if mapped is not None and mapped != DEFAULT_COMPILE_ERROR_CLASS:
            return mapped

    signal = "\n".join(part for part in (error_message or "", _terminal_message(terminal_result)) if part).strip()
    if not signal:
        return DEFAULT_COMPILE_ERROR_CLASS

    for error_class, pattern in _MESSAGE_RULES:
        if pattern.search(signal):
            return error_class
    return DEFAULT_COMPILE_ERROR_CLASS


# Descriptive alias used by worker call sites that classify a whole terminal
# result rather than a single message.
classify_compile_failure = classify_compile_error


__all__ = [
    "ALLOWED_COMPILE_ERROR_CLASSES",
    "COMPILE_ERROR_CLASSES",
    "CompileErrorClass",
    "DEFAULT_COMPILE_ERROR_CLASS",
    "classify_compile_error",
    "classify_compile_failure",
    "normalize_compile_error_class",
]
