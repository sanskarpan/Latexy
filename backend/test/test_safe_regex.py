"""Safety and compatibility tests for bounded regular expressions."""

from __future__ import annotations

import time

import pytest

from app.utils import safe_regex as re


def test_module_and_compiled_operations_remain_compatible() -> None:
    pattern = re.compile(r"(?P<word>[a-z]+)", re.IGNORECASE)
    assert pattern.search("123 Latexy").group("word") == "Latexy"
    assert pattern.findall("A b") == ["A", "b"]
    assert re.sub(r"\s+", "-", "a  b") == "a-b"
    assert re.split(r"\s+", "a  b") == ["a", "b"]


def test_catastrophic_pattern_is_interrupted() -> None:
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        re.search(r"(a|aa)+$", "a" * 100_000 + "!")
    # The regex engine enforces a 250 ms operation timeout, but wall-clock
    # scheduling can pause the process during a heavily parallel full gate.
    # Keep a generous scheduler allowance while still proving this adversarial
    # input is bounded rather than allowed to backtrack indefinitely.
    assert time.monotonic() - started < 2.0
