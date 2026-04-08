"""
Async analysis API endpoints.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.tasks.analysis_tasks import create_async_analysis
from app.models.job import JobStatus
from services.auth import get_current_tenant, TenantContext
from services.tenant_service import get_db


router = APIRouter(prefix="/api/async", tags=["async-analysis"])


# ==============================
# REQUEST/RESPONSE MODELS
# ==============================

class AsyncAnalysisRequest(BaseModel):
    """Request for async analysis."""
    title: str
    description: str
    project_id: Optional[int] = None


class AsyncAnalysisResponse(BaseModel):
    """Response for async analysis creation."""
    job_id: str
    status: str
    message: str


class AsyncAnalysisStatus(BaseModel):
    """Status of async analysis."""
    job_id: str
    status: JobStatus
    progress: int
    result: Optional[dict] = None
    error: Optional[str] = None


# ==============================
# ENDPOINTS
# ==============================

@router.post("/analyses", response_model=AsyncAnalysisResponse)
async def create_analysis_async(
    payload: AsyncAnalysisRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    db=Depends(get_db),
):
    """
    Create async analysis job.

    Returns job_id immediately. Poll /analyses/{job_id} for status.
    """
    job_id = create_async_analysis(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        title=payload.title,
        description=payload.description,
    )

    return AsyncAnalysisResponse(
        job_id=job_id,
        status="pending",
        message="Analysis queued. Use job_id to check status.",
    )


@router.get("/analyses/{job_id}", response_model=AsyncAnalysisStatus)
async def get_analysis_status(
    job_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db=Depends(get_db),
):
    """
    Get status of async analysis job.
    """
    from services.tenant_service import AnalysisDB
    import json

    analysis = db.query(AnalysisDB).filter(
        AnalysisDB.id == int(job_id),
        AnalysisDB.tenant_id == tenant.tenant_id,
    ).first()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Determine progress
    if analysis.status in ("pending",):
        progress = 0
    elif analysis.status in ("processing", "started"):
        progress = 50
    elif analysis.status in ("completed", "success"):
        progress = 100
    else:
        progress = 0

    result = None
    if analysis.analysis_result:
        try:
            result = json.loads(analysis.analysis_result)
        except Exception:
            result = None

    return AsyncAnalysisStatus(
        job_id=str(analysis.id),
        status=JobStatus(analysis.status),
        progress=progress,
        result=result,
        error=analysis.error_message,
    )


@router.post("/analyses/{job_id}/retry")
async def retry_analysis(
    job_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db=Depends(get_db),
):
    """
    Retry failed analysis.
    """
    from services.tenant_service import AnalysisDB
    from app.tasks.analysis_tasks import retry_failed_analysis

    analysis = db.query(AnalysisDB).filter(
        AnalysisDB.id == int(job_id),
        AnalysisDB.tenant_id == tenant.tenant_id,
    ).first()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    if analysis.status not in ["failed", "failure"]:
        raise HTTPException(
            status_code=400,
            detail="Can only retry failed analyses",
        )

    result = retry_failed_analysis(int(job_id))

    return {
        "status": "retrying",
        "new_job_id": result.get("new_job_id"),
    }

