"""
Multi-tenant analysis router with tenant isolation.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from services.tenant_service import (
    get_db,
    create_analysis,
    update_analysis,
    get_analyses,
    log_usage,
    get_tenant
)
from services.tenant_db import AnalysisStatus
from services.auth import get_current_tenant, TenantContext
from app.core.scoring_v4 import ScoringInput, Niche
from services.subscription import (
    check_monthly_quota,
    check_rate_limit,
    get_tenant_usage,
    QuotaExceeded,
    PLAN_LIMITS,
    PLAN_RATE_LIMITS
)

router = APIRouter(prefix="/api/tenant", tags=["tenant-analyses"])


# ==============================
# REQUEST/RESPONSE MODELS
# ==============================

class AnalysisCreate(BaseModel):
    title: str
    description: str
    project_id: Optional[int] = None


class AnalysisResponse(BaseModel):
    id: int
    title: str
    status: str
    final_score: Optional[float] = None
    confidence: Optional[float] = None
    scoring_version: str


class AnalysisListResponse(BaseModel):
    analyses: list[AnalysisResponse]
    total: int


class AnalysisCompleteRequest(BaseModel):
    final_score: float
    confidence: float
    risk_penalty: float
    risk_flags: list[str] = Field(default_factory=list)


# ==============================
# ENDPOINTS
# ==============================

@router.post("/analyses", response_model=AnalysisResponse)
async def create_tenant_analysis(
    payload: AnalysisCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Create new analysis for tenant.
    Automatically isolates by tenant_id.
    Checks subscription limits before creating.
    """
    # Get tenant plan
    tenant_obj = get_tenant(db, tenant.tenant_id)
    plan = tenant_obj.plan if tenant_obj else "free"

    # Check monthly quota
    try:
        check_monthly_quota(db, tenant.tenant_id, plan)
    except QuotaExceeded as e:
        raise HTTPException(status_code=403, detail=str(e))

    # Check rate limits
    try:
        check_rate_limit(db, tenant.tenant_id, plan)
    except QuotaExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))

    analysis = create_analysis(
        db=db,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        title=payload.title,
        description=payload.description
    )

    # Log usage
    log_usage(
        db=db,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        endpoint="/api/tenant/analyses",
        status_code=201
    )

    return AnalysisResponse(
        id=analysis.id,
        title=analysis.title,
        status=analysis.status,
        final_score=analysis.final_score,
        confidence=analysis.confidence,
        scoring_version=analysis.scoring_version
    )


@router.get("/analyses", response_model=AnalysisListResponse)
async def list_tenant_analyses(
    project_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 20,
    tenant: TenantContext = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    List analyses for current tenant.
    Automatically filtered by tenant_id - no cross-tenant access!
    """
    analyses = get_analyses(
        db=db,
        tenant_id=tenant.tenant_id,
        project_id=project_id,
        skip=skip,
        limit=limit
    )

    return AnalysisListResponse(
        analyses=[
            AnalysisResponse(
                id=a.id,
                title=a.title,
                status=a.status,
                final_score=a.final_score,
                confidence=a.confidence,
                scoring_version=a.scoring_version
            )
            for a in analyses
        ],
        total=len(analyses)
    )


@router.get("/analyses/{analysis_id}", response_model=AnalysisResponse)
async def get_tenant_analysis(
    analysis_id: int,
    tenant: TenantContext = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Get analysis by ID.
    Tenant isolation: only returns if analysis belongs to tenant.
    """
    from services.tenant_service import AnalysisDB

    analysis = db.query(AnalysisDB).filter(
        AnalysisDB.id == analysis_id,
        AnalysisDB.tenant_id == tenant.tenant_id
    ).first()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return AnalysisResponse(
        id=analysis.id,
        title=analysis.title,
        status=analysis.status,
        final_score=analysis.final_score,
        confidence=analysis.confidence,
        scoring_version=analysis.scoring_version
    )


@router.patch("/analyses/{analysis_id}/complete")
async def complete_tenant_analysis(
    analysis_id: int,
    payload: AnalysisCompleteRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Mark analysis as completed with results.
    """
    analysis = update_analysis(
        db=db,
        analysis_id=analysis_id,
        tenant_id=tenant.tenant_id,
        final_score=payload.final_score,
        confidence=payload.confidence,
        risk_penalty=payload.risk_penalty,
        risk_flags=str(payload.risk_flags),  # Store as JSON string
        status=AnalysisStatus.COMPLETED.value
    )

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return {"status": "completed", "analysis_id": analysis_id}


@router.get("/usage")
async def get_tenant_usage_stats(
    tenant: TenantContext = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Get current usage statistics for tenant."""
    tenant_obj = get_tenant(db, tenant.tenant_id)
    plan = tenant_obj.plan if tenant_obj else "free"

    return get_tenant_usage(db, tenant.tenant_id, plan)


@router.get("/plans")
async def get_plans():
    """Get available plans and their limits."""
    return {
        "plans": [
            {
                "name": plan,
                "monthly_analyses": limit,
                "requests_per_minute": PLAN_RATE_LIMITS[plan]["requests_per_minute"],
                "tokens_per_day": PLAN_RATE_LIMITS[plan]["tokens_per_day"]
            }
            for plan, limit in PLAN_LIMITS.items()
        ]
    }
