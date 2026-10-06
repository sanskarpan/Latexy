"""Structured, source-aware validation diagnostics for resume documents."""

from __future__ import annotations

import re
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.nodes import MappingNode, Node, SequenceNode

_PATH_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")
_QUOTED_FIELD_RE = re.compile(r"field '([^']+)'")
_ENTRY_FIELD_RE = re.compile(r"JSON Resume '([^']+)' entry")
_UNSUPPORTED_FIELD_RE = re.compile(r"Unsupported JSON Resume field '([^']+)'")


def _path_tokens(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    for name, index in _PATH_TOKEN_RE.findall(path):
        tokens.append(int(index) if index else name)
    return tokens


def _path_string(location: tuple[Any, ...] | list[Any]) -> str:
    path = ""
    for token in location:
        if isinstance(token, int):
            path += f"[{token}]"
        elif path:
            path += f".{token}"
        else:
            path = str(token)
    return path or "$"


def locate_json_path(source: str, path: str) -> tuple[int | None, int | None]:
    """Locate a semantic JSON path using YAML's source-marked syntax tree."""
    try:
        node = yaml.compose(source)
    except yaml.YAMLError:
        return None, None
    if node is None:
        return None, None

    current: Node = node
    mark = current.start_mark
    for token in _path_tokens(path):
        if isinstance(token, str) and isinstance(current, MappingNode):
            pair = next(
                (
                    (key_node, value_node)
                    for key_node, value_node in current.value
                    if getattr(key_node, "value", None) == token
                ),
                None,
            )
            if pair is None:
                return None, None
            key_node, current = pair
            mark = key_node.start_mark
        elif isinstance(token, int) and isinstance(current, SequenceNode):
            if token < 0 or token >= len(current.value):
                return None, None
            current = current.value[token]
            mark = current.start_mark
        else:
            return None, None
    return mark.line + 1, mark.column + 1


def infer_json_resume_path(message: str) -> str:
    match = (
        _QUOTED_FIELD_RE.search(message)
        or _ENTRY_FIELD_RE.search(message)
        or _UNSUPPORTED_FIELD_RE.search(message)
    )
    if match:
        return match.group(1)
    if message.startswith("Unsupported top-level JSON Resume field(s):"):
        fields = message.partition(":")[2].strip()
        return fields.split(",", 1)[0].strip() or "$"
    return "$"


def value_error_issue(error: ValueError, source: str) -> dict[str, Any]:
    message = str(error)
    path = infer_json_resume_path(message)
    line, column = locate_json_path(source, path)
    return {"path": path, "message": message, "line": line, "column": column}


def pydantic_validation_issues(
    error: ValidationError,
    *,
    prefix: tuple[str | int, ...] = (),
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        location = (*prefix, *item.get("loc", ()))
        issues.append(
            {
                "path": _path_string(location),
                "message": str(item.get("msg") or "Invalid value"),
                "line": None,
                "column": None,
            }
        )
    return issues


def validation_error_detail(issues: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "error": {
            "code": "resume_validation_error",
            "message": "Resume data failed validation.",
            "details": {"issues": issues},
        }
    }
