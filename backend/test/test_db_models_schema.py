"""
Schema-level unit tests for app.database.models.

Pure metadata assertions (no DB connection) guarding the db-models audit fixes:
FK indexes, coupon-redemption uniqueness, payments FK cascade, JSONB types,
share_token partial-index reconciliation, and the resume_settings callable default.
"""
from __future__ import annotations

from sqlalchemy.dialects.postgresql import JSONB

from app.database.models import (
    ApplicationSubmission,
    CareerAnalysis,
    CareerTransition,
    CouponRedemption,
    JobApplication,
    Optimization,
    Payment,
    RecruiterNote,
    Resume,
    ResumeComment,
    Snippet,
    TeamSeat,
    UsageAnalytics,
    UserMacro,
)


def _indexed_columns(model) -> set[str]:
    """Column names covered by a single-column index or the leading col of a composite."""
    covered: set[str] = set()
    for col in model.__table__.columns:
        if col.index:
            covered.add(col.name)
    for idx in model.__table__.indexes:
        cols = list(idx.columns)
        if cols:
            covered.add(cols[0].name)
    return covered


def test_coupon_redemption_unique_coupon_user():
    names = {c.name for c in CouponRedemption.__table__.constraints}
    assert "uq_coupon_redemptions_coupon_user" in names


def test_payments_subscription_fk_set_null_and_indexed():
    fk = next(iter(Payment.__table__.c.subscription_id.foreign_keys))
    assert fk.ondelete == "SET NULL"
    assert "subscription_id" in _indexed_columns(Payment)


def test_fk_columns_are_indexed():
    assert "member_user_id" in _indexed_columns(TeamSeat)
    assert "author_id" in _indexed_columns(RecruiterNote)
    assert "author_id" in _indexed_columns(ResumeComment)
    assert "author_id" in _indexed_columns(Snippet)
    assert "resume_id" in _indexed_columns(JobApplication)
    assert "resume_id" in _indexed_columns(ApplicationSubmission)
    assert "job_tracker_id" in _indexed_columns(ApplicationSubmission)
    assert "target_role_id" in _indexed_columns(CareerAnalysis)
    assert "to_role_id" in _indexed_columns(CareerTransition)
    assert "user_id" in _indexed_columns(UserMacro)


def test_json_columns_are_jsonb():
    assert isinstance(Optimization.__table__.c.changes_made.type, JSONB)
    assert isinstance(UsageAnalytics.__table__.c.event_metadata.type, JSONB)


def test_resume_settings_default_is_callable():
    default = Resume.__table__.c.metadata.default
    assert default is not None
    assert callable(default.arg)


def test_resume_share_token_partial_unique_index():
    idx = next(
        (i for i in Resume.__table__.indexes if i.name == "idx_resumes_share_token"),
        None,
    )
    assert idx is not None
    assert idx.unique is True
    # Column-level unique constraint should NOT exist (would drift from the partial index).
    assert Resume.__table__.c.share_token.unique in (None, False)
