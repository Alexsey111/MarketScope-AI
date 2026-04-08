"""
SQLAlchemy models for PostgreSQL database.
Multi-tenant architecture with proper indexing and relationships.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime,
    ForeignKey, Text, JSON, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.dialects.postgresql import JSONB  # Faster than JSON

Base = declarative_base()


class TenantDB(Base):
    """Organization/Company in multi-tenant architecture."""
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    plan = Column(String(50), default="free", index=True)
    
    # Quota tracking
    analyses_limit = Column(Integer, default=5)  # Per month
    requests_per_minute = Column(Integer, default=5)
    tokens_per_day = Column(Integer, default=10000)
    
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    users = relationship("UserDB", back_populates="tenant", cascade="all, delete-orphan")
    projects = relationship("ProjectDB", back_populates="tenant", cascade="all, delete-orphan")
    analyses = relationship("AnalysisDB", back_populates="tenant", cascade="all, delete-orphan")
    usage_logs = relationship("UsageLogDB", back_populates="tenant", cascade="all, delete-orphan")


class UserDB(Base):
    """User within a tenant."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Integer, 
        ForeignKey("tenants.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="viewer")  # admin, editor, viewer
    is_active = Column(Boolean, default=True, index=True)
    
    # Additional fields
    full_name = Column(String(255))
    last_login = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tenant = relationship("TenantDB", back_populates="users")
    analyses = relationship("AnalysisDB", back_populates="user")
    usage_logs = relationship("UsageLogDB", back_populates="user")
    usage_counters = relationship("UsageCounter", back_populates="user")


class ProjectDB(Base):
    """Project for organizing analyses."""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Integer, 
        ForeignKey("tenants.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    name = Column(String(255), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tenant = relationship("TenantDB", back_populates="projects")
    analyses = relationship("AnalysisDB", back_populates="project")

    # Constraints
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_project_tenant_name"),
    )


class AnalysisDB(Base):
    """Product card analysis result."""
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Integer, 
        ForeignKey("tenants.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    user_id = Column(
        Integer, 
        ForeignKey("users.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    project_id = Column(
        Integer, 
        ForeignKey("projects.id", ondelete="SET NULL"), 
        nullable=True,
        index=True
    )

    # Input data
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)

    # Scoring results
    scoring_version = Column(String(20), default="v4.0", index=True)
    final_score = Column(Float, index=True)  # For filtering by score
    confidence = Column(Float)
    risk_penalty = Column(Float)
    risk_flags = Column(JSONB, default=list)  # ✅ Changed to JSONB
    
    # Detailed analysis
    feature_vector = Column(JSONB)  # All metrics
    analysis_result = Column(JSONB)  # Full LLM response
    
    # Metadata
    niche = Column(String(50), index=True)  # Denormalized for quick filtering
    status = Column(String(50), default="pending", index=True)
    error_message = Column(Text)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime)
    deleted_at = Column(DateTime, nullable=True, index=True)  # Soft delete

    # Relationships
    tenant = relationship("TenantDB", back_populates="analyses")
    user = relationship("UserDB", back_populates="analyses")
    project = relationship("ProjectDB", back_populates="analyses")

    # Indexes for common queries
    __table_args__ = (
        Index("idx_analyses_tenant_created", "tenant_id", "created_at"),
        Index("idx_analyses_tenant_status", "tenant_id", "status"),
        Index("idx_analyses_user_created", "user_id", "created_at"),
        Index("idx_analyses_score_range", "tenant_id", "final_score"),
        Index("idx_analyses_niche", "tenant_id", "niche"),
        # GIN index for JSON queries
        Index("idx_analyses_risk_flags", "risk_flags", postgresql_using="gin"),
    )


class UsageLogDB(Base):
    """API usage tracking for billing and rate limiting."""
    __tablename__ = "usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Integer, 
        ForeignKey("tenants.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    user_id = Column(
        Integer, 
        ForeignKey("users.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    endpoint = Column(String(255), nullable=False, index=True)
    method = Column(String(10), default="POST")  # GET, POST, PUT, DELETE
    tokens_used = Column(Integer, default=0)
    latency_ms = Column(Float, default=0.0)
    status_code = Column(Integer, default=200, index=True)
    
    # Additional context
    ip_address = Column(String(45))  # IPv6 support
    user_agent = Column(String(500))
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    tenant = relationship("TenantDB", back_populates="usage_logs")
    user = relationship("UserDB", back_populates="usage_logs")

    # Indexes
    __table_args__ = (
        Index("idx_usage_tenant_created", "tenant_id", "created_at"),
        Index("idx_usage_user_created", "user_id", "created_at"),
    )


class JobDB(Base):
    """Celery task tracking."""
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True)  # UUID from Celery
    task_name = Column(String(255), index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    
    status = Column(String(50), default="pending", index=True)
    result = Column(JSONB)  # ✅ Changed to JSONB
    error = Column(Text)
    progress = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    attempts = Column(Integer, default=0)

    __table_args__ = (
        Index("idx_jobs_status_created", "status", "created_at"),
    )


class HistoryDB(Base):
    """Legacy analysis history (can be migrated to AnalysisDB)."""
    __tablename__ = "history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, 
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, 
        index=True
    )
    text = Column(Text, nullable=False)
    score = Column(Float, index=True)
    scoring_version = Column(String(20), default="v4.0")
    feature_vector = Column(JSONB)  # ✅ Changed to JSONB
    analysis_status = Column(String(50), default="pending", index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    user = relationship("UserDB")


class UsageCounter(Base):
    """Daily usage counter for quota enforcement."""
    __tablename__ = "usage_counters"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, 
        ForeignKey("users.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    date = Column(DateTime, nullable=False)  # Truncated to day (YYYY-MM-DD 00:00:00)
    count = Column(Integer, default=0)
    tokens_used = Column(Integer, default=0)

    # Relationship
    user = relationship("UserDB", back_populates="usage_counters")

    # Unique constraint: one counter per user per day
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_usage_counter_user_date"),
        Index("idx_usage_counter_date", "date"),
    )
