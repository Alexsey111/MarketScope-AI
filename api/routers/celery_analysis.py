from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from celery_app import celery_app
from app.tasks.analysis_tasks import create_async_analysis, process_analysis
from services.auth import get_current_tenant, TenantContext
from services.subscription import check_monthly_quota, QuotaExceeded
from services.tenant_service import get_db, get_tenant, AnalysisDB


router = APIRouter(prefix="/api/celery", tags=["celery"])


# ==============================
# REQUEST MODELS
# ==============================

class AnalysisPayload(BaseModel):
    """Payload for analysis task."""
    title: str
    description: str
    niche: Optional[str] = "default"

    # Optional scoring metrics (if not provided, LLM will estimate)
    completeness: Optional[float] = None
    seo_score: Optional[float] = None
    usp_score: Optional[float] = None
    visual_quality: Optional[float] = None
    price_position: Optional[float] = None
    competition_intensity: Optional[float] = None
    differentiation: Optional[float] = None
    entry_barrier: Optional[float] = None
    demand_proxy: Optional[float] = None
    price_alignment: Optional[float] = None
    category_maturity: Optional[float] = None
    brand_dependency: Optional[float] = None
    logistics_complexity: Optional[float] = None
    margin_percent: Optional[float] = None
    upsell_potential: Optional[float] = None
    repeat_purchase: Optional[float] = None
    expansion_vector: Optional[float] = None


class AnalysisResponse(BaseModel):
    """Response for analysis creation."""
    job_id: str
    status: str
    message: str


class AnalysisStatus(BaseModel):
    """Status response."""
    job_id: str
    status: str
    ready: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ==============================
# ENDPOINTS
# ==============================

@router.post("/analysis", response_model=AnalysisResponse)
async def create_analysis(
    payload: AnalysisPayload,
    tenant: TenantContext = Depends(get_current_tenant),
    db=Depends(get_db),
):
    """
    Create async analysis job via Celery.
    """
    try:
        tenant_obj = get_tenant(db, tenant.tenant_id)
        plan = tenant_obj.plan if tenant_obj else "free"
        check_monthly_quota(db, tenant.tenant_id, plan)
    except QuotaExceeded as e:
        raise HTTPException(status_code=403, detail=str(e))

    task_id = create_async_analysis(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        title=payload.title,
        description=payload.description,
    )

    return AnalysisResponse(
        job_id=task_id,
        status="pending",
        message="Analysis queued. Use job_id to check status.",
    )


@router.get("/analysis/{job_id}", response_model=AnalysisStatus)
async def get_result(job_id: str):
    """
    Get analysis result by job_id.
    """
    result = celery_app.AsyncResult(job_id)

    if result.ready():
        if result.successful():
            return AnalysisStatus(
                job_id=job_id,
                status="success",
                ready=True,
                result=result.result,
            )
        return AnalysisStatus(
            job_id=job_id,
            status="failed",
            ready=True,
            error=str(result.info),
        )

    state = result.state
    if state == "PENDING":
        status = "pending"
    elif state == "STARTED":
        status = "processing"
    elif state == "RETRY":
        status = "retrying"
    else:
        status = "unknown"

    return AnalysisStatus(
        job_id=job_id,
        status=status,
        ready=False,
    )


@router.post("/analysis/{job_id}/retry", response_model=AnalysisResponse)
async def retry_analysis(job_id: str):
    """
    Retry failed analysis.
    """
    result = celery_app.AsyncResult(job_id)

    if result.ready() and result.successful():
        raise HTTPException(
            status_code=400,
            detail="Cannot retry successful analysis",
        )

    from services.tenant_service import get_db

    db = next(get_db())
    try:
        analysis = db.query(AnalysisDB).filter(AnalysisDB.id == int(job_id)).first()
        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis not found")

        task = process_analysis.apply_async(
            args=[analysis.id],
            kwargs={
                "data": {
                    "title": analysis.title,
                    "description": analysis.description,
                    "tenant_id": analysis.tenant_id,
                    "user_id": analysis.user_id,
                }
            },
            task_id=str(analysis.id),
        )
    finally:
        db.close()

    return AnalysisResponse(
        job_id=task.id,
        status="retry",
        message="Analysis retry queued",
    )


@router.delete("/analysis/{job_id}")
async def revoke_analysis(job_id: str):
    """
    Revoke (cancel) running analysis.
    """
    celery_app.control.revoke(job_id, terminate=True)

    return {"message": f"Analysis {job_id} revoked"}
