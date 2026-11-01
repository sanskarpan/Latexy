"""Call-site sanitization for log sinks.

Defense for CodeQL ``py/log-injection``: wrap untrusted values interpolated
into log messages or ``extra={...}`` payloads with :func:`sanitize_for_log`
so embedded line breaks and control characters cannot forge log records.

This complements the sink-side guards in ``app.core.logging``
(``DiagnosticMessageFilter`` escapes message controls for plain-text
handlers; ``JsonFormatter`` JSON-escapes the payload): sanitizing at the
call site keeps raw control characters out of the record itself, so
``extra`` attributes and non-JSON handlers are covered too.
"""

from __future__ import annotations

import re
from typing import Any

#: Values matching this pattern contain no line breaks, control characters,
#: or anything outside a conservative printable-ASCII range, so they can be
#: logged verbatim (subject to ``max_len``).
_SAFE_LOG_VALUE = re.compile(r"[A-Za-z0-9_\-.: /=@+]*")

#: Characters that must never reach a log record raw: CR, LF, NEL, and the
#: Unicode line/paragraph separators, escaped the same way as the existing
#: audit helper in ``admin_routes._log_role_toggle``.
_LINE_BREAKS = (
    ("\r", "\\r"),
    ("\n", "\\n"),
    ("\x85", "\\x85"),
    ("\u2028", "\\u2028"),
    ("\u2029", "\\u2029"),
)


def _escape_controls(text: str) -> str:
    for raw, escaped in _LINE_BREAKS:
        text = text.replace(raw, escaped)
    # Remaining C0/C1 controls (BEL, ESC, DEL, ...) have no short escape;
    # render them as ``\\uXXXX`` so the record stays on one line, mirroring
    # ``DiagnosticMessageFilter`` in ``app.core.logging``.
    return "".join(f"\\u{ord(char):04x}" if ord(char) < 32 or 127 <= ord(char) <= 159 else char for char in text)


def sanitize_for_log(value: Any, max_len: int = 500) -> Any:
    """Return a log-safe representation of ``value``.

    - ``None``, ``bool``, ``int``, and ``float`` pass through unchanged
      (they cannot carry line breaks).
    - ``bytes`` are decoded as UTF-8 with replacement; anything else is
      stringified with ``str()`` (covers ``UUID``, exceptions, enums).
    - ``\\r``/``\\n`` (and friends) are replaced with visible safe markers;
      other control characters become ``\\uXXXX`` escapes.
    - Over-long values are truncated to ``max_len`` characters plus a
      ``...`` marker.

    The transformation is idempotent: sanitizing an already-sanitized value
    is a no-op.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    elif isinstance(value, str):
        text = value
    else:
        text = str(value)
    if _SAFE_LOG_VALUE.fullmatch(text) is not None:
        if len(text) <= max_len:
            return text
    else:
        text = _escape_controls(text)
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return text
