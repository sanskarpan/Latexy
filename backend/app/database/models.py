"""Database models for Latexy application."""

from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func, text

from .connection import Base


class ResumePdfImport(Base):
    """Private original attachment, outside hot document/render queries."""
    __tablename__ = "resume_pdf_imports"
    __table_args__ = (
        CheckConstraint("size_bytes > 0 AND size_bytes <= 10485760", name="ck_pdf_import_size"),
        CheckConstraint("octet_length(original_pdf) = size_bytes", name="ck_pdf_import_bytes"),
        CheckConstraint("octet_length(structured_seed::text) <= 1048576", name="ck_pdf_import_seed"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resume_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=True, unique=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    original_pdf: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    structured_seed: Mapped[dict] = mapped_column(JSONB, nullable=False)
    extraction_status: Mapped[str] = mapped_column(String(16), nullable=False)
    adaptation_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ResumeOptimizationRun(Base):
    """Owner-scoped, expiring candidate snapshot and hard run budget."""
    __tablename__ = "resume_optimization_runs"
    __table_args__ = (
        CheckConstraint("base_revision > 0", name="ck_optimization_run_revision"),
        CheckConstraint("effort IN ('quick','standard','deep')", name="ck_optimization_run_effort"),
        CheckConstraint("status IN ('running','completed','partial','failed','cancelled')", name="ck_optimization_run_status"),
        Index("ix_optimization_runs_owner_resume", "user_id", "resume_id", "created_at"),
        Index("ix_optimization_runs_expiry", "expires_at"),
    )
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(255), ForeignKey("job_finalizations.job_id", ondelete="CASCADE"), nullable=False, unique=True)
    resume_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    base_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effort: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    credential_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running", server_default="running")
    snapshot: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    context_payload: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    budget: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    decisions: Mapped[Dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ResumeOptimizationStage(Base):
    """A unique durable intent prevents repaying an ambiguous provider call."""
    __tablename__ = "resume_optimization_stages"
    __table_args__ = (
        UniqueConstraint("run_id", "stage_key", name="uq_optimization_stage_key"),
        CheckConstraint("status IN ('requesting','completed','failed','ambiguous')", name="ck_optimization_stage_status"),
        CheckConstraint("owner_epoch > 0", name="ck_optimization_stage_epoch"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(255), ForeignKey("resume_optimization_runs.id", ondelete="CASCADE"), nullable=False)
    stage_key: Mapped[str] = mapped_column(String(128), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="requesting", server_default="requesting")
    owner_token: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_usage: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    usage: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    output: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    output_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ResumeRequirementContext(Base):
    __tablename__ = "resume_requirement_contexts"
    __table_args__ = (UniqueConstraint("user_id", "jd_hash", "version", "language", name="uq_resume_requirement_context"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    jd_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    requirements: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
    # Server-derived signup provider. Values: email | google | github | oidc |
    # passkey | unknown. Never written from a client claim (migration 0081).
    auth_provider: Mapped[str] = mapped_column(
        String(20), default="unknown", server_default="unknown", nullable=False
    )
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
        CheckConstraint("content_revision > 0", name="ck_resumes_content_revision_positive"),
        CheckConstraint("imported_projection IS NULL OR octet_length(imported_projection::text) <= 131072",
                        name="ck_resumes_imported_projection_bounded"),
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
    content_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    imported_projection: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
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
        CheckConstraint(
            "error_class IN ('syntax', 'missing_package', 'timeout', 'engine', "
            "'storage', 'pdf_limit', 'unknown')",
            name="ck_compilations_error_class",
        ),
        # Bounded document-complexity counts (0092). Only counts are stored;
        # source text and rendered content never reach these columns.
        CheckConstraint(
            "page_count IS NULL OR (page_count >= 1 AND page_count <= 10000)",
            name="ck_compilations_page_count_bounded",
        ),
        CheckConstraint(
            "section_count IS NULL OR (section_count >= 0 AND section_count <= 500)",
            name="ck_compilations_section_count_bounded",
        ),
        # DB-013: composite index supports queries filtering by resume filtered by status
        Index("idx_compilations_resume_status", "resume_id", "status"),
        # Compile-latency analytics scan completed rows by status in a bounded
        # created_at window before grouping by the persisted dimensions.
        Index("idx_compilations_latency_created", "status", "created_at"),
        # Compile-error analytics group failed rows by the persisted class in a
        # bounded created_at window. Only the allowlisted class is stored.
        Index(
            "idx_compilations_error_class_created",
            "error_class",
            "created_at",
            postgresql_where=text("status = 'failed'"),
        ),
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
    artifact_branch: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft", default="draft")
    artifact_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", default=True)
    compilation_time: Mapped[Optional[float]] = mapped_column(Float)
    # Aggregate attribution captured at admission from server-side state.
    # Nullable because rows created before 0081 (and jobs without a résumé or
    # template) have no dimension value; analytics reports those as missing.
    plan_family: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    compiler: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    template_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), index=True)
    pdf_size: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    # Bounded compile-complexity counts (0092). ``page_count`` is the
    # compiler-reported PDF page count for successful compiles; ``section_count``
    # is a bounded count derived from submitted source at admission. Neither
    # column stores LaTeX/PDF text or any other document content.
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    section_count: Mapped[Optional[int]] = mapped_column(Integer)
    # Normalized compile-error taxonomy (0083). Classified at write time from
    # bounded parser/finalization signals; raw logs and document text are never
    # copied into this column or exported to analytics.
    error_class: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="unknown", default="unknown"
    )
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


class EmailDeliveryEvent(Base):
    """Append-only provider delivery/bounce/complaint evidence.

    Rows are keyed by the provider webhook event id for idempotency and carry
    the provider message id for delivery mapping. Recipient mailboxes are never
    stored; ``recipient_hash`` is a one-way digest used only to honour
    suppression state. No message body, subject, headers or provider payload is
    persisted.
    """

    __tablename__ = "email_delivery_events"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_email_delivery_events_provider_event",
        ),
        Index(
            "ix_email_delivery_events_provider_message",
            "provider_message_id",
        ),
        Index(
            "ix_email_delivery_events_type_occurred",
            "event_type",
            "occurred_at",
        ),
        Index("ix_email_delivery_events_delivery", "delivery_id"),
        Index("ix_email_delivery_events_recipient_hash", "recipient_hash"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="resend", server_default="resend"
    )
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivery_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("document_email_deliveries.id", ondelete="CASCADE"),
        nullable=True,
    )
    recipient_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    bounce_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    bounce_subtype: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    occurred_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EmailRecipientSuppression(Base):
    """Current local suppression state for a hashed recipient address.

    The provider remains the source of truth for its suppression list; this
    table mirrors suppression.added/removed and hard bounce/complaint outcomes so
    Latexy does not submit another document email to a known-bad mailbox.
    """

    __tablename__ = "email_recipient_suppressions"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "recipient_hash",
            name="uq_email_recipient_suppressions_provider_hash",
        ),
        Index("ix_email_recipient_suppressions_created", "created_at"),
        Index("ix_email_recipient_suppressions_delivery", "delivery_id"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="resend", server_default="resend"
    )
    recipient_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    source_event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivery_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("document_email_deliveries.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
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
    # Legacy post-score column kept for older readers. New writers set both
    # ats_score_after and ats_score; ats_score_before stays NULL when no
    # comparable baseline was captured for the run.
    ats_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ats_score_before: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ats_score_after: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Bounded classification keys only — never resume or job-description text.
    industry: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    profile: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
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


class SignupFunnelEvent(Base):
    """Aggregate-only signup funnel event (migration 0081).

    Rows intentionally contain no email, name, IP, user-agent, OAuth token or
    other credential. ``provider`` is always an allowlisted bucket derived from
    server-owned auth state; anonymous attempt rows are never joined back to an
    account to assign it a provider.
    """

    __tablename__ = "signup_funnel_events"
    __table_args__ = (
        CheckConstraint(
            "event IN ('signup_started', 'signup_completed', 'email_verified', 'oauth_failure')",
            name="ck_signup_funnel_events_event",
        ),
        CheckConstraint(
            "provider IN ('email', 'google', 'github', 'oidc', 'passkey', 'unknown')",
            name="ck_signup_funnel_events_provider",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code IN "
            "('access_denied', 'account_not_linked', 'callback_failed', "
            "'provider_error', 'state_mismatch', 'unknown')",
            name="ck_signup_funnel_events_failure_code",
        ),
        Index(
            "idx_signup_funnel_events_event_provider_time",
            "event",
            "provider",
            "created_at",
        ),
        Index("idx_signup_funnel_events_user_event", "user_id", "event"),
        Index(
            "uq_signup_funnel_events_user_milestone",
            "user_id",
            "event",
            unique=True,
            postgresql_where=text(
                "user_id IS NOT NULL AND event IN ('signup_completed', 'email_verified')"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(20), default="unknown", server_default="unknown", nullable=False
    )
    failure_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TrialAttribution(Base):
    """Consented trial acquisition and trial-to-account/subscription link.

    One row per anonymous trial. ``user_id``/``subscription_id`` stay null
    until the visitor signs in, then the row is linked in place. No raw device
    fingerprint, IP address, user-agent, email, name or token is stored here;
    the anonymous trial row remains the only device-scoped record.
    """

    __tablename__ = "trial_attributions"
    __table_args__ = (
        CheckConstraint(
            "consent_granted OR ("
            "acquisition_source IS NULL AND acquisition_medium IS NULL AND "
            "acquisition_campaign IS NULL AND acquisition_content IS NULL AND "
            "acquisition_term IS NULL AND referrer_host IS NULL AND "
            "landing_path IS NULL)",
            name="ck_trial_attributions_consent_source",
        ),
        UniqueConstraint("trial_id", name="uq_trial_attributions_trial"),
        Index(
            "uq_trial_attributions_user",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index("idx_trial_attributions_source", "acquisition_source"),
        Index("idx_trial_attributions_user_created", "user_id", "created_at"),
        Index("idx_trial_attributions_paid", "paid_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    trial_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("device_trials.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    subscription_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    consent_granted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    acquisition_source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    acquisition_medium: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    acquisition_campaign: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    acquisition_content: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    acquisition_term: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    referrer_host: Mapped[Optional[str]] = mapped_column(String(253), nullable=True)
    landing_path: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    plan_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    trial_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    signup_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Subscription(Base):
    """Subscription management."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subscription_id", name="uq_subscriptions_provider_subscription_id"),
        UniqueConstraint("provider", "provider_checkout_session_id", name="uq_subscriptions_provider_checkout_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="dodo", server_default="dodo")
    provider_subscription_id: Mapped[Optional[str]] = mapped_column(String(255))
    provider_checkout_session_id: Mapped[Optional[str]] = mapped_column(String(255))
    provider_customer_id: Mapped[Optional[str]] = mapped_column(String(255))
    provider_product_id: Mapped[Optional[str]] = mapped_column(String(255))
    provider_event_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    quoted_amount: Mapped[Optional[int]] = mapped_column(Integer)
    quoted_tax_inclusive: Mapped[Optional[bool]] = mapped_column(Boolean)
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
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


class SubscriptionHistory(Base):
    """Append-only subscription plan/status transition ledger.

    Rows are written by the billing service inside the subscription mutation
    transaction. ``previous_*`` columns make upgrades/downgrades and churn
    reconstructable without parsing logs. The table intentionally stores only a
    user UUID, plan/status identifiers, period timestamps and allowlisted event
    metadata: no email, name, document, provider payload, token or free text.
    """

    __tablename__ = "subscription_history"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "effective_at",
            "plan_id",
            "status",
            name="uq_subscription_history_transition",
        ),
        CheckConstraint(
            "event_type IN ('subscription_created', 'plan_changed', "
            "'status_changed', 'activated', 'renewed', 'period_updated', "
            "'cancellation_scheduled', 'cancelled', 'expired', "
            "'payment_failed', 'refunded', 'checkout_failed', "
            "'checkout_unknown', 'admin_override', 'backfill')",
            name="ck_subscription_history_event_type",
        ),
        CheckConstraint(
            "source IN ('billing', 'checkout', 'reconcile', 'admin', 'backfill')",
            name="ck_subscription_history_source",
        ),
        Index("idx_subscription_history_user_effective", "user_id", "effective_at"),
        Index("idx_subscription_history_effective_type", "effective_at", "event_type"),
        Index(
            "idx_subscription_history_subscription_effective",
            "subscription_id",
            "effective_at",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subscription_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    plan_id: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_plan_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    current_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(
        String(24), nullable=False, default="billing", server_default="billing"
    )
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SubscriptionStatusHistory(Base):
    """Append-only provider status observations for dunning recovery.

    The current ``subscriptions.status`` column is a snapshot; this ledger keeps
    the ordered observations needed to reconstruct past-due/on-hold episodes.
    Duplicate deliveries share the natural key and are ignored. An older event
    may be recorded with ``applied=False`` so it is visible to the timeline
    without regressing the current subscription row. No customer PII, provider
    payload, token or free-form note is stored here.
    """

    __tablename__ = "subscription_status_history"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "provider_event_at",
            "status",
            name="uq_subscription_status_history_transition",
        ),
        CheckConstraint(
            "event_type IN ('dunning_started', 'dunning_escalated', "
            "'recovered', 'cancelled', 'expired', 'failed', "
            "'status_observed', 'backfill')",
            name="ck_subscription_status_history_event_type",
        ),
        CheckConstraint(
            "source IN ('billing', 'checkout', 'reconcile', 'admin', 'backfill')",
            name="ck_subscription_status_history_source",
        ),
        Index(
            "idx_subscription_status_history_subscription_effective",
            "subscription_id",
            "provider_event_at",
        ),
        Index(
            "idx_subscription_status_history_user_effective",
            "user_id",
            "provider_event_at",
        ),
        Index(
            "idx_subscription_status_history_effective_status",
            "provider_event_at",
            "status",
        ),
        Index(
            "idx_subscription_status_history_plan_effective",
            "plan_id",
            "provider_event_at",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subscription_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    plan_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(
        String(24), nullable=False, default="billing", server_default="billing"
    )
    provider_event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    provider_event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Payment(Base):
    """Payment history."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider", "provider_payment_id", name="uq_payments_provider_payment_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # DB-006: SET NULL preserves payment history when a subscription row is deleted;
    # index backs per-subscription payment lookups.
    subscription_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="dodo", server_default="dodo")
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(255))
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    provider_event_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="payments")
    subscription: Mapped[Optional["Subscription"]] = relationship("Subscription", back_populates="payments")


class BillingWebhookEvent(Base):
    """Durable inbox for signed provider webhooks; Redis is only an optional lock."""

    __tablename__ = "billing_webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_billing_webhook_provider_event"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    event_resource_id: Mapped[Optional[str]] = mapped_column(String(255))
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    event_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="processing", server_default="processing")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    acknowledgement_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reconcile_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_reconcile_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reconcile_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_reconcile_outcome: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class AdminAuditLog(Base):
    """Append-only operator action record; the database rejects UPDATE/DELETE."""

    __tablename__ = "admin_audit_log"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    actor_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    actor_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    before_state: Mapped[Optional[Dict]] = mapped_column("before", JSONB, nullable=True)
    after_state: Mapped[Optional[Dict]] = mapped_column("after", JSONB, nullable=True)
    event_metadata: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AdminApproval(Base):
    """Two-person approval for one sensitive admin action.

    The canonical payload is hashed at request time and cannot be changed. A
    different admin must approve it before a mutation may consume it, and a
    consumed approval can never be replayed. Direct identifiers in the payload
    are bounded to target UUIDs, roles, feature keys and booleans; documents,
    prompts, emails, tokens and provider payloads are never stored here.
    """

    __tablename__ = "admin_approvals"
    __table_args__ = (
        CheckConstraint(
            "request_type IN ('refund', 'account_deletion', 'impersonation', "
            "'role_escalation', 'bulk_entitlement_change')",
            name="ck_admin_approvals_request_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'executing', "
            "'executed', 'failed', 'expired', 'cancelled')",
            name="ck_admin_approvals_status",
        ),
        CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name="ck_admin_approvals_payload_hash",
        ),
        CheckConstraint(
            "expires_at > requested_at",
            name="ck_admin_approvals_expiry",
        ),
        CheckConstraint(
            "approved_by IS NULL OR approved_by <> requested_by",
            name="ck_admin_approvals_separation_of_duties",
        ),
        CheckConstraint(
            "status NOT IN ('approved', 'executing', 'executed') OR approved_by IS NOT NULL",
            name="ck_admin_approvals_approved_actor",
        ),
        CheckConstraint(
            "status <> 'executed' OR executed_at IS NOT NULL",
            name="ck_admin_approvals_executed_at",
        ),
        CheckConstraint(
            "status <> 'rejected' OR decided_at IS NOT NULL",
            name="ck_admin_approvals_rejected_at",
        ),
        Index("idx_admin_approvals_status_requested", "status", "requested_at"),
        Index("idx_admin_approvals_request_type_requested", "request_type", "requested_at"),
        Index("idx_admin_approvals_requester_requested", "requested_by", "requested_at"),
        Index("idx_admin_approvals_expires", "expires_at"),
        Index("idx_admin_approvals_resource", "resource_type", "resource_id"),
        Index(
            "uq_admin_approvals_open_payload",
            "request_type",
            "payload_hash",
            unique=True,
            postgresql_where=text("status IN ('pending', 'approved', 'executing')"),
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    request_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[Dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False)
    approved_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    decision_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    execution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    executed_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    result: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    audit_request_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("admin_audit_log.id", ondelete="RESTRICT"),
        nullable=True,
    )
    audit_decision_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("admin_audit_log.id", ondelete="RESTRICT"),
        nullable=True,
    )
    audit_execution_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("admin_audit_log.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class GdprRequest(Base):
    """One data-subject export or erasure request.

    Status is mutable so the queue can advance, but every transition is written
    to the append-only ``gdpr_request_events`` table and request rows cannot be
    deleted. No document content, export token or admin note beyond the bounded
    review note is duplicated here.
    """

    __tablename__ = "gdpr_requests"
    __table_args__ = (
        CheckConstraint(
            "request_type IN ('export', 'deletion')",
            name="ck_gdpr_requests_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'legal_review', 'approved', 'processing', "
            "'ready', 'completed', 'failed', 'rejected', 'cancelled', "
            "'blocked', 'expired')",
            name="ck_gdpr_requests_status",
        ),
        CheckConstraint(
            "legal_review_status IN ('not_required', 'pending', 'approved', 'rejected')",
            name="ck_gdpr_requests_legal_review_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_gdpr_requests_attempts"),
        CheckConstraint(
            "export_size_bytes IS NULL OR export_size_bytes >= 0",
            name="ck_gdpr_requests_export_size",
        ),
        Index("idx_gdpr_requests_user_created", "user_id", "created_at"),
        Index("idx_gdpr_requests_status_created", "status", "created_at"),
        Index("idx_gdpr_requests_type_status", "request_type", "status"),
        Index("idx_gdpr_requests_export_expiry", "export_expires_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    # SET NULL keeps the request history if a future hard-delete maintenance
    # pass removes an already anonymized account row.
    user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", server_default="pending"
    )
    legal_review_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="not_required",
        server_default="not_required",
    )
    identity_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reauthenticated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    legal_reviewed_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    legal_reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    legal_review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    legal_hold_blocked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    export_token_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    export_issued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    export_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    export_downloaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    export_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    export_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    failure_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    failure_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    table_results: Mapped[List[Dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    retention_exceptions: Mapped[List[Dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GdprRequestEvent(Base):
    """Append-only transition history for a GDPR request."""

    __tablename__ = "gdpr_request_events"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user', 'admin', 'system')",
            name="ck_gdpr_request_events_actor_type",
        ),
        Index("idx_gdpr_request_events_request_created", "request_id", "created_at"),
        Index("idx_gdpr_request_events_actor_created", "actor_user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("gdpr_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    from_status: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    to_status: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[Dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GdprLegalHold(Base):
    """Active legal hold that blocks an account erasure job until released."""

    __tablename__ = "gdpr_legal_holds"
    __table_args__ = (
        CheckConstraint(
            "active OR released_at IS NOT NULL",
            name="ck_gdpr_legal_holds_released",
        ),
        Index("idx_gdpr_legal_holds_user_active", "user_id", "active"),
        Index(
            "uq_gdpr_legal_holds_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("active"),
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    placed_by: Mapped[str] = mapped_column(String(36), nullable=False)
    placed_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    released_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    released_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    released_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    release_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AdminRefundRequest(Base):
    """Refund intent with separation of duties and a provider execution receipt."""

    __tablename__ = "admin_refund_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'executing', 'executed', 'failed', 'cancelled')",
            name="ck_admin_refund_status",
        ),
        CheckConstraint("amount IS NULL OR amount > 0", name="ck_admin_refund_amount"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    payment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    amount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    provider_item_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tax_inclusive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decision_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False)
    requested_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    approved_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    executed_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    provider_refund_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AdminAlert(Base):
    """Durable operational alert with deduplication, ack and snooze state."""

    __tablename__ = "admin_alerts"
    __table_args__ = (
        CheckConstraint(
            "state IN ('open', 'acknowledged', 'snoozed', 'resolved')",
            name="ck_admin_alerts_state",
        ),
        CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low')",
            name="ck_admin_alerts_severity",
        ),
        Index("idx_admin_alerts_state_severity", "state", "severity", "last_seen_at"),
        Index("idx_admin_alerts_kind", "kind"),
        Index(
            "uq_admin_alerts_active_dedupe",
            "dedupe_key",
            unique=True,
            postgresql_where=text("state IN ('open', 'acknowledged', 'snoozed')"),
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    owner: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[Dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    runbook_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="open", server_default="open")
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledgement_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    snoozed_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    snoozed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    snooze_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AdminIncident(Base):
    """Operator-owned incident timeline row.

    Only admin-written operational metadata lives here: no customer identifiers,
    document content, provider errors or credentials. The status/end-time
    invariant is enforced in the database so an open incident cannot carry an
    end timestamp and a resolved incident cannot omit one.
    """

    __tablename__ = "admin_incidents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'resolved')",
            name="ck_admin_incidents_status",
        ),
        CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low')",
            name="ck_admin_incidents_severity",
        ),
        CheckConstraint(
            "(status = 'open' AND ended_at IS NULL) OR "
            "(status = 'resolved' AND ended_at IS NOT NULL)",
            name="ck_admin_incidents_state_end",
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_admin_incidents_time_order",
        ),
        CheckConstraint(
            "jsonb_typeof(services) = 'array' AND jsonb_array_length(services) > 0",
            name="ck_admin_incidents_services",
        ),
        CheckConstraint(
            "jsonb_typeof(links) = 'array'",
            name="ck_admin_incidents_links",
        ),
        CheckConstraint(
            "jsonb_typeof(related_alert_keys) = 'array'",
            name="ck_admin_incidents_alert_keys",
        ),
        CheckConstraint(
            "deploy_sha IS NULL OR deploy_sha ~ '^[0-9a-f]{7,40}$'",
            name="ck_admin_incidents_deploy_sha",
        ),
        CheckConstraint(
            "length(trim(title)) > 0 AND length(trim(summary)) > 0 "
            "AND length(trim(owner)) > 0",
            name="ck_admin_incidents_required_text",
        ),
        Index("idx_admin_incidents_status_started", "status", "started_at"),
        Index("idx_admin_incidents_severity_started", "severity", "started_at"),
        Index("idx_admin_incidents_started", "started_at"),
        Index("idx_admin_incidents_services", "services", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", server_default="open")
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    services: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    owner: Mapped[str] = mapped_column(String(64), nullable=False)
    links: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    related_alert_keys: Mapped[List[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    deploy_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    deploy_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AdminSavedView(Base):
    """Reusable admin tab state: filters, columns, sort and range.

    Rows are owner-scoped operator preferences, never customer records. Only
    allowlisted filter keys/values are persisted by the service layer; names,
    filters and payloads are rejected when they look like PII or document
    content. Deletes are soft (``deleted_at``) so a stale browser cannot
    silently lose a shared view. ``version`` is the optimistic-concurrency
    token used by update/delete.
    """

    __tablename__ = "admin_saved_views"
    __table_args__ = (
        CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 80 AND length(name_key) BETWEEN 1 AND 80",
            name="ck_admin_saved_views_name",
        ),
        CheckConstraint(
            "scope IN ('analytics', 'operations', 'quality', 'billing', "
            "'subscriptions', 'email', 'growth', 'customers')",
            name="ck_admin_saved_views_scope",
        ),
        CheckConstraint(
            "range_days IS NULL OR (range_days >= 1 AND range_days <= 365)",
            name="ck_admin_saved_views_range",
        ),
        CheckConstraint("version >= 1", name="ck_admin_saved_views_version"),
        CheckConstraint(
            "jsonb_typeof(filters) = 'object'",
            name="ck_admin_saved_views_filters_object",
        ),
        CheckConstraint(
            "jsonb_typeof(columns) = 'array'",
            name="ck_admin_saved_views_columns_array",
        ),
        CheckConstraint(
            "sort IS NULL OR jsonb_typeof(sort) = 'object'",
            name="ck_admin_saved_views_sort_object",
        ),
        Index(
            "uq_admin_saved_views_owner_scope_name",
            "owner_user_id",
            "scope",
            "name_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_admin_saved_views_owner_default",
            "owner_user_id",
            "scope",
            unique=True,
            postgresql_where=text("is_default AND deleted_at IS NULL"),
        ),
        Index("idx_admin_saved_views_scope_updated", "scope", "updated_at"),
        Index("idx_admin_saved_views_owner_updated", "owner_user_id", "updated_at"),
        Index("idx_admin_saved_views_shared_updated", "shared", "updated_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_key: Mapped[str] = mapped_column(String(80), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    filters: Mapped[Dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    columns: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    sort: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    range_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminSegment(Base):
    """Reusable cohort definition over allowlisted aggregate dimensions.

    Only the typed filter DSL (match + conditions) is stored. The service
    compiler maps each field/operator to a fixed SQLAlchemy expression, so a
    stored definition can never contain SQL, identifiers, document content or
    per-user data. Visibility is private by default; sharing requires the
    owner's explicit flag. Deletes are soft and versioned like saved views.
    """

    __tablename__ = "admin_segments"
    __table_args__ = (
        CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 80 AND length(name_key) BETWEEN 1 AND 80",
            name="ck_admin_segments_name",
        ),
        CheckConstraint(
            "description IS NULL OR length(description) <= 280",
            name="ck_admin_segments_description",
        ),
        CheckConstraint("version >= 1", name="ck_admin_segments_version"),
        CheckConstraint(
            "jsonb_typeof(definition) = 'object'",
            name="ck_admin_segments_definition_object",
        ),
        Index(
            "uq_admin_segments_owner_name",
            "owner_user_id",
            "name_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_admin_segments_owner_updated", "owner_user_id", "updated_at"),
        Index("idx_admin_segments_shared_updated", "shared", "updated_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_key: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    definition: Mapped[Dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class LLMCallAttempt(Base):
    """Append-only, privacy-safe telemetry for one LLM provider attempt.

    Only aggregate dimensions, bounded outcome classes and latency are stored.
    Prompts, documents, provider error text, API keys and user identifiers never
    enter this table. ``run_ref`` is an opaque hash used only to count distinct
    runs for reconciliation.
    """

    __tablename__ = "llm_call_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'error', 'timeout', 'cancelled')",
            name="ck_llm_call_attempts_status",
        ),
        CheckConstraint(
            "retry_reason IN ('none', 'timeout', 'rate_limit', 'connection', "
            "'provider_error', 'empty_output', 'truncated', 'invalid_response', "
            "'cancelled', 'unknown')",
            name="ck_llm_call_attempts_retry_reason",
        ),
        CheckConstraint(
            "error_class IS NULL OR error_class IN ('timeout', 'rate_limit', "
            "'connection', 'provider_error', 'invalid_response', 'cancelled', "
            "'unknown')",
            name="ck_llm_call_attempts_error_class",
        ),
        CheckConstraint(
            "attempt_number >= 1",
            name="ck_llm_call_attempts_attempt_number",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_llm_call_attempts_latency",
        ),
        Index("idx_llm_attempts_occurred", "occurred_at"),
        Index("idx_llm_attempts_provider_occurred", "provider", "occurred_at"),
        Index("idx_llm_attempts_model_occurred", "provider", "model", "occurred_at"),
        Index("idx_llm_attempts_feature_occurred", "feature", "occurred_at"),
        Index("idx_llm_attempts_plan_occurred", "plan", "occurred_at"),
        Index("idx_llm_attempts_run", "run_ref"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    provider: Mapped[str] = mapped_column(
        String(64), nullable=False, default="unknown", server_default="unknown"
    )
    model: Mapped[str] = mapped_column(
        String(160), nullable=False, default="unknown", server_default="unknown"
    )
    feature: Mapped[str] = mapped_column(
        String(120), nullable=False, default="unknown", server_default="unknown"
    )
    plan: Mapped[str] = mapped_column(
        String(50), nullable=False, default="unknown", server_default="unknown"
    )
    run_ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="success", server_default="success"
    )
    retry_reason: Mapped[str] = mapped_column(
        String(64), nullable=False, default="none", server_default="none"
    )
    error_class: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class CeleryQueueSnapshot(Base):
    """A single periodic sample of a Celery queue for admin operations.

    Operational metadata only: pending depth, the age of the oldest pending
    message, and cumulative enqueue/completion totals used to derive throughput.
    Rows carry no job payloads and no Redis credentials.
    """

    __tablename__ = "celery_queue_snapshots"
    __table_args__ = (
        CheckConstraint("depth >= 0", name="ck_queue_snapshots_depth"),
        CheckConstraint(
            "oldest_age_seconds IS NULL OR oldest_age_seconds >= 0",
            name="ck_queue_snapshots_age",
        ),
        Index("idx_queue_snapshots_queue_sampled", "queue", "sampled_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    queue: Mapped[str] = mapped_column(String(64), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    oldest_age_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    enqueued_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completed_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    sampled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PaymentRefund(Base):
    """Append-only refund records, including partial refunds and failed attempts."""

    __tablename__ = "payment_refunds"
    __table_args__ = (UniqueConstraint("provider", "provider_refund_id", name="uq_payment_refunds_provider_id"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    payment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_refund_id: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Optional[int]] = mapped_column(Integer)
    currency: Mapped[Optional[str]] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    """Coupon reservation and redemption state for a subscription intent."""

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
    subscription_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="redeemed", server_default="redeemed")
    redeemed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, server_default=func.now())


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


class RoleFeature(Base):
    """Optional product restrictions by authenticated account role/context."""

    __tablename__ = "role_features"

    role: Mapped[str] = mapped_column(String(20), primary_key=True)
    feature_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        CheckConstraint("role IN ('anonymous', 'user', 'support', 'admin')", name="ck_capability_role"),
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


class TemplateHealthCheck(Base):
    """Append-only verification evidence for one catalog template.

    Template popularity and compile outcomes stay in their existing source
    tables.  This table only owns the latest rendered-asset/compile/visual
    verification snapshot so admin can distinguish pass, fail and unknown.
    Rows never contain template source, document text, compiler logs, storage
    credentials or per-user activity.
    """

    __tablename__ = "template_health_checks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pass', 'fail', 'unknown')",
            name="ck_template_health_checks_status",
        ),
        CheckConstraint(
            "visual_test IN ('pass', 'fail', 'unknown')",
            name="ck_template_health_checks_visual_test",
        ),
        CheckConstraint(
            "error_class IS NULL OR error_class IN "
            "('missing_asset', 'compile_error', 'syntax', 'missing_package', "
            "'timeout', 'engine', 'storage', 'pdf_limit', 'visual_regression', 'unknown')",
            name="ck_template_health_checks_error_class",
        ),
        CheckConstraint(
            "source IN ('admin_retry', 'compile_batch', 'ci', 'backfill')",
            name="ck_template_health_checks_source",
        ),
        CheckConstraint(
            "commit_sha IS NULL OR commit_sha ~ '^[0-9a-f]{40}$'",
            name="ck_template_health_checks_commit_sha",
        ),
        CheckConstraint(
            "ci_run_id IS NULL OR ci_run_id ~ '^[0-9]{1,32}$'",
            name="ck_template_health_checks_ci_run_id",
        ),
        CheckConstraint(
            "compile_samples IS NULL OR compile_samples >= 0",
            name="ck_template_health_checks_compile_samples",
        ),
        CheckConstraint(
            "compile_failures IS NULL OR compile_failures >= 0",
            name="ck_template_health_checks_compile_failures",
        ),
        CheckConstraint(
            "compile_samples IS NULL OR compile_failures IS NULL "
            "OR compile_failures <= compile_samples",
            name="ck_template_health_checks_compile_failures_bounded",
        ),
        UniqueConstraint(
            "template_id",
            "idempotency_key",
            name="uq_template_health_checks_template_idempotency",
        ),
        Index(
            "ix_template_health_checks_template_checked",
            "template_id",
            text("checked_at DESC"),
        ),
        Index("ix_template_health_checks_checked", "checked_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    template_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("resume_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    error_class: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    visual_test: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    commit_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    ci_run_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="admin_retry")
    assets_present: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    compile_samples: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    compile_failures: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status_detail: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


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
    # Nullable because an external DNS/TLS automation owns these facts. Null is
    # surfaced as "unknown expiry", never as an unlimited/far-future domain.
    domain_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    domain_certificate_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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


class TenantDomainEvent(Base):
    """Append-only, tenant-scoped custom-domain verification history.

    Only an allowlisted outcome, the tenant-owned hostname, an optional error
    class and the check timestamp are persisted. DNS answers, TXT values,
    certificate material and user identifiers never enter this table.
    """

    __tablename__ = "tenant_domain_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('verified', 'failed', 'error', 'removed')",
            name="ck_tenant_domain_events_event_type",
        ),
        CheckConstraint(
            "error_class IS NULL OR error_class IN ('txt_missing', 'dns_unavailable')",
            name="ck_tenant_domain_events_error_class",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    error_class: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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
class RenderArtifactManifest(Base):
    """Durable private references for authorized preview and safe binary GC."""
    __tablename__ = "render_artifact_manifests"
    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(255), ForeignKey("job_finalizations.job_id", ondelete="CASCADE"), nullable=False, index=True)
    owner_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_scope_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    manifest_key: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    pdf_key: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    synctex_key: Mapped[Optional[str]] = mapped_column(String(500), index=True)
    geometry_key: Mapped[Optional[str]] = mapped_column(String(500), index=True)
    payload: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class RetentionPolicy(Base):
    """Current configured retention window and schedule for one data class."""

    __tablename__ = "retention_policies"
    __table_args__ = (
        CheckConstraint(
            "data_class IN ('pdfs', 'job_finalizations', 'analytics', 'audit', 'exports')",
            name="ck_retention_policies_data_class",
        ),
        CheckConstraint(
            "configured_hours BETWEEN 1 AND 87600",
            name="ck_retention_policies_configured_hours",
        ),
        CheckConstraint(
            "schedule_hours BETWEEN 1 AND 8760",
            name="ck_retention_policies_schedule_hours",
        ),
        CheckConstraint("version >= 1", name="ck_retention_policies_version"),
    )

    data_class: Mapped[str] = mapped_column(String(32), primary_key=True)
    configured_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    schedule_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=24, server_default="24"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    change_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class RetentionPolicyRevision(Base):
    """Append-only snapshot of one retention policy version."""

    __tablename__ = "retention_policy_revisions"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_retention_policy_revisions_version"),
    )

    data_class: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("retention_policies.data_class", ondelete="RESTRICT"),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    changed_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RetentionRun(Base):
    """One bounded preview or purge attempt for a data class."""

    __tablename__ = "retention_runs"
    __table_args__ = (
        CheckConstraint(
            "data_class IN ('pdfs', 'job_finalizations', 'analytics', 'audit', 'exports')",
            name="ck_retention_runs_data_class",
        ),
        CheckConstraint("mode IN ('dry_run', 'purge')", name="ck_retention_runs_mode"),
        CheckConstraint(
            "status IN ('running', 'completed', 'refused', 'failed')",
            name="ck_retention_runs_status",
        ),
        CheckConstraint("batch_limit BETWEEN 1 AND 1000", name="ck_retention_runs_batch_limit"),
        CheckConstraint(
            "scanned >= 0 AND eligible >= 0 AND affected >= 0",
            name="ck_retention_runs_counts",
        ),
        Index("idx_retention_runs_class_started", "data_class", "started_at"),
        Index(
            "uq_retention_runs_active_class",
            "data_class",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
        Index(
            "uq_retention_runs_idempotency",
            "data_class",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    data_class: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("retention_policies.data_class", ondelete="RESTRICT"),
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running", server_default="running"
    )
    retention_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    eligible: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    protected_active_jobs: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    protected_legal_hold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    protected_immutable: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    recent: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    affected: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    batch_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=200, server_default="200")
    has_more: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    started_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detail: Mapped[Dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


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


class PlanCatalog(Base):
    """Mutable merchandising for a stable SKU; no price or subscription state."""

    __tablename__ = "plan_catalog"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_plan_catalog_version"),
        CheckConstraint("display_order >= 0", name="ck_plan_catalog_order"),
    )

    sku: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    purchase_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    updated_by: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class PlanCatalogRevision(Base):
    """Append-only snapshots of admin merchandising changes for review."""

    __tablename__ = "plan_catalog_revisions"
    sku: Mapped[str] = mapped_column(String(50), ForeignKey("plan_catalog.sku"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    changed_by: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PlanQuotaOverride(Base):
    """Exact-SKU allowance overrides. Windows and counter identities are fixed."""

    __tablename__ = "plan_quota_overrides"
    __table_args__ = (
        CheckConstraint("dimension IN ('compilations', 'optimizations', 'ai_assists')", name="ck_plan_quota_dimension"),
        CheckConstraint("limit_value IS NULL OR (limit_value >= 0 AND limit_value <= 1000000000)", name="ck_plan_quota_limit"),
        CheckConstraint("version >= 1", name="ck_plan_quota_version"),
    )
    sku: Mapped[str] = mapped_column(String(50), primary_key=True)
    dimension: Mapped[str] = mapped_column(String(30), primary_key=True)
    limit_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    updated_by: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class PlanQuotaRevision(Base):
    """Append-only audit of limit edits; never stores or resets usage counters."""

    __tablename__ = "plan_quota_revisions"
    sku: Mapped[str] = mapped_column(String(50), primary_key=True)
    dimension: Mapped[str] = mapped_column(String(30), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    limit_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    changed_by: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RedisAuthorityControl(Base):
    """Primary-only freeze record; frozen authority cannot admit product work."""

    __tablename__ = "redis_authority_control"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_redis_authority_singleton"),
        CheckConstraint("generation >= 0", name="ck_redis_authority_generation"),
        CheckConstraint("phase IN ('legacy', 'frozen')", name="ck_redis_authority_phase"),
        CheckConstraint("active_backend = 'primary'", name="ck_redis_authority_primary_only"),
        CheckConstraint(
            "(phase = 'legacy' AND freeze_reason IS NULL AND freeze_id IS NULL) OR "
            "(phase = 'frozen' AND freeze_reason IS NOT NULL AND freeze_id IS NOT NULL)",
            name="ck_redis_authority_freeze_reason",
        ),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    active_backend: Mapped[str] = mapped_column(String(16), nullable=False)
    freeze_reason: Mapped[Optional[str]] = mapped_column(String(32))
    freeze_id: Mapped[Optional[str]] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class QuotaLedgerAccount(Base):
    """Disabled durable account; missing or unknown balances cannot admit work."""

    __tablename__ = "quota_ledger_accounts"
    __table_args__ = (
        CheckConstraint("status IN ('unknown', 'reconciled')", name="ck_quota_account_status"),
        CheckConstraint(
            "(status = 'unknown' AND used IS NULL AND opening_used IS NULL AND "
            "source_ref IS NULL AND source_sha256 IS NULL AND reconciled_at IS NULL) OR "
            "(status = 'reconciled' AND used IS NOT NULL AND used >= 0 AND "
            "opening_used IS NOT NULL AND opening_used >= 0 AND "
            "source_ref IS NOT NULL AND length(trim(source_ref)) > 0 AND "
            "source_sha256 IS NOT NULL AND length(source_sha256) = 64 AND "
            "reconciled_at IS NOT NULL)",
            name="ck_quota_account_reconciliation",
        ),
    )

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dimension: Mapped[str] = mapped_column(String(64), primary_key=True)
    period: Mapped[str] = mapped_column(String(8), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    used: Mapped[Optional[int]] = mapped_column(BigInteger)
    opening_used: Mapped[Optional[int]] = mapped_column(BigInteger)
    source_ref: Mapped[Optional[str]] = mapped_column(String(255))
    source_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    reconciled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class QuotaLedgerReservation(Base):
    """One immutable request fingerprint and its terminal refund outcome."""

    __tablename__ = "quota_ledger_reservations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "dimension", "period"],
            ["quota_ledger_accounts.user_id", "quota_ledger_accounts.dimension", "quota_ledger_accounts.period"],
            name="fk_quota_reservation_account", ondelete="RESTRICT",
        ),
        CheckConstraint("cost > 0", name="ck_quota_reservation_cost"),
        CheckConstraint("limit_value IS NULL OR limit_value >= 0", name="ck_quota_reservation_limit"),
        CheckConstraint("used_after >= 0", name="ck_quota_reservation_used"),
        CheckConstraint(
            "(\"window\" = 'day' AND length(period) = 8) OR "
            "(\"window\" = 'month' AND length(period) = 6)",
            name="ck_quota_reservation_window",
        ),
        CheckConstraint("length(intent_fingerprint) = 64", name="ck_quota_reservation_intent"),
        CheckConstraint(
            "(state IN ('allowed', 'denied') AND refunded_at IS NULL AND settled_at IS NULL) OR "
            "(state = 'refunded' AND refunded_at IS NOT NULL AND settled_at IS NULL) OR "
            "(state = 'settled' AND settled_at IS NOT NULL AND refunded_at IS NULL)",
            name="ck_quota_reservation_state",
        ),
        UniqueConstraint(
            "user_id", "dimension", "period", "intent_fingerprint",
            name="uq_quota_reservation_intent",
        ),
        Index("ix_quota_reservations_account", "user_id", "dimension", "period"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(8), nullable=False)
    window: Mapped[str] = mapped_column(String(8), nullable=False)
    intent_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    cost: Mapped[int] = mapped_column(BigInteger, nullable=False)
    limit_value: Mapped[Optional[int]] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    used_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    refunded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
