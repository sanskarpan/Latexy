"""Database models for Latexy application."""

from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4

from sqlalchemy import ARRAY, JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    resumes: Mapped[List["Resume"]] = relationship("Resume", back_populates="user", cascade="all, delete-orphan")
    api_keys: Mapped[List["UserAPIKey"]] = relationship("UserAPIKey", back_populates="user", cascade="all, delete-orphan")
    compilations: Mapped[List["Compilation"]] = relationship("Compilation", back_populates="user")
    optimizations: Mapped[List["Optimization"]] = relationship("Optimization", back_populates="user")
    subscriptions: Mapped[List["Subscription"]] = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="user", cascade="all, delete-orphan")
    usage_analytics: Mapped[List["UsageAnalytics"]] = relationship("UsageAnalytics", back_populates="user")
    resume_job_matches: Mapped[List["ResumeJobMatch"]] = relationship("ResumeJobMatch", back_populates="user", cascade="all, delete-orphan")
    cover_letters: Mapped[List["CoverLetter"]] = relationship("CoverLetter", back_populates="user")
    job_applications: Mapped[List["JobApplication"]] = relationship("JobApplication", back_populates="user", cascade="all, delete-orphan")

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

class Resume(Base):
    """Resume model for storing user resumes."""
    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    latex_content: Mapped[str] = mapped_column(Text, nullable=False)
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    # Layer 3: vector embedding for semantic job matching (1536-dim OpenAI text-embedding-3-small)
    content_embedding: Mapped[Optional[List[float]]] = mapped_column(ARRAY(Float), nullable=True)
    # Per-resume settings (compiler preference, custom flags, etc.)
    # Note: "metadata" is reserved by SQLAlchemy's Declarative API, so we use
    # resume_settings as the Python attribute name while keeping the DB column "metadata".
    resume_settings: Mapped[Optional[Dict]] = mapped_column("metadata", JSONB, nullable=True, default={})
    # Shareable link token (null = not shared)
    share_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True, unique=True, index=False)
    share_token_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Variant / fork system: self-referential parent link
    parent_resume_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True, index=True
    )
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

class Compilation(Base):
    """Compilation history for tracking LaTeX compilations."""
    __tablename__ = "compilations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    # SET NULL preserves anonymous compilation records after account deletion
    user_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    resume_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="SET NULL"))
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
    resume_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    device_fingerprint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    job_description: Mapped[str] = mapped_column(Text, nullable=False)
    original_latex: Mapped[str] = mapped_column(Text, nullable=False)
    optimized_latex: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    optimization_time: Mapped[Optional[float]] = mapped_column(Float)
    ats_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    changes_made: Mapped[Optional[dict]] = mapped_column(JSON)
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
    event_metadata: Mapped[Optional[dict]] = mapped_column(JSON)
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
    subscription_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("subscriptions.id"))
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="payments")
    subscription: Mapped[Optional["Subscription"]] = relationship("Subscription", back_populates="payments")

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
        UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
