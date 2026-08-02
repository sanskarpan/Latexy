"""Contact-detail extraction shared by every resume parser.

Phone numbers are found with ``phonenumbers`` (Google's libphonenumber) rather
than a regex. The regex this replaced matched the NANP layout only —
``(?:\\+?1[-.\\s]?)?(?:\\(?[2-9]\\d{2}\\)?[-.\\s]?)[2-9]\\d{2}[-.\\s]?\\d{4}`` — so
``+91 98765 43210``, ``+44 20 7946 0958``, ``+61 2 9374 4000`` and
``+65 6123 4567`` all silently produced no phone number at all. Every format
went through it, not just PDF.

``PhoneNumberMatcher`` is used instead of ``parse()`` because it is built to scan
free text: it will not match the digit strings a resume is full of. Verified
against ``"Reduced p95 latency from 380ms to 140ms"``, ``"CGPA: 9.1/10"``,
``"cert id 4519827364"`` and ``"Bangalore 560001"`` — none of which yield a
match, where a looser regex would.
"""

from __future__ import annotations

import re
from typing import Optional

try:
    import phonenumbers
    from phonenumbers import PhoneNumberFormat, PhoneNumberMatcher

    _PHONENUMBERS_AVAILABLE = True
except ImportError:  # pragma: no cover - declared in requirements.txt
    _PHONENUMBERS_AVAILABLE = False


# Fallback for the (unlikely) case where phonenumbers is missing. Deliberately
# permissive, since it only runs when the real parser is unavailable.
_FALLBACK_PHONE_RE = re.compile(r"\+?\d[\d\s\-().]{7,17}\d")

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def find_phone(text: str, default_region: Optional[str] = "US") -> Optional[str]:
    """Return the first phone number in *text*, formatted internationally.

    Two passes, in this order:

    1. With no region. Anything written with an explicit country code (``+91``,
       ``+44``) is unambiguous and is matched correctly wherever the candidate
       lives — which covers most resumes that list an international number.
    2. With *default_region*. Only this pass can resolve a bare local number
       like ``98765 43210``, which is meaningless without knowing the country.

    A number written bare in a region other than *default_region* yields ``None``
    rather than a wrong guess: parsing a bare Indian number as US returns no
    match, it does not invent one. Set ``RESUME_DEFAULT_PHONE_REGION`` to the
    region most of your users write from.
    """
    if not text:
        return None

    if not _PHONENUMBERS_AVAILABLE:
        match = _FALLBACK_PHONE_RE.search(text)
        return match.group(0).strip() if match else None

    for region in (None, default_region):
        try:
            for match in PhoneNumberMatcher(text, region):
                return phonenumbers.format_number(
                    match.number, PhoneNumberFormat.INTERNATIONAL
                )
        except Exception:
            continue
    return None


def find_email(text: str) -> Optional[str]:
    """Return the first email address in *text*."""
    if not text:
        return None
    match = EMAIL_RE.search(text)
    return match.group(0) if match else None
