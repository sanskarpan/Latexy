"""Database models for Latexy application."""

from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
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
    # RBAC role (Admin Control Plane) — values: user | support | admin
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False, server_default="user")
    # Better Auth two-factor plugin state (migration 0047).
    two_factor_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    email_notifications: Mapped[Optional[Dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=lambda: {
            "job_completed": True,
            "job_failed": True,
            "share_viewed": False,
            "weekly_digest": False,
            "tracker_updates": True,
            "comment_mentions": True,
        },
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
    default_tenant_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    resumes: Mapped[List["Resume"]] = relationship("Resume", back_populates="user", cascade="all, delete-orphan")
    api_keys: Mapped[List["UserAPIKey"]] = relationship(
        "UserAPIKey", back_populates="user", cascade="all, delete-orphan"
    )
    developer_api_keys: Mapped[List["DeveloperAPIKey"]] = relationship(
        "DeveloperAPIKey", back_populates="user", cascade="all, delete-orphan"
    )
    compilations: Mapped[List["Compilation"]] = relationship("Compilation", back_populates="user")
    optimizations: Mapped[List["Optimization"]] = relationship("Optimization", back_populates="user")
    subscriptions: Mapped[List["Subscription"]] = relationship(
        "Subscription", back_populates="user", cascade="all, delete-orphan"
    )
    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="user", cascade="all, delete-orphan")
    usage_analytics: Mapped[List["UsageAnalytics"]] = relationship("UsageAnalytics", back_populates="user")
    resume_job_matches: Mapped[List["ResumeJobMatch"]] = relationship(
        "ResumeJobMatch", back_populates="user", cascade="all, delete-orphan"
    )
    cover_letters: Mapped[List["CoverLetter"]] = relationship("CoverLetter", back_populates="user")
    job_applications: Mapped[List["JobApplication"]] = relationship(
        "JobApplication", back_populates="user", cascade="all, delete-orphan"
    )
    interview_preps: Mapped[List["InterviewPrep"]] = relationship(
        "InterviewPrep", back_populates="user", cascade="all, delete-orphan"
    )
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
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
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
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
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
    content_source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="manual_latex", default="manual_latex"
    )
    builder_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="detached", default="detached")
    # Shareable link token (null = not shared)
    # Uniqueness is enforced by the partial index idx_resumes_share_token (see __table_args__).
    share_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    share_token_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Variant / fork system: self-referential parent link
    parent_resume_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # For source-linked builder variants, content remains on the parent while
    # this JSON stores only per-variant section/entry/list-item exclusions.
    variant_visibility: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
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
    # Explicit opt-in for the user's public /u/{username} portfolio. Portfolio
    # enablement alone must never reveal every non-archived resume title.
    portfolio_visible: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # Document type — Feature 86: 'resume' | 'presentation' | 'academic_cv'
    document_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="resume", default="resume")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="resumes")
    parent: Mapped[Optional["Resume"]] = relationship(
        "Resume", remote_side="Resume.id", foreign_keys=[parent_resume_id], back_populates="variants"
    )
    variants: Mapped[List["Resume"]] = relationship(
        "Resume", back_populates="parent", foreign_keys="[Resume.parent_resume_id]"
    )
    compilations: Mapped[List["Compilation"]] = relationship("Compilation", back_populates="resume")
    optimizations: Mapped[List["Optimization"]] = relationship(
        "Optimization", back_populates="resume", cascade="all, delete-orphan"
    )
    cover_letters: Mapped[List["CoverLetter"]] = relationship(
        "CoverLetter", back_populates="resume", cascade="all, delete-orphan"
    )
    interview_preps: Mapped[List["InterviewPrep"]] = relationship(
        "InterviewPrep", back_populates="resume", cascade="all, delete-orphan"
    )
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


class ResumeSuggestionDecision(Base):
    """Durable, server-authorized outcome for one suggesting-mode proposal.

    Suggestions themselves are intentionally ephemeral awareness payloads. A
    decision is different: accepting a proposal mutates the persisted resume,
    so the decision and resulting content must survive a client crash and be
    idempotently replayable by a second client. The unique resume/proposal key
    is protected by the resume row lock in the decision endpoint.
    """

    __tablename__ = "resume_suggestion_decisions"
    __table_args__ = (
        UniqueConstraint(
            "resume_id",
            "suggestion_id",
            name="uq_resume_suggestion_decisions_resume_suggestion",
        ),
        Index("ix_resume_suggestion_decisions_resume_created", "resume_id", "created_at"),
        Index(
            "ix_resume_suggestion_decisions_rate",
            "resume_id",
            "decided_by_user_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False
    )
    # Awareness ids are namespaced by provider client id. Keep this as text so
    # a reconnect cannot collide with an unrelated UUID-shaped proposal.
    suggestion_id: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Attribution must not erase the immutable decision if the actor's account
    # is later deleted. The user link is intentionally nullable/set-null.
    decided_by_user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_by_role: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # The exact post-decision content makes recent decisions replayable if the
    # browser dies after the DB transaction but before its Y.Text update. Older
    # accepted rows retain only their compact idempotency tombstone.
    result_content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Compilation(Base):
    """Compilation history for tracking LaTeX compilations."""

    __tablename__ = "compilations"
    __table_args__ = (
        # DB-013: composite index supports queries filtering by resume filtered by status
        Index("idx_compilations_resume_status", "resume_id", "status"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    # SET NULL preserves anonymous compilation records after account deletion
    user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resume_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="SET NULL"), index=True
    )
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


class JobFinalization(Base):
    """Durable cross-store arbiter for terminal job decisions.

    Redis lifecycle state is an admission/lease mechanism; this row is the
    database linearization point for terminal output.  Cleanup and workers
    lock the same row before fencing, cancelling, refunding, or committing a
    result.  Rows intentionally retain only bounded generated output metadata,
    never task arguments, credentials, or raw provider diagnostics.
    """

    __tablename__ = "job_finalizations"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_job_finalizations_job_id"),
        CheckConstraint(
            "state IN ('pending', 'committing', 'completed', 'failed', 'cancelled', 'fenced')",
            name="ck_job_finalizations_state",
        ),
        CheckConstraint("owner_epoch >= 0", name="ck_job_finalizations_owner_epoch_nonnegative"),
        CheckConstraint(
            "pdf_size IS NULL OR pdf_size BETWEEN 0 AND 20971520",
            name="ck_job_finalizations_pdf_size_bounded",
        ),
        Index("idx_job_finalizations_recovery", "state", "lease_expires_at"),
        Index("idx_job_finalizations_expiry", "expires_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Finalization payloads can contain generated résumé text. Account deletion
    # must remove that recovery payload immediately; retention GC handles rows
    # for accounts that remain active.
    user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Nullable for rows created before the durable job-type discriminator was
    # introduced; new submission paths populate it so read recovery can reject
    # a different job family without guessing from payload shape.
    job_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    compilation_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("compilations.id", ondelete="SET NULL"), nullable=True
    )
    resume_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )
    cover_letter_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cover_letters.id", ondelete="SET NULL"), nullable=True
    )
    owner_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    owner_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    terminal_result: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    result_payload: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    failure_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    pdf_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    pdf_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    pdf_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resume_apply_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    resume_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    cover_letter_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    cover_letter_apply_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentEmailDelivery(Base):
    """Durable state for a user-requested compiled-document email.

    ``accepted`` means the configured provider accepted the submission; it is
    intentionally not named ``delivered`` because inbox delivery is outside
    Latexy's control.  A stable idempotency key makes provider retries safe
    where the provider supports it, while claim fields let the worker recover
    rows abandoned by a crashed process.
    """

    __tablename__ = "document_email_deliveries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_document_email_deliveries_idempotency"),
        Index("ix_document_email_deliveries_pending", "status", "next_attempt_at", "claimed_at"),
        Index("ix_document_email_deliveries_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    resume_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    compilation_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("compilations.id", ondelete="SET NULL"), nullable=True
    )
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="pending")
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Optimization(Base):
    """LLM optimization history."""

    __tablename__ = "optimizations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    # SET NULL preserves anonymous optimization records after account deletion
    user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
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


class BulletVariantSet(Base):
    """Three reviewable rewrites of one source bullet for one job context."""

    __tablename__ = "bullet_variant_sets"
    __table_args__ = (
        UniqueConstraint(
            "resume_id",
            "source_hash",
            "job_context_hash",
            name="uq_bullet_variant_sets_resume_source_job",
        ),
        Index("ix_bullet_variant_sets_resume_created", "resume_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Store only a one-way job-description fingerprint. The display label is
    # user supplied; the potentially sensitive full posting is not retained.
    job_context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_label: Mapped[str] = mapped_column(String(200), nullable=False, server_default="General")
    options: Mapped[List[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ResumeElementVersion(Base):
    """Immutable, user-owned history for one identified resume element.

    ``element_key`` is supplied by a structured editor (for example an
    experience-entry id plus a bullet id) and is deliberately not inferred
    from text.  Text fingerprints are useful for duplicate detection, but
    changing text must never silently create a new identity.
    """

    __tablename__ = "resume_element_versions"
    __table_args__ = (
        Index("ix_resume_element_versions_resume_element_created", "resume_id", "element_key", "created_at", "id"),
        Index("ix_resume_element_versions_user_created", "user_id", "created_at"),
        Index("ix_resume_element_versions_application", "application_id"),
        Index(
            "uq_resume_element_versions_idempotency",
            "user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False
    )
    # Stable editor-owned identity; never derive this from mutable content.
    element_key: Mapped[str] = mapped_column(String(200), nullable=False)
    element_type: Mapped[str] = mapped_column(String(30), nullable=False, server_default="bullet")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_version_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resume_element_versions.id", ondelete="SET NULL"), nullable=True
    )
    root_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False, server_default="create")
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual")
    # Only bounded, user-safe provenance metadata is accepted by the API.
    provenance: Mapped[Dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # A version can be explicitly associated with a user-owned tracker entry.
    # This is evidence provenance, not an outcome attribution signal.
    application_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("job_applications.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


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
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jd_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    matched_keywords: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    missing_keywords: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    semantic_gaps: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # One cache row per (resume, jd_hash); prevents duplicate rows that would make
    # the .scalar_one_or_none() cache lookup raise MultipleResultsFound.
    __table_args__ = (UniqueConstraint("resume_id", "jd_hash", name="uq_resume_job_matches_resume_jd"),)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="resume_job_matches")


class UsageAnalytics(Base):
    """Usage analytics for tracking user behavior."""

    __tablename__ = "usage_analytics"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
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
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    razorpay_subscription_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    plan_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    current_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="subscriptions")
    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="subscription")


class Payment(Base):
    """Payment history."""

    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
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
    __table_args__ = (UniqueConstraint("owner_user_id", "member_email", name="uq_team_seats_owner_email"),)

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
    member: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[member_user_id], back_populates="team_memberships"
    )


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
    __table_args__ = (UniqueConstraint("coupon_id", "user_id", name="uq_coupon_redemptions_coupon_user"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    coupon_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("coupon_codes.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReferralIdentity(Base):
    """Opaque, user-owned referral identity for the user referral programme.

    ``code`` is a random bearer token, never derived from an email/name.  It is
    intentionally not a username or affiliate handle; the unique digest is
    used for lookup so database reads do not need to expose the link token.
    """

    __tablename__ = "referral_identities"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ReferralAttribution(Base):
    """Immutable first-touch attribution from one user to another user."""

    __tablename__ = "referral_attributions"
    __table_args__ = (
        UniqueConstraint("referred_user_id", name="uq_referral_attributions_referred_user"),
        Index("ix_referral_attributions_referrer_status", "referrer_user_id", "status"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    referral_identity_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("referral_identities.id", ondelete="RESTRICT"), nullable=False
    )
    referrer_user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    referred_user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="captured")
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    qualifying_payment_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payments.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    qualified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ReferralReward(Base):
    """Idempotent reward ledger entry for a qualifying paid event.

    The policy value is copied into the ledger at issuance so later operator
    policy changes cannot rewrite historical rewards.  ``pending`` is used
    when policy is configured but the referrer has no eligible paid plan yet.
    """

    __tablename__ = "referral_rewards"
    __table_args__ = (
        UniqueConstraint("attribution_id", name="uq_referral_rewards_attribution"),
        UniqueConstraint("qualifying_payment_id", name="uq_referral_rewards_payment"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    attribution_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("referral_attributions.id", ondelete="CASCADE"), nullable=False
    )
    referrer_user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    qualifying_payment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False
    )
    # The exact referrer's subscription term that received this extension.
    # Nullable for rewards written before the B59 hardening migration.
    subscription_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reward_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reward_value: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    period_end_before: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end_after: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CoverLetter(Base):
    """Cover letter generated from a resume."""

    __tablename__ = "cover_letters"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_description: Mapped[Optional[str]] = mapped_column(Text)
    company_name: Mapped[Optional[str]] = mapped_column(String(255))
    role_title: Mapped[Optional[str]] = mapped_column(String(255))
    tone: Mapped[str] = mapped_column(String(50), default="formal")
    length_preference: Mapped[str] = mapped_column(String(50), default="3_paragraphs")
    latex_content: Mapped[Optional[str]] = mapped_column(Text)
    pdf_path: Mapped[Optional[str]] = mapped_column(String(500))
    generation_job_id: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PlanFeature(Base):
    """Per-plan feature matrix (Admin Control Plane) — feature access on/off per pricing plan."""

    __tablename__ = "plan_features"

    plan_family: Mapped[str] = mapped_column(String(20), primary_key=True)
    feature_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class JobApplication(Base):
    """Job application tracker entry."""

    __tablename__ = "job_applications"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="job_applications")
    resume: Mapped[Optional["Resume"]] = relationship("Resume")


class SavedJob(Base):
    """A user-supplied job kept for later, before it becomes an application."""

    __tablename__ = "saved_jobs"
    __table_args__ = (Index("ix_saved_jobs_user_created", "user_id", "created_at"),)
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role_title: Mapped[str] = mapped_column(String(200), nullable=False)
    job_url: Mapped[Optional[str]] = mapped_column(String(500))
    job_description_text: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class JobAlert(Base):
    """Alert criteria supplied by a user; Latexy is not a job aggregator."""

    __tablename__ = "job_alerts"
    __table_args__ = (
        Index("ix_job_alerts_user_created", "user_id", "created_at"),
        Index(
            "ix_job_alerts_delivery",
            "active",
            "frequency",
            "last_notified_at",
            "delivery_claimed_at",
            "created_at",
        ),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query: Mapped[str] = mapped_column(String(300), nullable=False)
    company_name: Mapped[Optional[str]] = mapped_column(String(200))
    location: Mapped[Optional[str]] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="daily")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivery_claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivery_claim_token: Mapped[Optional[str]] = mapped_column(String(64))
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    delivery_last_error: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApplicationReminder(Base):
    __tablename__ = "application_reminders"
    __table_args__ = (Index("ix_application_reminders_delivery", "sent_at", "remind_at", "delivery_claimed_at"),)
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("job_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    note: Mapped[Optional[str]] = mapped_column(String(1000))
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivery_claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivery_claim_token: Mapped[Optional[str]] = mapped_column(String(64))
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    delivery_last_error: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApplicationInterview(Base):
    __tablename__ = "application_interviews"
    __table_args__ = (Index("ix_application_interviews_user_start", "user_id", "starts_at"),)
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("job_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round_name: Mapped[str] = mapped_column(String(200), nullable=False)
    interview_format: Mapped[str] = mapped_column(String(30), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, default="UTC")
    location: Mapped[Optional[str]] = mapped_column(String(500))
    interviewers: Mapped[List] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TrackerCompany(Base):
    __tablename__ = "tracker_companies"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tracker_company_user_name"),)
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    website: Mapped[Optional[str]] = mapped_column(String(500))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrackerContact(Base):
    __tablename__ = "tracker_contacts"
    __table_args__ = (Index("ix_tracker_contacts_user_name", "user_id", "name"),)
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("tracker_companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role_title: Mapped[Optional[str]] = mapped_column(String(200))
    email: Mapped[Optional[str]] = mapped_column(String(320))
    phone: Mapped[Optional[str]] = mapped_column(String(100))
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApplicationSubmission(Base):
    """One-click job application submission record (Feature 87)."""

    __tablename__ = "application_submissions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_tracker_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("job_applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    platform: Mapped[str] = mapped_column(Text, nullable=False)  # 'greenhouse' | 'lever' | 'manual'
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
    user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    questions: Mapped[List[Dict]] = mapped_column(JSONB, default=list, nullable=False, server_default="[]")
    generation_job_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

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
    __table_args__ = (UniqueConstraint("resume_id", "user_id", name="uq_resume_collaborators_resume_user"),)

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

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    share_token: Mapped[str] = mapped_column(Text, nullable=False)
    # DB-014: index supports time-range queries on view history
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
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

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
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
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="members")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])


class WorkspaceResume(Base):
    """Resume shared into a workspace (Feature 66).

    ``opened_at`` and ``downloaded_at`` are legacy names for candidate
    self-activity milestones. The write paths intentionally only update them
    when the resume owner performs the action; they are not employer/reviewer
    telemetry.
    """

    __tablename__ = "workspace_resumes"
    __table_args__ = (PrimaryKeyConstraint("workspace_id", "resume_id"),)

    workspace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shared_by: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    downloaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="workspace_resumes")
    resume: Mapped["Resume"] = relationship("Resume")


class RecruiterNote(Base):
    """Recruiter annotation on a workspace-shared resume (Feature 73)."""

    __tablename__ = "recruiter_notes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
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

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
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


class ResumeReviewComment(Base):
    """Anonymous sticky comment left through a review-capable share link.

    ``share_token_hash`` deliberately binds a comment to the exact capability
    that created it.  The raw share token is never persisted in this table and
    rotating/revoking a link therefore immediately cuts off public access.
    ``reviewer_label`` is an opaque, stable browser label (for example,
    ``Reviewer 4A91C2``), never an email, user id, or client address.
    """

    __tablename__ = "resume_review_comments"
    __table_args__ = (
        Index("ix_resume_review_comments_token", "share_token_hash", "created_at"),
        Index("ix_resume_review_comments_resume", "resume_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False
    )
    share_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer_label: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    line_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    section_tag: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Normalized coordinates in the rendered PDF page.  The API validates that
    # all three values are present together and keeps x/y in [0, 1].
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    resume: Mapped["Resume"] = relationship("Resume")


class ResumeCommentMention(Base):
    """A resolved collaborator mention with durable email delivery state."""

    __tablename__ = "resume_comment_mentions"
    __table_args__ = (UniqueConstraint("comment_id", "mentioned_user_id", name="uq_comment_mentions_comment_user"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    comment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("resume_comments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized scope lets workers and recovery jobs verify ownership without
    # trusting a comment id supplied by a client.
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mentioned_user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    delivery_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_claim_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    delivery_last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    comment: Mapped["ResumeComment"] = relationship("ResumeComment")
    resume: Mapped["Resume"] = relationship("Resume")
    mentioned_user: Mapped["User"] = relationship("User", foreign_keys=[mentioned_user_id])


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

    from_role_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("career_roles.id", ondelete="CASCADE"), nullable=False
    )
    to_role_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("career_roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    avg_years: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    difficulty: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # easy|moderate|hard

    __table_args__ = (PrimaryKeyConstraint("from_role_id", "to_role_id"),)


class CareerAnalysis(Base):
    """Stored career path + gap analysis for a user's resume."""

    __tablename__ = "career_analyses"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_role_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("career_roles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_role_freetext: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_skills: Mapped[List[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    gap_skills: Mapped[List[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    skill_taxonomy: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    skill_taxonomy_language: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    skill_taxonomy_mappings: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    path_role_ids: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    timeline_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    llm_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    target_role: Mapped[Optional["CareerRole"]] = relationship("CareerRole", foreign_keys=[target_role_id])


# ── Snippet Marketplace (Feature 82) ─────────────────────────────────────────


class Snippet(Base):
    """Community-shared LaTeX snippets."""

    __tablename__ = "snippets"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    author_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    is_official: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    installs_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    upvotes_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    author: Mapped[Optional["User"]] = relationship("User", foreign_keys=[author_id], lazy="selectin")
    installs: Mapped[List["SnippetInstall"]] = relationship(
        "SnippetInstall", back_populates="snippet", cascade="all, delete-orphan"
    )
    upvotes: Mapped[List["SnippetUpvote"]] = relationship(
        "SnippetUpvote", back_populates="snippet", cascade="all, delete-orphan"
    )


class SnippetInstall(Base):
    """Tracks which users have installed which snippets."""

    __tablename__ = "snippet_installs"
    __table_args__ = (PrimaryKeyConstraint("snippet_id", "user_id"),)

    snippet_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("snippets.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    snippet: Mapped["Snippet"] = relationship("Snippet", back_populates="installs")


class SnippetUpvote(Base):
    """Tracks snippet upvotes (one per user per snippet)."""

    __tablename__ = "snippet_upvotes"
    __table_args__ = (PrimaryKeyConstraint("snippet_id", "user_id"),)

    snippet_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("snippets.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    snippet: Mapped["Snippet"] = relationship("Snippet", back_populates="upvotes")


class UserMacro(Base):
    """Named keyboard macro with recorded action sequence."""

    __tablename__ = "user_macros"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    shortcut: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actions: Mapped[List] = mapped_column(JSONB, nullable=False, server_default="[]")
    # Oversized action payloads created before the 0052 safety cap are kept
    # for rollback/admin recovery only; normal API responses never serialize
    # this field and such macros are not executable.
    legacy_actions: Mapped[Optional[List]] = mapped_column(JSONB, nullable=True)
    # B53c intentionally stores a tiny declarative DSL, never executable
    # Python/JavaScript.  The service layer parses and executes only a finite
    # allow-list of document transformations.
    script: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    script_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    script_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])


# ── White-Label Tenancy (Feature 85) ─────────────────────────────────────────


class Tenant(Base):
    """White-label tenant — agency or university career center."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    custom_domain: Mapped[Optional[str]] = mapped_column(Text, nullable=True, unique=True)
    domain_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    logo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    primary_color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    owner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="agency")
    max_members: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id])
    members: Mapped[List["TenantMember"]] = relationship(
        "TenantMember", back_populates="tenant", cascade="all, delete-orphan"
    )


class TenantMember(Base):
    """Membership record linking a user to a tenant."""

    __tablename__ = "tenant_members"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "user_id"),)

    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="members")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])


# Create indexes for performance
Index("idx_users_email", User.email)
Index("idx_device_trials_fingerprint", DeviceTrial.device_fingerprint)
Index("idx_device_trials_ip", DeviceTrial.ip_address)
Index("idx_deep_analysis_trials_fingerprint", DeepAnalysisTrial.device_fingerprint)
Index("idx_resumes_user_id", Resume.user_id)
Index("idx_compilations_user_id", Compilation.user_id)
Index("idx_compilations_device", Compilation.device_fingerprint)
Index("idx_optimizations_user_id", Optimization.user_id)
Index("idx_optimizations_device_fp", Optimization.device_fingerprint)
Index("idx_usage_analytics_user_id", UsageAnalytics.user_id)
Index("idx_usage_analytics_device", UsageAnalytics.device_fingerprint)
Index("idx_subscriptions_user_id", Subscription.user_id)
Index("idx_rjm_resume_jd", ResumeJobMatch.resume_id, ResumeJobMatch.jd_hash)
