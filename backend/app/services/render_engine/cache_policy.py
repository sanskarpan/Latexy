"""Conservative admission for exact-output reuse of visibly static TeX source.

This scanner is a cache optimization guard, never a security boundary or a proof
that arbitrary TeX macros/packages are deterministic. Supported resume profiles
must not introduce hidden clock/random/ambient-file dependencies.
"""
from __future__ import annotations

import re

from ..latex_service import _normalize_for_scanning

_VOLATILE = re.compile(
    r"\\(?:today|time|day|month|year|pdfcreationdate|pdfelapsedtime|elapsedtime"
    r"|pdfuniformdeviate|pdfnormaldeviate|uniformdeviate|normaldeviate|randomseed"
    r"|pdfrandomseed|pgfmathrandom|pgfmathsetseed|random|rand|input|include"
    r"|subfile|subfileinclude|InputIfFileExists|IfFileExists|includegraphics"
    r"|lstinputlisting|verbatiminput|import|subimport|directlua|latelua"
    r"|filemoddate|pdffilemoddate|pdfmdfivesum|pdfstrcmp|read|readline"
    r"|openin|openout)(?![A-Za-z@])"
)


def supports_exact_cache(source: str) -> bool:
    normalized = _normalize_for_scanning(source)
    # Unresolved dynamically generated names and TeX character expansion can
    # hide dependencies. Recompile such sources instead of guessing.
    return not ("\\csname" in normalized or "^^" in normalized or _VOLATILE.search(normalized))
