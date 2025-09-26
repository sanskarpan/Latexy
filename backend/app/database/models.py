"""Database models for Latexy application."""

from datetime import datetime
from typing import Optional, List
from uuid import uuid4

from sqlalchemy import (
    String, Integer, Boolean, Text, DateTime, Float, JSON, ARRAY, 
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID, INET
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

class UserAPIKey(Base):
    """User API keys for BYOK (Bring Your Own Key) functionality."""
    __tablename__ = "user_api_keys"
    
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # 'openai', 'anthropic', 'gemini'
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="resumes")
    compilations: Mapped[List["Compilation"]] = relationship("Compilation", back_populates="resume")
    optimizations: Mapped[List["Optimization"]] = relationship("Optimization", back_populates="resume", cascade="all, delete-orphan")

class Compilation(Base):
    """Compilation history for tracking LaTeX compilations."""
    __tablename__ = "compilations"
    
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    resume_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="SET NULL"))
    device_fingerprint: Mapped[Optional[str]] = mapped_column(String(255), index=True)  # For anonymous users
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
    user_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    resume_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    job_description: Mapped[str] = mapped_column(Text, nullable=False)
    original_latex: Mapped[str] = mapped_column(Text, nullable=False)
    optimized_latex: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    optimization_time: Mapped[Optional[float]] = mapped_column(Float)
    ats_score: Mapped[Optional[dict]] = mapped_column(JSON)  # Store ATS scoring data
    changes_made: Mapped[Optional[dict]] = mapped_column(JSON)  # Store change log
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="optimizations")
    resume: Mapped["Resume"] = relationship("Resume", back_populates="optimizations")

class UsageAnalytics(Base):
    """Usage analytics for tracking user behavior."""
    __tablename__ = "usage_analytics"
    
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    device_fingerprint: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)  # 'compile', 'optimize', 'download'
    resource_type: Mapped[Optional[str]] = mapped_column(String(50))  # 'resume', 'template'
    event_metadata: Mapped[Optional[dict]] = mapped_column(JSON)
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="usage_analytics")

class Subscription(Base):
    """Subscription management."""
    __tablename__ = "subscriptions"
    
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    razorpay_subscription_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    plan_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # 'active', 'cancelled', 'past_due'
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
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # Amount in paise
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="payments")
    subscription: Mapped[Optional["Subscription"]] = relationship("Subscription", back_populates="payments")

# Create indexes for performance
Index('idx_users_email', User.email)
Index('idx_device_trials_fingerprint', DeviceTrial.device_fingerprint)
Index('idx_device_trials_ip', DeviceTrial.ip_address)
Index('idx_resumes_user_id', Resume.user_id)
Index('idx_compilations_user_id', Compilation.user_id)
Index('idx_compilations_device', Compilation.device_fingerprint)
Index('idx_optimizations_user_id', Optimization.user_id)
Index('idx_usage_analytics_user_id', UsageAnalytics.user_id)
Index('idx_usage_analytics_device', UsageAnalytics.device_fingerprint)
Index('idx_subscriptions_user_id', Subscription.user_id)
