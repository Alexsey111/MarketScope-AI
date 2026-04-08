#app\models\job.py
"""
Job model for async analysis tasks.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel


class JobStatus(str, Enum):
    PENDING = "pending"
    STARTED = "started"
    RETRY = "retry"
    SUCCESS = "success"
    FAILURE = "failure"


class Job(BaseModel):
    """Async job model."""
    id: str
    status: JobStatus = JobStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: int = 0
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    attempts: int = 0

    class Config:
        from_attributes = True


class JobCreate(BaseModel):
    """Request to create a job."""
    title: str
    description: str
    project_id: Optional[int] = None
    niche: Optional[str] = None


class JobResponse(BaseModel):
    """Job response."""
    id: str
    status: JobStatus
    progress: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
