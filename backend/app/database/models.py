"""Database models for Latexy application."""

from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func, text

from .connection import Base


class User(Base):
    """User model for authentication and profile management."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500))
    subscription_plan: Mapped[str] = mapped_column(String(50), default="free")
    subscription_status: Mapped[str] = mapped_column(String(50), default="inactive")
    subscription_id: Mapped[Optional[str]] = mapped_column(String(255))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    email_notifications: Mapped[Optional[Dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=lambda: {"job_completed": True, "weekly_digest": False},
    )
    # GitHub integration (Feature 37)
    github_access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    github_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Dropbox integration (Feature 77)
    dropbox_access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dropbox_refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dropbox_account_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Reference manager tokens (Feature 42) — encrypted, stored as JSONB
    user_metadata: Mapped[Optional[Dict]] = mapped_column("user_metadata", JSONB, nullable=True)
    # Portfolio / public profile (Feature 67)
    public_username: Mapped[Optional[str]] = mapped_column(Text, nullable=True, unique=True)
    portfolio_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    portfolio_custom_domain: Mapped[Optional[str]] = mapped_column(Text, nullable=True, unique=True)
    portfolio_theme: Mapped[str] = mapped_column(Text, default="minimal", server_default="minimal")
    portfolio_tagline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # White-label tenancy (Feature 85)
    default_tenant_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    resumes: Mapped[List["Resume"]] = relationship("Resume", back_populates="user", cascade="all, delete-orphan")
    api_keys: Mapped[List["UserAPIKey"]] = relationship("UserAPIKey", back_populates="user", cascade="all, delete-orphan")
    developer_api_keys: Mapped[List["DeveloperAPIKey"]] = relationship(
        "DeveloperAPIKey", back_populates="user", cascade="all, delete-orphan"
    )
    compilations: Mapped[List["Compilation"]] = relationship("Compilation", back_populates="user")
    optimizations: Mapped[List["Optimization"]] = relationship("Optimization", back_populates="user")
    subscriptions: Mapped[List["Subscription"]] = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="user", cascade="all, delete-orphan")
    usage_analytics: Mapped[List["UsageAnalytics"]] = relationship("UsageAnalytics", back_populates="user")
    resume_job_matches: Mapped[List["ResumeJobMatch"]] = relationship("ResumeJobMatch", back_populates="user", cascade="all, delete-orphan")
    cover_letters: Mapped[List["CoverLetter"]] = relationship("CoverLetter", back_populates="user")
    job_applications: Mapped[List["JobApplication"]] = relationship("JobApplication", back_populates="user", cascade="all, delete-orphan")
    interview_preps: Mapped[List["InterviewPrep"]] = relationship("InterviewPrep", back_populates="user", cascade="all, delete-orphan")
    owned_team_seats: Mapped[List["TeamSeat"]] = relationship(
        "TeamSeat",
        foreign_keys="[TeamSeat.owner_user_id]",
        back_populates="owner",
        cascade="all, delete-orphan",
    )
    team_memberships: Mapped[List["TeamSeat"]] = relationship(
        "TeamSeat",
        foreign_keys="[TeamSeat.member_user_id]",
        back_populates="member",
    )

class DeviceTrial(Base):
    """Device trial tracking for freemium model."""
    __tablename__ = "device_trials"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    device_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    ip_address: Mapped[Optional[str]] = mapped_column(INET, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(255))
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class DeepAnalysisTrial(Base):
    """Trial tracking for deep analysis feature (2 free uses per device)."""
    __tablename__ = "deep_analysis_trials"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    device_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class UserAPIKey(Base):
    """User API keys for BYOK (Bring Your Own Key) functionality."""
    __tablename__ = "user_api_keys"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    key_name: Mapped[Optional[str]] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_validated: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="api_keys")


class DeveloperAPIKey(Base):
    """Developer public API keys (Feature 21)."""
    __tablename__ = "developer_api_keys"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    scopes: Mapped[List[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=lambda: ["compile", "optimize", "ats", "export"],
        server_default='{"compile","optimize","ats","export"}',
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="developer_api_keys")

class Resume(Base):
    """Resume model for storing user resumes."""
    __tablename__ = "resumes"
    __table_args__ = (
        # DB-015: composite index supports ORDER BY updated_at queries scoped to a user
        Index("idx_resumes_user_updated", "user_id", "updated_at"),
        # DB-009: matches the partial unique index created in migration 0008
        # (a plain unique=True on the column would drift from the DB definition).
        Index(
            "idx_resumes_share_token",
            "share_token",
            unique=True,
            postgresql_where=text("share_token IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    latex_content: Mapped[str] = mapped_column(Text, nullable=False)
    structured_content: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    structured_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    # Layer 3: vector embedding for semantic job matching (1536-dim OpenAI text-embedding-3-small)
    content_embedding: Mapped[Optional[List[float]]] = mapped_column(ARRAY(Float), nullable=True)
    # Per-resume settings (compiler preference, custom flags, etc.)
    # Note: "metadata" is reserved by SQLAlchemy's Declarative API, so we use
    # resume_settings as the Python attribute name while keeping the DB column "metadata".
    resume_settings: Mapped[Optional[Dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)
    selected_template_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resume_templates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content_source: Mapped[str] = mapped_column(Text, nullable=False, server_default="manual_latex", default="manual_latex")
    builder_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="detached", default="detached")
    # Shareable link token (null = not shared)
    # Uniqueness is enforced by the partial index idx_resumes_share_token (see __table_args__).
    share_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    share_token_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Variant / fork system: self-referential parent link
    parent_resume_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Soft-delete / archive (Feature from PR #185)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # GitHub sync (Feature 37)
    github_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    github_repo_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    github_last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Dropbox sync (Feature 77)
    dropbox_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    dropbox_folder_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dropbox_last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Document type — Feature 86: 'resume' | 'presentation' | 'academic_cv'
    document_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="resume", default="resume")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="resumes")
    parent: Mapped[Optional["Resume"]] = relationship(
        "Resume", remote_side="Resume.id", foreign_keys=[parent_resume_id], back_populates="variants"
    )
    variants: Mapped[List["Resume"]] = relationship(
        "Resume", back_populates="parent", foreign_keys="[Resume.parent_resume_id]"
    )
    compilations: Mapped[List["Compilation"]] = relationship("Compilation", back_populates="resume")
    optimizations: Mapped[List["Optimization"]] = relationship("Optimization", back_populates="resume", cascade="all, delete-orphan")
    cover_letters: Mapped[List["CoverLetter"]] = relationship("CoverLetter", back_populates="resume", cascade="all, delete-orphan")
    interview_preps: Mapped[List["InterviewPrep"]] = relationship("InterviewPrep", back_populates="resume", cascade="all, delete-orphan")
    # Collaboration (Feature 40)
    collaborators: Mapped[List["ResumeCollaborator"]] = relationship(
        "ResumeCollaborator",
        foreign_keys="[ResumeCollaborator.resume_id]",
        back_populates="resume",
        cascade="all, delete-orphan",
    )
    # View analytics (Feature 43)
    views: Mapped[List["ResumeView"]] = relationship(
        "ResumeView", back_populates="resume", cascade="all, delete-orphan"
    )
    selected_template: Mapped[Optional["ResumeTemplate"]] = relationship("ResumeTemplate")

class Compilation(Base):
    """Compilation history for tracking LaTeX compilations."""
    __tablename__ = "compilations"
    __table_args__ = (
        # DB-013: composite index supports queries filtering by resume filtered by status
        Index("idx_compilations_resume_status", "resume_id", "status"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    # SET NULL preserves anonymous compilation records after account deletion
    user_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    resume_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="SET NULL"), index=True)
    device_fingerprint: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    job_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    pdf_path: Mapped[Optional[str]] = mapped_column(String(500))
    compilation_time: Mapped[Optional[float]] = mapped_column(Float)
    pdf_size: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="compilations")
    resume: Mapped[Optional["Resume"]] = relationship("Resume", back_populates="compilations")

class Optimization(Base):
    """LLM optimization history."""
    __tablename__ = "optimizations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    # SET NULL preserves anonymous optimization records after account deletion
    user_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    resume_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True)
    device_fingerprint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    job_description: Mapped[str] = mapped_column(Text, nullable=False)
    original_latex: Mapped[str] = mapped_column(Text, nullable=False)
    optimized_latex: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    optimization_time: Mapped[Optional[float]] = mapped_column(Float)
    ats_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    changes_made: Mapped[Optional[dict]] = mapped_column(JSONB)
    # Layer 3: embedding of the job description used for this optimization
    job_desc_embedding: Mapped[Optional[List[float]]] = mapped_column(ARRAY(Float), nullable=True)
    # Version history / checkpoint fields
    checkpoint_label: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_checkpoint: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_auto_save: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="optimizations")
    resume: Mapped["Resume"] = relationship("Resume", back_populates="optimizations")

class ResumeJobMatch(Base):
    """Cached semantic similarity results between resumes and job descriptions."""
    __tablename__ = "resume_job_matches"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    resume_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True)
    jd_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    matched_keywords: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    missing_keywords: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    semantic_gaps: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # One cache row per (resume, jd_hash); prevents duplicate rows that would make
    # the .scalar_one_or_none() cache lookup raise MultipleResultsFound.
    __table_args__ = (
        UniqueConstraint("resume_id", "jd_hash", name="uq_resume_job_matches_resume_jd"),
    )

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="resume_job_matches")

class UsageAnalytics(Base):
    """Usage analytics for tracking user behavior."""
    __tablename__ = "usage_analytics"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    device_fingerprint: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50))
    event_metadata: Mapped[Optional[dict]] = mapped_column(JSONB)
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="usage_analytics")

class Subscription(Base):
    """Subscription management."""
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    razorpay_subscription_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    plan_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    current_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="subscriptions")
    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="subscription")

class Payment(Base):
    """Payment history."""
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # DB-006: SET NULL preserves payment history when a subscription row is deleted;
    # index backs per-subscription payment lookups.
    subscription_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True
    )
    # DB-018: nullable=True with unique=True is intentional — payments in progress have
    # no Razorpay payment ID yet; PostgreSQL unique constraints allow multiple NULL rows.
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="payments")
    subscription: Mapped[Optional["Subscription"]] = relationship("Subscription", back_populates="payments")


class TeamSeat(Base):
    """Team plan seat allocation and invitations (Feature 32)."""
    __tablename__ = "team_seats"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "member_email", name="uq_team_seats_owner_email"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    member_email: Mapped[str] = mapped_column(Text, nullable=False)
    member_user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="invited", server_default="invited")
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_user_id], back_populates="owned_team_seats")
    member: Mapped[Optional["User"]] = relationship("User", foreign_keys=[member_user_id], back_populates="team_memberships")


class CouponCode(Base):
    """Billing coupon codes (Feature 32)."""
    __tablename__ = "coupon_codes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    applicable_plans: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    max_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CouponRedemption(Base):
    """Audit trail for coupon redemptions."""
    __tablename__ = "coupon_redemptions"
    # DB-005: one redemption per (coupon, user); backs the app-level already-redeemed
    # check with a DB guarantee and prevents duplicate redemptions under a race.
    # The composite index also covers coupon_id lookups.
    __table_args__ = (
        UniqueConstraint("coupon_id", "user_id", name="uq_coupon_redemptions_coupon_user"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    coupon_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("coupon_codes.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class CoverLetter(Base):
    """Cover letter generated from a resume."""
    __tablename__ = "cover_letters"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    resume_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True)
    job_description: Mapped[Optional[str]] = mapped_column(Text)
    company_name: Mapped[Optional[str]] = mapped_column(String(255))
    role_title: Mapped[Optional[str]] = mapped_column(String(255))
    tone: Mapped[str] = mapped_column(String(50), default="formal")
    length_preference: Mapped[str] = mapped_column(String(50), default="3_paragraphs")
    latex_content: Mapped[Optional[str]] = mapped_column(Text)
    pdf_path: Mapped[Optional[str]] = mapped_column(String(500))
    generation_job_id: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="cover_letters")
    resume: Mapped["Resume"] = relationship("Resume", back_populates="cover_letters")


class FeatureFlag(Base):
    """Feature flags for independent runtime control of platform restrictions."""
    __tablename__ = "feature_flags"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class JobApplication(Base):
    """Job application tracker entry."""
    __tablename__ = "job_applications"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    role_title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="applied")
    resume_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ats_score_at_submission: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    job_description_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    company_logo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="job_applications")
    resume: Mapped[Optional["Resume"]] = relationship("Resume")


class ApplicationSubmission(Base):
    """One-click job application submission record (Feature 87)."""
    __tablename__ = "application_submissions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    resume_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True, index=True)
    job_tracker_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("job_applications.id", ondelete="SET NULL"), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(Text, nullable=False)           # 'greenhouse' | 'lever' | 'manual'
    platform_job_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    application_url: Mapped[str] = mapped_column(Text, nullable=False)
    job_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    company_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending", default="pending")
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship("User")
    resume: Mapped[Optional["Resume"]] = relationship("Resume")


class InterviewPrep(Base):
    """Interview question sets generated per resume/job."""
    __tablename__ = "interview_prep"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    resume_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True)
    job_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    questions: Mapped[List[Dict]] = mapped_column(JSONB, default=list, nullable=False, server_default='[]')
    generation_job_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="interview_preps")
    resume: Mapped["Resume"] = relationship("Resume", back_populates="interview_preps")


class ResumeTemplate(Base):
    """Global resume templates available to all users."""
    __tablename__ = "resume_templates"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), default=list)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500))
    latex_content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Document type — Feature 86: 'resume' | 'presentation' | 'academic_cv'
    document_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="resume", default="resume")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResumeCollaborator(Base):
    """Per-resume collaborator access control (Feature 40)."""

    __tablename__ = "resume_collaborators"
    __table_args__ = (
        UniqueConstraint("resume_id", "user_id", name="uq_resume_collaborators_resume_user"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 'editor' | 'commenter' | 'viewer'
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="editor")
    invited_by: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    joined_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    resume: Mapped["Resume"] = relationship(
        "Resume",
        foreign_keys=[resume_id],
        back_populates="collaborators",
    )
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    inviter: Mapped[Optional["User"]] = relationship("User", foreign_keys=[invited_by])


class ResumeView(Base):
    """Tracks views of shared resume links (Feature 43)."""
    __tablename__ = "resume_views"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    share_token: Mapped[str] = mapped_column(Text, nullable=False)
    # DB-014: index supports time-range queries on view history
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    country_code: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    referrer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # sha256(ip + ua)[:16] — never stores raw IP
    session_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    resume: Mapped["Resume"] = relationship("Resume", back_populates="views")


class Workspace(Base):
    """Team workspace for collaborative resume management (Feature 66)."""
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(String(50), nullable=False, server_default="free")
    max_members: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id])
    members: Mapped[List["WorkspaceMember"]] = relationship(
        "WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan"
    )
    workspace_resumes: Mapped[List["WorkspaceResume"]] = relationship(
        "WorkspaceResume", back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMember(Base):
    """Workspace membership with role (Feature 66)."""
    __tablename__ = "workspace_members"
    __table_args__ = (PrimaryKeyConstraint("workspace_id", "user_id"),)

    workspace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 'owner' | 'editor' | 'viewer'
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="editor")
    invited_by: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="members")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])


class WorkspaceResume(Base):
    """Resume shared into a workspace (Feature 66)."""
    __tablename__ = "workspace_resumes"
    __table_args__ = (PrimaryKeyConstraint("workspace_id", "resume_id"),)

    workspace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False
    )
    shared_by: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    shared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="workspace_resumes")
    resume: Mapped["Resume"] = relationship("Resume")


class RecruiterNote(Base):
    """Recruiter annotation on a workspace-shared resume (Feature 73)."""
    __tablename__ = "recruiter_notes"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    resume: Mapped["Resume"] = relationship("Resume")
    author: Mapped["User"] = relationship("User")


class ResumeComment(Base):
    """Inline comment on a resume, optionally scoped to a workspace (Feature 74)."""
    __tablename__ = "resume_comments"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    author_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    line_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    section_tag: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    resume: Mapped["Resume"] = relationship("Resume")
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    author: Mapped["User"] = relationship("User")


# ── Career Path Models (Feature 80) ──────────────────────────────────────────

class CareerRole(Base):
    """A node in the career progression graph."""
    __tablename__ = "career_roles"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False)  # junior|mid|senior|staff|principal|director|vp|c-suite
    industry: Mapped[str] = mapped_column(Text, nullable=False)
    required_skills: Mapped[List[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    typical_yoe_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    typical_yoe_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CareerTransition(Base):
    """A directed edge in the career progression graph."""
    __tablename__ = "career_transitions"

    from_role_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("career_roles.id", ondelete="CASCADE"), nullable=False)
    to_role_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("career_roles.id", ondelete="CASCADE"), nullable=False, index=True)
    avg_years: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    difficulty: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # easy|moderate|hard

    __table_args__ = (PrimaryKeyConstraint('from_role_id', 'to_role_id'),)


class CareerAnalysis(Base):
    """Stored career path + gap analysis for a user's resume."""
    __tablename__ = "career_analyses"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    resume_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True)
    target_role_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("career_roles.id", ondelete="SET NULL"), nullable=True, index=True)
    target_role_freetext: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_skills: Mapped[List[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    gap_skills: Mapped[List[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    path_role_ids: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    timeline_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    llm_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    target_role: Mapped[Optional["CareerRole"]] = relationship("CareerRole", foreign_keys=[target_role_id])


# ── Snippet Marketplace (Feature 82) ─────────────────────────────────────────

class Snippet(Base):
    """Community-shared LaTeX snippets."""
    __tablename__ = 'snippets'

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text('gen_random_uuid()'))
    author_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, server_default='{}')
    is_official: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='false')
    installs_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')
    upvotes_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    author: Mapped[Optional['User']] = relationship('User', foreign_keys=[author_id], lazy='selectin')
    installs: Mapped[List['SnippetInstall']] = relationship('SnippetInstall', back_populates='snippet', cascade='all, delete-orphan')
    upvotes: Mapped[List['SnippetUpvote']] = relationship('SnippetUpvote', back_populates='snippet', cascade='all, delete-orphan')


class SnippetInstall(Base):
    """Tracks which users have installed which snippets."""
    __tablename__ = 'snippet_installs'
    __table_args__ = (PrimaryKeyConstraint('snippet_id', 'user_id'),)

    snippet_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey('snippets.id', ondelete='CASCADE'), nullable=False)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    snippet: Mapped['Snippet'] = relationship('Snippet', back_populates='installs')


class SnippetUpvote(Base):
    """Tracks snippet upvotes (one per user per snippet)."""
    __tablename__ = 'snippet_upvotes'
    __table_args__ = (PrimaryKeyConstraint('snippet_id', 'user_id'),)

    snippet_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey('snippets.id', ondelete='CASCADE'), nullable=False)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    snippet: Mapped['Snippet'] = relationship('Snippet', back_populates='upvotes')


class UserMacro(Base):
    """Named keyboard macro with recorded action sequence."""
    __tablename__ = 'user_macros'

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text('gen_random_uuid()'))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    shortcut: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actions: Mapped[List] = mapped_column(JSONB, nullable=False, server_default='[]')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user: Mapped['User'] = relationship('User', foreign_keys=[user_id])


# ── White-Label Tenancy (Feature 85) ─────────────────────────────────────────

class Tenant(Base):
    """White-label tenant — agency or university career center."""
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    custom_domain: Mapped[Optional[str]] = mapped_column(Text, nullable=True, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    logo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    primary_color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="agency")
    max_members: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id])
    members: Mapped[List["TenantMember"]] = relationship("TenantMember", back_populates="tenant", cascade="all, delete-orphan")


class TenantMember(Base):
    """Membership record linking a user to a tenant."""
    __tablename__ = "tenant_members"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "user_id"),)

    tenant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="members")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])


# Create indexes for performance
Index('idx_users_email', User.email)
Index('idx_device_trials_fingerprint', DeviceTrial.device_fingerprint)
Index('idx_device_trials_ip', DeviceTrial.ip_address)
Index('idx_deep_analysis_trials_fingerprint', DeepAnalysisTrial.device_fingerprint)
Index('idx_resumes_user_id', Resume.user_id)
Index('idx_compilations_user_id', Compilation.user_id)
Index('idx_compilations_device', Compilation.device_fingerprint)
Index('idx_optimizations_user_id', Optimization.user_id)
Index('idx_optimizations_device_fp', Optimization.device_fingerprint)
Index('idx_usage_analytics_user_id', UsageAnalytics.user_id)
Index('idx_usage_analytics_device', UsageAnalytics.device_fingerprint)
Index('idx_subscriptions_user_id', Subscription.user_id)
Index('idx_rjm_resume_jd', ResumeJobMatch.resume_id, ResumeJobMatch.jd_hash)
