"""Tests for Feature 48: ResumeResponse freshness fields."""
from datetime import datetime, timedelta, timezone

import pytest

from app.api.resume_routes import ResumeResponse


def make_response(**kwargs) -> ResumeResponse:
    defaults = dict(
        id="r1",
        user_id="u1",
        title="My Resume",
        latex_content="\\documentclass{article}",
        is_template=False,
        tags=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return ResumeResponse.model_validate(defaults)


def test_freshness_fresh():
    r = make_response(updated_at=datetime.now(timezone.utc) - timedelta(days=5))
    assert r.freshness_status == "fresh"
    assert r.days_since_updated == 5


def test_freshness_stale():
    r = make_response(updated_at=datetime.now(timezone.utc) - timedelta(days=45))
    assert r.freshness_status == "stale"
    assert r.days_since_updated == 45


def test_freshness_very_stale():
    r = make_response(updated_at=datetime.now(timezone.utc) - timedelta(days=100))
    assert r.freshness_status == "very_stale"
    assert r.days_since_updated == 100


def test_freshness_boundary_exactly_30_days():
    r = make_response(updated_at=datetime.now(timezone.utc) - timedelta(days=30))
    assert r.freshness_status == "stale"


def test_freshness_boundary_exactly_90_days():
    r = make_response(updated_at=datetime.now(timezone.utc) - timedelta(days=90))
    assert r.freshness_status == "very_stale"
