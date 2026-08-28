"""Regression coverage for production template asset generation (#1689)."""

import pytest

from app.scripts.compile_templates import _raise_if_failed


def test_asset_backfill_accepts_a_clean_batch():
    _raise_if_failed(0)


def test_asset_backfill_fails_the_caller_when_any_template_fails():
    with pytest.raises(
        RuntimeError,
        match=r"template asset generation failed for 2 template\(s\)",
    ):
        _raise_if_failed(2)
