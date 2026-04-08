#services\tenant_db.py
"""
Multi-tenant database models for PostgreSQL.
"""
from datetime import datetime
from enum import Enum
from typing import Optional
import re
from pydantic import BaseModel, Field, field_validator


# ==============================
# ENUMS
# ==============================

class UserRole(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    ANALYST = "analyst"
    VIEWER = "viewer"


class Plan(str, Enum):
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ==============================
# MODELS
# ==============================

class Tenant(BaseModel):
    id: Optional[int] = None
    name: str
    plan: Plan = Plan.FREE
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class User(BaseModel):
    id: Optional[int] = None
    tenant_id: int
    email: str
    role: UserRole = UserRole.VIEWER
    hashed_password: str
    is_active: bool = True
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email address")
        return v


class Project(BaseModel):
    id: Optional[int] = None
    tenant_id: int
    name: str
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class Analysis(BaseModel):
    id: Optional[int] = None
    tenant_id: int
    project_id: Optional[int] = None
    user_id: int
    title: str
    description: str
    scoring_version: str = "v4.0"
    final_score: Optional[float] = None
    confidence: Optional[float] = None
    risk_penalty: Optional[float] = None
    risk_flags: list = Field(default_factory=list)
    feature_vector: Optional[dict] = None
    analysis_result: Optional[dict] = None
    status: AnalysisStatus = AnalysisStatus.PENDING
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UsageLog(BaseModel):
    id: Optional[int] = None
    tenant_id: int
    user_id: int
    endpoint: str
    tokens_used: int = 0
    latency_ms: float = 0
    status_code: int = 200
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
