"""Privacy-minimized parsing for one user-forwarded application-status email.

This module deliberately has no transport, mailbox, persistence, or tracker
dependencies.  Callers provide one RFC 5322 message and receive a reviewable
suggestion.  A suggestion is never an instruction to mutate a tracker card.

The parser is intentionally conservative: only unambiguous status language is
classified, and malformed messages or non-text attachments fail closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from email import policy
from email.header import decode_header
from email.parser import BytesParser, Parser
from email.utils import parseaddr
from html import unescape
from html.parser import HTMLParser
from typing import Final

# A forwarded email is a small, user-selected input.  Keeping this bound low
# also bounds MIME parsing and decoded text work for an untrusted payload.
MAX_EMAIL_BYTES: Final[int] = 1_000_000
# Explicit name for callers that want to enforce the same limit at the HTTP
# boundary before invoking this pure service.
MAX_RAW_EMAIL_BYTES: Final[int] = MAX_EMAIL_BYTES
MAX_HEADER_CHARS: Final[int] = 8_192
MAX_TEXT_CHARS: Final[int] = 200_000
MAX_MIME_PARTS: Final[int] = 40
MAX_FIELD_CHARS: Final[int] = 120


class EmailStatusParseError(ValueError):
    """Raised when a forwarded message is unsafe or cannot be parsed."""


@dataclass(frozen=True)
class StatusEvidence:
    """A privacy-minimized explanation for a status suggestion.

    ``signal`` contains a short canonical phrase, never an unbounded source
    excerpt.  The source identifies which user-provided field contained it.
    """

    signal: str
    source: str


@dataclass(frozen=True)
class EmailStatusParseResult:
    """Review-only result from :func:`parse_forwarded_application_email`."""

    status: str | None
    company: str | None
    role: str | None
    confidence: float
    evidence: tuple[StatusEvidence, ...]
    requires_review: bool = True
    company_confidence: float = 0.0
    role_confidence: float = 0.0

    @property
    def suggested_status(self) -> str | None:
        """Compatibility/readability alias for integrations."""

        return self.status

    @property
    def review_required(self) -> bool:
        return self.requires_review


@dataclass(frozen=True)
class _Signal:
    status: str
    pattern: re.Pattern[str]
    signal: str
    confidence: float


# These are deliberately phrase-based and do not attempt sentiment or fuzzy
# classification.  More-specific stages precede broad application language.
_SIGNALS: Final[tuple[_Signal, ...]] = (
    _Signal("offer", re.compile(r"\b(?:pleased|delighted|excited|happy)\s+to\s+offer\b|\boffer\s+of\s+employment\b|\b(?:we\s+are|we're)\s+offering\s+(?:you|the)\b", re.I), "offer of employment", 0.99),
    _Signal("rejected", re.compile(r"\b(?:we\s+)?(?:regret\s+to\s+inform|will\s+not\s+be\s+moving\s+forward|won't\s+be\s+moving\s+forward|have\s+decided\s+not\s+to\s+move\s+forward)\b|\bapplication\s+(?:was\s+)?(?:unsuccessful|rejected|declined)\b|\bnot\s+selected(?:\s+for)?\b|\bunable\s+to\s+offer\s+you\b|\bposition\s+has\s+been\s+filled\b", re.I), "application not selected", 0.98),
    _Signal("onsite", re.compile(r"\b(?:on[- ]site|onsite|panel)\s+(?:interview|interviewing)\b|\bfinal\s+(?:round|stage)\s+interview\b", re.I), "onsite/final interview", 0.98),
    _Signal("technical", re.compile(r"\btechnical\s+(?:interview|screen|assessment)\b", re.I), "technical interview", 0.98),
    _Signal("phone_screen", re.compile(r"\b(?:phone|telephone|recruiter)\s+screen\b|\bphone\s+interview\b", re.I), "phone screen", 0.97),
    _Signal("withdrawn", re.compile(r"\bapplication\s+(?:(?:has\s+been|was)\s+)?withdrawn\b|\bwithdraw(?:ing|n)\s+(?:your|my)\s+application\b", re.I), "application withdrawn", 0.97),
    _Signal("applied", re.compile(r"\b(?:we\s+have\s+)?received\s+(?:your|the)\s+application\b|\bthank\s+you\s+for\s+(?:applying|your\s+application)\b|\bapplication\s+successfully\s+submitted\b", re.I), "application received", 0.96),
)

_ARCHIVE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/zip",
        "application/x-7z-compressed",
        "application/x-rar-compressed",
        "application/gzip",
        "application/x-gzip",
        "application/x-tar",
        "application/x-bzip2",
        "application/x-xz",
    }
)
_ARCHIVE_SUFFIXES: Final[tuple[str, ...]] = (".zip", ".7z", ".rar", ".gz", ".tgz", ".tar", ".bz2", ".xz")
_GENERIC_SENDER_WORDS: Final[frozenset[str]] = frozenset(
    {
        "noreply",
        "no-reply",
        "do-not-reply",
        "donotreply",
        "notifications",
        "mailer",
        "mail",
        "careers",
        "recruiting",
        "recruiter",
        "recruitment",
        "hiring",
        "jobs",
        "talent",
        "team",
    }
)
_ATS_DOMAINS: Final[frozenset[str]] = frozenset(
    {"greenhouse.io", "lever.co", "ashbyhq.com", "myworkday.com", "workday.com", "icims.com", "smartrecruiters.com"}
)
_FORWARDED_SEPARATOR_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:-{2,}\s*)?(?:forwarded\s+message|original\s+message|begin\s+forwarded\s+message)(?:\s*-{2,})?\s*:?[ \t]*$",
    re.I,
)
_FORWARDED_SUBJECT_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(?:fwd?|fw)\s*:", re.I)
_INLINE_HEADER_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,79}:\s?.*$")


@dataclass(frozen=True)
class _ForwardedScope:
    subject: str
    from_header: str
    body: str
    detected: bool


def _reject(reason: str) -> None:
    # Keep the exception deliberately generic: callers can count a reason
    # without accidentally logging headers, body text, or addresses.
    raise EmailStatusParseError(reason)


def _raw_bytes(raw_email: bytes | str) -> bytes:
    if isinstance(raw_email, str):
        try:
            raw = raw_email.encode("utf-8", "strict")
        except UnicodeEncodeError:
            _reject("email text contains invalid Unicode")
    elif isinstance(raw_email, bytes):
        raw = raw_email
    else:
        _reject("email must be bytes or text")
    if not raw:
        _reject("email is empty")
    if len(raw) > MAX_EMAIL_BYTES:
        _reject("email exceeds maximum size")
    if b"\x00" in raw:
        _reject("email contains an invalid NUL byte")
    # A header/body separator is required; this avoids treating arbitrary text
    # as an email and makes malformed input fail closed.
    if b"\r\n\r\n" not in raw and b"\n\n" not in raw and b"\r\r" not in raw:
        _reject("email has no header/body separator")
    return raw


def _decode_header_value(value: object) -> str:
    if value is None:
        return ""
    raw_value = str(value)
    if len(raw_value) > MAX_HEADER_CHARS:
        _reject("email header is too long")
    chunks: list[str] = []
    try:
        pieces = decode_header(raw_value)
    except (LookupError, UnicodeError, ValueError):
        pieces = [(raw_value, None)]
    for chunk, charset in pieces:
        if isinstance(chunk, bytes):
            try:
                text = chunk.decode(charset or "ascii", "replace")
            except (LookupError, UnicodeError):
                text = chunk.decode("utf-8", "replace")
        else:
            text = str(chunk)
        chunks.append(text)
    decoded = "".join(chunks)
    # Header controls are never useful for extracting a status or identity.
    return re.sub(r"[\x00-\x1f\x7f]", " ", decoded).strip()[:MAX_HEADER_CHARS]


def _clean_text(text: str) -> str:
    text = unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t\f\v ]+", " ", text)
    text = re.sub(r"\n[ ]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_TEXT_CHARS]


def _strip_html(html: str) -> str:
    """Extract visible text without interpreting URLs or executing markup."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        # A standard-library parser is a safe fallback for minimal runtimes.
        parser = _VisibleHTMLTextParser()
        parser.feed(html)
        parser.close()
        return _clean_text("\n".join(parser.text))
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(("script", "style", "template", "noscript", "iframe", "object", "embed", "form", "svg")):
        tag.decompose()
    # get_text() reads markup only; it never dereferences src/href attributes.
    return _clean_text(soup.get_text("\n"))


class _VisibleHTMLTextParser(HTMLParser):
    """Minimal, non-fetching HTML text extractor used without BeautifulSoup."""

    _IGNORED = frozenset({"script", "style", "template", "noscript", "iframe", "object", "embed", "form", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs  # Attributes, including href/src, are never inspected.
        tag = tag.lower()
        if tag in self._IGNORED:
            self._ignored_depth += 1
        elif not self._ignored_depth and tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.text.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._IGNORED and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.text.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.text.append(data)


def _part_text(part: object) -> str:
    # Message is intentionally duck-typed here to keep this helper private and
    # independent of email.message implementation details in tests.
    payload = part.get_payload(decode=True)  # type: ignore[attr-defined]
    if payload is None:
        value = part.get_payload()  # type: ignore[attr-defined]
        if not isinstance(value, str):
            return ""
        payload = value.encode("utf-8", "replace")
    if len(payload) > MAX_EMAIL_BYTES:
        _reject("MIME part exceeds maximum size")
    charset = part.get_content_charset() or "utf-8"  # type: ignore[attr-defined]
    try:
        value = payload.decode(charset, "replace")
    except (LookupError, UnicodeError):
        value = payload.decode("utf-8", "replace")
    return _clean_text(value)


def _extract_parts(message: object) -> str:
    part_count = 0

    def _inspect(part: object) -> list[tuple[str, str]]:
        nonlocal part_count
        part_count += 1
        if part_count > MAX_MIME_PARTS:
            _reject("email contains too many MIME parts")
        content_type = (part.get_content_type() or "").lower()
        disposition = (part.get_content_disposition() or "").lower()
        filename = _decode_header_value(part.get_filename())
        filename_lower = filename.lower()
        if disposition == "attachment" or filename:
            _reject("email attachments are not accepted")
        if content_type in _ARCHIVE_TYPES or filename_lower.endswith(_ARCHIVE_SUFFIXES):
            _reject("archive MIME content is not accepted")
        if content_type == "message/rfc822" or content_type.startswith("application/"):
            _reject("non-text MIME content is not accepted")
        if part.is_multipart():
            children = part.get_payload()
            if not isinstance(children, list):
                _reject("multipart MIME content is malformed")
            child_texts: list[tuple[str, str]] = []
            for child in children:
                child_texts.extend(_inspect(child))
            if part.get_content_subtype().lower() == "alternative":
                # Alternative parts are two renderings of one message.  Pick
                # one to avoid duplicate markers/signals; still inspect every
                # child so unsafe attachments cannot hide in an unused branch.
                plain = next((item for item in child_texts if item[0] == "plain" and item[1]), None)
                if plain:
                    return [plain]
                html = next((item for item in child_texts if item[0] == "html" and item[1]), None)
                return [html] if html else []
            return child_texts
        if content_type.startswith("image/") or content_type.startswith("audio/") or content_type.startswith("video/"):
            # Inline decorative media is ignored and never fetched or decoded.
            return []
        if content_type == "text/html":
            text = _strip_html(_part_text(part))
            return [("html", text)] if text else []
        elif content_type in {"text/plain", "text/markdown"}:
            text = _part_text(part)
            return [("plain", text)] if text else []
        else:
            _reject("unsupported MIME content")

    selected = _inspect(message)
    return "\n\n".join(text for _, text in selected)[:MAX_TEXT_CHARS]


def _parse_inline_forwarded_headers(lines: list[str], start: int) -> tuple[object, int] | None:
    """Parse the one header block immediately following a forward marker."""

    index = start
    while index < len(lines) and not lines[index].strip():
        index += 1
    header_lines: list[str] = []
    header_chars = 0
    saw_header = False
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            if saw_header:
                break
            index += 1
            continue
        if line[:1].isspace() and saw_header:
            # RFC header folding is retained for Parser to decode safely.
            header_lines.append(line)
        elif _INLINE_HEADER_RE.fullmatch(line):
            saw_header = True
            header_lines.append(line)
        else:
            break
        header_chars += len(line) + 1
        if header_chars > MAX_HEADER_CHARS:
            _reject("forwarded header block is too long")
        index += 1
    if not saw_header or index >= len(lines) or lines[index].strip():
        return None
    header_text = "\n".join(header_lines) + "\n\n"
    try:
        parsed = Parser(policy=policy.default).parsestr(header_text)
    except Exception as exc:
        raise EmailStatusParseError("forwarded headers could not be parsed") from exc
    if parsed.defects:
        _reject("forwarded headers are malformed")
    if not any(key.lower() in {"from", "subject"} for key in parsed.keys()):
        return None
    return parsed, index + 1


def _forwarded_scope(outer_subject: str, body: str) -> _ForwardedScope:
    """Return original-message fields, excluding outer forwarding metadata."""

    lines = body.splitlines()
    separator_indices = [index for index, line in enumerate(lines) if _FORWARDED_SEPARATOR_RE.fullmatch(line)]
    if len(separator_indices) > 1:
        _reject("multiple forwarded message blocks are ambiguous")
    if separator_indices:
        marker_index = separator_indices[0]
        parsed_headers = _parse_inline_forwarded_headers(lines, marker_index + 1)
        if parsed_headers is None:
            _reject("forwarded message header block is malformed")
        parsed, body_start = parsed_headers
        inner_from = _decode_header_value(parsed.get("From"))
        inner_subject = _decode_header_value(parsed.get("Subject"))
        inner_body = _clean_text("\n".join(lines[body_start:]))
        return _ForwardedScope(inner_subject, inner_from, inner_body, True)

    # Some clients omit the dashed separator but retain ``Fwd:``/``FW:`` and
    # put the original RFC headers at the start of the body.
    if _FORWARDED_SUBJECT_RE.match(outer_subject):
        parsed_headers = _parse_inline_forwarded_headers(lines, 0)
        if parsed_headers is None:
            _reject("forwarded message header block is missing")
        parsed, body_start = parsed_headers
        inner_from = _decode_header_value(parsed.get("From"))
        inner_subject = _decode_header_value(parsed.get("Subject"))
        inner_body = _clean_text("\n".join(lines[body_start:]))
        return _ForwardedScope(inner_subject, inner_from, inner_body, True)

    return _ForwardedScope(outer_subject, "", body, False)


def _safe_field(value: str | None) -> str | None:
    if not value:
        return None
    value = _clean_text(value)
    if not value or len(value) > MAX_FIELD_CHARS or "@" in value or "http" in value.lower():
        return None
    if any(ord(char) < 32 for char in value):
        return None
    return value.strip(" \t-–—:|\"'“”") or None


def _extract_role(subject: str, body: str) -> tuple[str | None, float]:
    sources = ((subject, 0.88), (body, 0.76))
    patterns = (
        re.compile(r"\bapplication\s+for\s+(?:the\s+)?[\"“]?([^\n\r|]{2,100}?)[\"”]?(?:\s+(?:position|role|job))?(?:\s+(?:at|with)\b|\s*$)", re.I),
        re.compile(r"\b(?:position|role|job)\s*:\s*([^\n\r|]{2,100})", re.I),
        re.compile(r"\bfor\s+the\s+([^\n\r|]{2,100}?)\s+position\b", re.I),
    )
    for text, confidence in sources:
        for pattern in patterns:
            match = pattern.search(text)
            role = _safe_field(match.group(1)) if match else None
            if role and not re.search(r"\b(?:thank|your|application|interview|candidate)\b", role, re.I):
                return role, confidence
    return None, 0.0


def _sender_company(from_header: str) -> tuple[str | None, float]:
    display, address = parseaddr(from_header)
    display = _safe_field(display)
    address = address.strip().lower()
    domain = address.rsplit("@", 1)[-1] if "@" in address else ""
    if display:
        words = re.split(r"\s+", display)
        useful = [word for word in words if word.lower().strip("-_,") not in _GENERIC_SENDER_WORDS]
        value = _safe_field(" ".join(useful))
        if value:
            return value, 0.88
    if domain and re.fullmatch(r"[a-z0-9.-]{3,253}", domain) and domain not in _ATS_DOMAINS:
        label = domain.split(".")[0]
        if label not in _GENERIC_SENDER_WORDS and len(label) > 1:
            return label.replace("-", " ").title(), 0.58
    return None, 0.0


def _extract_company(subject: str, body: str, from_header: str) -> tuple[str | None, float]:
    company, confidence = _sender_company(from_header)
    if company:
        return company, confidence
    sources = ((subject, 0.78), (body, 0.68))
    patterns = (
        re.compile(r"\bapplication\s+for\s+[^\n\r|]{2,100}?\s+(?:at|with)\s+([A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,4})", re.I),
        re.compile(r"\bthank\s+you\s+for\s+applying\s+to\s+([A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,4})", re.I),
    )
    for text, score in sources:
        for pattern in patterns:
            match = pattern.search(text)
            value = _safe_field(match.group(1)) if match else None
            if value:
                return value, score
    return None, 0.0


def parse_forwarded_application_email(raw_email: bytes | str) -> EmailStatusParseResult:
    """Parse one forwarded RFC 5322 email into a review-only suggestion.

    No network operation is performed.  Callers should catch
    :class:`EmailStatusParseError` and expose only a generic validation error;
    its stable messages intentionally contain no input values.
    """

    raw = _raw_bytes(raw_email)
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception as exc:
        # Parser implementation exceptions are converted to a stable,
        # content-free error and are never logged here.
        raise EmailStatusParseError("email could not be parsed") from exc
    if message.defects:
        _reject("email has malformed RFC 5322/MIME structure")
    if not message.keys() or not any(
        key.lower() in {"from", "to", "subject", "date", "mime-version", "content-type"} for key in message.keys()
    ):
        _reject("email has no valid RFC 5322 headers")
    outer_subject = _decode_header_value(message.get("Subject"))
    outer_from = _decode_header_value(message.get("From"))
    outer_body = _extract_parts(message)
    scope = _forwarded_scope(outer_subject, outer_body)
    subject = scope.subject
    body = scope.body
    # The outer sender is the person who forwarded the message.  Once an
    # inline original is identified, using it as an employer would be a
    # privacy and correctness bug; only the original From may inform company.
    from_header = scope.from_header if scope.detected else outer_from
    if not subject and not body:
        _reject("email has no readable text")

    fields = (("subject", subject), ("body", body))
    matches: list[tuple[_Signal, str]] = []
    for signal in _SIGNALS:
        for source, text in fields:
            if signal.pattern.search(text):
                matches.append((signal, source))
                break
    # Contradictory high-confidence language is not safe to auto-advance.
    # Receipt language commonly appears alongside a rejection or interview
    # decision ("Thanks for applying, but ...").  It is corroboration, not a
    # contradictory state, and must not mask the stronger signal.
    if any(signal.status != "applied" for signal, _ in matches):
        matches = [(signal, source) for signal, source in matches if signal.status != "applied"]
    statuses = {signal.status for signal, _ in matches}
    evidence = tuple(StatusEvidence(signal.signal, source) for signal, source in matches)
    if len(statuses) == 1 and matches:
        signal = max(matches, key=lambda item: item[0].confidence)[0]
        confidence = signal.confidence
        status = signal.status
    else:
        status = None
        confidence = 0.0

    company, company_confidence = _extract_company(subject, body, from_header)
    role, role_confidence = _extract_role(subject, body)
    return EmailStatusParseResult(
        status=status,
        company=company,
        role=role,
        confidence=confidence,
        evidence=evidence,
        requires_review=True,
        company_confidence=company_confidence,
        role_confidence=role_confidence,
    )


# Short aliases make the boundary easy to discover without introducing a
# second implementation or a route.
parse_application_status_email = parse_forwarded_application_email
parse_forwarded_email = parse_forwarded_application_email
parse_email_status = parse_forwarded_application_email


__all__ = [
    "EmailStatusParseError",
    "EmailStatusParseResult",
    "MAX_EMAIL_BYTES",
    "MAX_RAW_EMAIL_BYTES",
    "StatusEvidence",
    "parse_email_status",
    "parse_application_status_email",
    "parse_forwarded_application_email",
    "parse_forwarded_email",
]
