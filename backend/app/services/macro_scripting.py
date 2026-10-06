"""Small, deterministic macro scripting language.

This is deliberately *not* JavaScript or Python.  User supplied macro source is
parsed into a finite list of document-edit operations and interpreted in this
module.  There is no eval/exec, import, filesystem, network, clock, random or
process capability.  Keeping the language boring is the security boundary: a
macro can transform the supplied document, and nothing else.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

MAX_SOURCE_BYTES = 16_384
MAX_LINES = 128
MAX_INPUT_BYTES = 500_000
MAX_OUTPUT_BYTES = 500_000
MAX_TEXT_BYTES = 100_000
MAX_OPERATIONS = 128


class MacroScriptError(ValueError):
    """A user-correctable script error, safe to return to clients."""

    def __init__(self, message: str, *, line: int | None = None) -> None:
        self.line = line
        super().__init__(f"line {line}: {message}" if line is not None else message)


@dataclass(frozen=True)
class Operation:
    name: str
    args: tuple[str, ...]
    line: int


def _bounded_text(value: str, label: str, *, limit: int = MAX_TEXT_BYTES) -> str:
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in value):
        raise MacroScriptError(f"{label} contains a disallowed control character")
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise MacroScriptError(f"{label} contains invalid Unicode") from exc
    if encoded_length > limit:
        raise MacroScriptError(f"{label} exceeds {limit} bytes")
    return value


def parse_script(source: str) -> tuple[Operation, ...]:
    """Parse source without executing any user-provided language.

    Syntax (one command per line):
      prepend "text"
      append "text"
      replace "old" with "new" [all|first]
      delete-prefix <count>
      delete-suffix <count>

    Comments begin with ``#`` only when outside a quoted string.  Empty lines
    are ignored.  Unknown commands and malformed arguments fail closed.
    """
    if not isinstance(source, str):
        raise MacroScriptError("script must be a string")
    _bounded_text(source, "script", limit=MAX_SOURCE_BYTES)
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise MacroScriptError(f"script exceeds {MAX_SOURCE_BYTES} bytes")
    operations: list[Operation] = []
    for line_number, raw_line in enumerate(source.splitlines(), 1):
        if line_number > MAX_LINES:
            raise MacroScriptError(f"script exceeds {MAX_LINES} lines", line=line_number)
        try:
            lexer = shlex.shlex(raw_line, posix=True)
            lexer.whitespace_split = True
            lexer.commenters = "#"
            tokens = list(lexer)
        except ValueError as exc:
            raise MacroScriptError("malformed quoting", line=line_number) from exc
        if not tokens:
            continue
        command = tokens[0].lower()
        args = tuple(tokens[1:])
        if command in {"prepend", "append"} and len(args) == 1:
            _bounded_text(args[0], f"{command} text")
        elif command == "replace" and len(args) in (3, 4) and args[1].lower() == "with":
            if not args[0]:
                raise MacroScriptError("search text cannot be empty", line=line_number)
            _bounded_text(args[0], "search text")
            _bounded_text(args[2], "replacement text")
            if len(args) == 4 and args[3].lower() not in {"all", "first"}:
                raise MacroScriptError("replace mode must be all or first", line=line_number)
        elif command in {"delete-prefix", "delete-suffix"}:
            if len(args) != 1 or not args[0].isdigit() or int(args[0]) < 1:
                raise MacroScriptError(f"invalid {command} arguments", line=line_number)
            if int(args[0]) > MAX_INPUT_BYTES:
                raise MacroScriptError("count is too large", line=line_number)
        else:
            raise MacroScriptError(f"unsupported command {command!r}", line=line_number)
        operations.append(Operation(command, args, line_number))
        if len(operations) > MAX_OPERATIONS:
            raise MacroScriptError(f"script exceeds {MAX_OPERATIONS} operations", line=line_number)
    return tuple(operations)


def _check_size(value: str) -> str:
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise MacroScriptError("result contains invalid Unicode") from exc
    if encoded_length > MAX_OUTPUT_BYTES:
        raise MacroScriptError(f"result exceeds {MAX_OUTPUT_BYTES} bytes")
    return value


def execute_script(source: str, document: str) -> str:
    """Apply a parsed finite operation list to a document."""
    if not isinstance(document, str):
        raise MacroScriptError("document must be a string")
    try:
        encoded_length = len(document.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise MacroScriptError("document contains invalid Unicode") from exc
    if encoded_length > MAX_INPUT_BYTES:
        raise MacroScriptError(f"document exceeds {MAX_INPUT_BYTES} bytes")
    result = document
    for operation in parse_script(source):
        try:
            if operation.name == "prepend":
                result = _check_size(operation.args[0] + result)
            elif operation.name == "append":
                result = _check_size(result + operation.args[0])
            elif operation.name == "replace":
                old, _, new = operation.args[:3]
                mode = operation.args[3].lower() if len(operation.args) == 4 else "first"
                result = _check_size(result.replace(old, new, -1 if mode == "all" else 1))
            elif operation.name == "delete-prefix":
                count = int(operation.args[0])
                result = _check_size(result[count:])
            elif operation.name == "delete-suffix":
                count = int(operation.args[0])
                result = _check_size(result[:-count] if count < len(result) else "")
        except MacroScriptError:
            raise
        except Exception as exc:  # pragma: no cover - defensive fail-closed path
            raise MacroScriptError("operation failed", line=operation.line) from exc
    return result
