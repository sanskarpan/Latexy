"""Regular-expression facade that bounds every match operation."""

from __future__ import annotations

from typing import Any

import regex as _regex

_MATCH_TIMEOUT_SECONDS = 0.25
Match = _regex.Match


class Pattern:
    """Proxy a compiled regex while injecting the shared operation timeout."""

    def __init__(self, compiled: _regex.Pattern) -> None:
        self._compiled = compiled

    @property
    def pattern(self) -> str:
        return self._compiled.pattern

    @property
    def flags(self) -> int:
        return self._compiled.flags

    @property
    def groups(self) -> int:
        return self._compiled.groups

    @property
    def groupindex(self) -> dict[str, int]:
        return self._compiled.groupindex

    def search(self, string: str, *args: Any, **kwargs: Any):
        return self._compiled.search(string, *args, timeout=_MATCH_TIMEOUT_SECONDS, **kwargs)

    def match(self, string: str, *args: Any, **kwargs: Any):
        return self._compiled.match(string, *args, timeout=_MATCH_TIMEOUT_SECONDS, **kwargs)

    def fullmatch(self, string: str, *args: Any, **kwargs: Any):
        return self._compiled.fullmatch(string, *args, timeout=_MATCH_TIMEOUT_SECONDS, **kwargs)

    def findall(self, string: str, *args: Any, **kwargs: Any):
        return self._compiled.findall(string, *args, timeout=_MATCH_TIMEOUT_SECONDS, **kwargs)

    def finditer(self, string: str, *args: Any, **kwargs: Any):
        return self._compiled.finditer(string, *args, timeout=_MATCH_TIMEOUT_SECONDS, **kwargs)

    def split(self, string: str, *args: Any, **kwargs: Any):
        return self._compiled.split(string, *args, timeout=_MATCH_TIMEOUT_SECONDS, **kwargs)

    def sub(self, repl: Any, string: str, *args: Any, **kwargs: Any):
        return self._compiled.sub(repl, string, *args, timeout=_MATCH_TIMEOUT_SECONDS, **kwargs)

    def subn(self, repl: Any, string: str, *args: Any, **kwargs: Any):
        return self._compiled.subn(repl, string, *args, timeout=_MATCH_TIMEOUT_SECONDS, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._compiled, name)


def compile(pattern: str, flags: int = 0, **kwargs: Any) -> Pattern:
    return Pattern(_regex.compile(pattern, flags, **kwargs))


def search(pattern: str, string: str, flags: int = 0, **kwargs: Any):
    return _regex.search(pattern, string, flags, timeout=_MATCH_TIMEOUT_SECONDS, **kwargs)


def match(pattern: str, string: str, flags: int = 0, **kwargs: Any):
    return _regex.match(pattern, string, flags, timeout=_MATCH_TIMEOUT_SECONDS, **kwargs)


def fullmatch(pattern: str, string: str, flags: int = 0, **kwargs: Any):
    return _regex.fullmatch(pattern, string, flags, timeout=_MATCH_TIMEOUT_SECONDS, **kwargs)


def findall(pattern: str, string: str, flags: int = 0, **kwargs: Any):
    return _regex.findall(pattern, string, flags, timeout=_MATCH_TIMEOUT_SECONDS, **kwargs)


def finditer(pattern: str, string: str, flags: int = 0, **kwargs: Any):
    return _regex.finditer(pattern, string, flags, timeout=_MATCH_TIMEOUT_SECONDS, **kwargs)


def split(pattern: str, string: str, maxsplit: int = 0, flags: int = 0, **kwargs: Any):
    return _regex.split(
        pattern, string, maxsplit=maxsplit, flags=flags,
        timeout=_MATCH_TIMEOUT_SECONDS, **kwargs,
    )


def sub(
    pattern: str,
    repl: Any,
    string: str,
    count: int = 0,
    flags: int = 0,
    **kwargs: Any,
):
    return _regex.sub(
        pattern, repl, string, count=count, flags=flags,
        timeout=_MATCH_TIMEOUT_SECONDS, **kwargs,
    )


def subn(
    pattern: str,
    repl: Any,
    string: str,
    count: int = 0,
    flags: int = 0,
    **kwargs: Any,
):
    return _regex.subn(
        pattern, repl, string, count=count, flags=flags,
        timeout=_MATCH_TIMEOUT_SECONDS, **kwargs,
    )


def __getattr__(name: str) -> Any:
    """Expose compatible constants/helpers such as IGNORECASE and escape."""
    return getattr(_regex, name)

