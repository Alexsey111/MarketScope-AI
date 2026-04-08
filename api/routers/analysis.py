#api\routers\analysis.py
import time
import json
import asyncio
import logging
from typing import AsyncIterator
from fastapi import APIRouter, HTTPException, Request, Depends, status

logger = logging.getLogger(__name__)
from sqlalchemy.orm import Session
from services.auth import get_current_tenant, TenantContext
from services.subscription import check_monthly_quota, QuotaExceeded
from services.tenant_service import get_db, get_tenant
from app.core.scoring_v4 import (
    scoring_engine,
    ScoringInput,
    Niche,
    SCORING_VERSION,
)
from services.scoring_engine import (
    build_feature_vector,
    detect_niche,
    build_analysis_prompt,
    parse_llm_analysis,
    AnalysisResponse,
    ScoringResult,
    AnalysisRequest,
    validate_input_length,
    validate_llm_output,
    LLMValidationError,
    LLMScoringMetrics,
    LLMAnalysisResponse,
    sanitize_input,
)
from services.llm_service import generate_json as llm_generate_json, generate_json_stream
from services.rate_limiter import rate_limiter
from services.database import save_history
from services.cache import analysis_cache
from services.usage_tracker import usage_tracker
from services.llm_service import set_deterministic_mode, get_llm_config, llm_config, LLM_TIMEOUT
from services.security import log_analysis_request, log_security_event, log_error_with_context

router = APIRouter()


@router.post("/analysis", response_model=AnalysisResponse)
async def full_analysis(
    payload: AnalysisRequest,
    request: Request,
    tenant: TenantContext = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    start_time = time.time()
    tokens_used = 0

    # ========== PRE-FLIGHT CHECKS ==========

    # 1️⃣ Rate limiting (IP-based)
    client_ip = request.client.host if request.client else "unknown"
    allowed, limit_info = await rate_limiter.check_limit(client_ip)

    if not allowed:
        log_security_event("rate_limit_exceeded", {
            "client_ip": client_ip,
            "limit_info": limit_info
        })
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit_info": limit_info
            }
        )

    # 2️⃣ Subscription quota check
    tenant_obj = get_tenant(db, tenant.tenant_id)
    if tenant_obj:
        try:
            check_monthly_quota(db, tenant.tenant_id, tenant_obj.plan)
        except QuotaExceeded as e:
            log_security_event("quota_exceeded", {
                "tenant_id": tenant.tenant_id,
                "plan": tenant_obj.plan,
                "error": str(e)
            })
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "Usage limit exceeded",
                    "message": str(e),
                    "upgrade_url": "/pricing"
                }
            )

    # 3️⃣ Input validation
    try:
        validate_input_length(payload.title, payload.description)
    except ValueError as e:
        log_security_event("input_validation_failed", {
            "user_id": tenant.user_id,
            "error": str(e)
        })
        raise HTTPException(status_code=400, detail=str(e))

    # 4️⃣ Sanitize input
    title, description = sanitize_input(payload.title, payload.description)

    # Log request (sanitized - no full description)
    log_analysis_request(
        "analysis_request",
        {"title": title[:50], "user_id": tenant.user_id},
        tenant.user_id
    )

    # ========== CACHE CHECK ==========

    cached_result = await analysis_cache.get(title, description)

    if cached_result:
        usage_tracker.log(
            user_id=tenant.user_id,
            tokens_used=0,
            analysis_time_ms=(time.time() - start_time) * 1000,
            scoring_version=SCORING_VERSION,
            niche=cached_result["niche"],
            final_score=cached_result["scoring"]["final_score"],
            cached=True
        )

        scoring_result = ScoringResult(**cached_result["scoring"])
        return AnalysisResponse(
            niche=cached_result["niche"],
            scoring=scoring_result,
            confidence=cached_result["confidence"],
            analysis=cached_result["analysis"]
        )

    # ========== PIPELINE ==========

    try:
        # Step 1: Detect niche
        niche = await detect_niche(llm_generate_json, title, description)
        tokens_used += 100

    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail={
                "error": "Niche detection timeout",
                "message": f"LLM timeout after {LLM_TIMEOUT}s",
                "version": SCORING_VERSION
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Niche detection failed",
                "message": str(e),
                "version": SCORING_VERSION
            }
        )

    try:
        # Step 2: Get LLM analysis
        raw_analysis = await llm_generate_json(
            build_analysis_prompt(title, description)
        )
        tokens_used += 500

    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail={
                "error": "Analysis timeout",
                "message": f"LLM timeout after {LLM_TIMEOUT}s",
                "version": SCORING_VERSION
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "LLM analysis failed",
                "message": str(e),
                "version": SCORING_VERSION
            }
        )

    try:
        # Step 3: Validate LLM output
        llm_analysis = validate_llm_output(
            LLMAnalysisResponse,
            raw_analysis,
            context="analysis"
        )

    except LLMValidationError:
        # Fallback with defaults
        llm_analysis = parse_llm_analysis(raw_analysis)

    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Invalid LLM structure",
                "message": f"Validation failed: {str(e)}",
                "version": SCORING_VERSION
            }
        )

    try:
        # Step 4: Build scoring input
        scoring_input = ScoringInput(
            niche=niche,
            **llm_analysis.scoring_metrics.model_dump()
        )

    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Invalid scoring input",
                "message": str(e),
                "version": SCORING_VERSION
            }
        )

    try:
        # Step 5: Calculate scores
        score_result = scoring_engine.calculate(scoring_input)

    except Exception as e:
        log_error_with_context("scoring_calculation_failed", e, {
            "user_id": tenant.user_id,
            "niche": niche.value if 'niche' in dir() else "unknown"
        })
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Scoring calculation failed",
                "message": str(e),
                "version": SCORING_VERSION
            }
        )

    try:
        # Step 6: Feature vector
        feature_vector = build_feature_vector(scoring_input)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Feature extraction failed",
                "message": str(e),
                "version": SCORING_VERSION
            }
        )

    # ========== POST-PROCESSING ==========

    try:
        # Save to history
        save_history(
            user_id=tenant.user_id,
            text=f"{title}\n{description}",
            score=score_result["final_score"],
            scoring_version=SCORING_VERSION,
            feature_vector={
                "numeric": feature_vector.numeric,
                "categorical": feature_vector.categorical,
                "feature_names": feature_vector.feature_names,
                "categorical_names": feature_vector.categorical_names,
                "niche": feature_vector.niche
            }
        )

        # Cache result
        result_to_cache = {
            "niche": niche.value,
            "scoring": score_result,
            "confidence": score_result["confidence_score"],
            "analysis": llm_analysis.model_dump()
        }
        await analysis_cache.set(title, description, result_to_cache)

    except Exception:
        # Non-critical: log but don't fail
        pass

    # Log usage
    usage_tracker.log(
        user_id=tenant.user_id,
        tokens_used=tokens_used,
        analysis_time_ms=(time.time() - start_time) * 1000,
        scoring_version=SCORING_VERSION,
        niche=niche.value,
        final_score=score_result["final_score"],
        cached=False
    )

    # Build response
    scoring_result = ScoringResult(**score_result)

    return AnalysisResponse(
        niche=niche.value,
        scoring=scoring_result,
        confidence=score_result["confidence_score"],
        analysis=llm_analysis.model_dump()
    )


@router.get("/usage")
async def get_usage_stats(user_id: int = None, days: int = 30):
    """Get usage statistics."""
    return usage_tracker.get_stats(user_id=user_id, days=days)


@router.post("/config/deterministic")
async def toggle_deterministic_mode(enabled: bool = True):
    """Toggle deterministic mode for enterprise clients."""
    set_deterministic_mode(enabled)
    return {
        "deterministic_mode": enabled,
        "llm_config": get_llm_config()
    }


@router.get("/config")
async def get_config():
    """Get current LLM configuration."""
    return get_llm_config()


# ==============================
# BATCH ANALYSIS
# ==============================

from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class BatchItem(BaseModel):
    """Single item in batch analysis."""
    id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    # Direct scoring metrics (bypass LLM)
    niche: Optional[str] = "default"
    completeness: Optional[float] = 50
    seo_score: Optional[float] = 50
    usp_score: Optional[float] = 50
    visual_quality: Optional[float] = 50
    price_position: Optional[float] = 50
    competition_intensity: Optional[float] = 50
    differentiation: Optional[float] = 50
    entry_barrier: Optional[float] = 50
    demand_proxy: Optional[float] = 50
    price_alignment: Optional[float] = 50
    category_maturity: Optional[float] = 50
    brand_dependency: Optional[float] = 50
    logistics_complexity: Optional[float] = 50
    margin_percent: Optional[float] = 25
    upsell_potential: Optional[float] = 50
    repeat_purchase: Optional[float] = 50
    expansion_vector: Optional[float] = 50


class BatchAnalysisRequest(BaseModel):
    """Request model for batch analysis."""
    items: List[Dict[str, Any]]
    calibration_params: Optional[Dict[str, float]] = None
    api_key: Optional[str] = None
    temperature: Optional[float] = 0.2


class BatchItemResult(BaseModel):
    """Result for single item in batch."""
    id: Optional[str] = None
    score: float
    confidence: float
    product_score: Optional[float] = None
    market_score: Optional[float] = None
    platform_score: Optional[float] = None
    growth_score: Optional[float] = None
    risk_penalty: Optional[float] = None
    risk_flags: Optional[List[str]] = None
    error: Optional[str] = None


class BatchAnalysisResponse(BaseModel):
    """Response model for batch analysis."""
    task_id: str
    status: str
    message: str


@router.post("/analysis/batch", response_model=BatchAnalysisResponse)
async def create_batch_analysis(payload: BatchAnalysisRequest, request: Request):
    """
    Create batch analysis task.

    Payload:
        {
            "items": [
                {"id": "item_1", "title": "...", "description": "..."},
                {"id": "item_2", "title": "...", "description": "..."},
                ...
            ],
            "calibration_params": {"scale": 1.0, "offset": 0.0},  # optional
            "api_key": "...",  # optional
            "temperature": 0.2  # optional
        }

    Returns task_id for checking status via GET /tasks/{task_id}
    """
    # Rate limiting
    client_ip = request.client.host if request.client else "unknown"
    allowed, limit_info = await rate_limiter.check_limit(client_ip)

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "limit_info": limit_info}
        )

    # Validate items count
    if not payload.items:
        raise HTTPException(
            status_code=400,
            detail={"error": "Items list cannot be empty"}
        )

    max_batch_size = 100
    if len(payload.items) > max_batch_size:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Batch size exceeds maximum of {max_batch_size}",
                "current_size": len(payload.items)
            }
        )

    # Import Celery task
    from app.tasks.analysis_tasks import run_batch_analysis
    import uuid

    # Create task
    task_id = str(uuid.uuid4())

    run_batch_analysis.apply_async(
        args=[{
            "items": payload.items,
            "calibration_params": payload.calibration_params,
            "api_key": payload.api_key,
            "temperature": payload.temperature
        }],
        task_id=task_id
    )

    log_analysis_request(
        "batch_analysis_request",
        {"items_count": len(payload.items), "task_id": task_id},
        None
    )

    return BatchAnalysisResponse(
        task_id=task_id,
        status="queued",
        message=f"Batch task created with {len(payload.items)} items"
    )


@router.get("/analysis/batch/{task_id}")
async def get_batch_result(task_id: str):
    """Get batch analysis result by task_id."""
    from celery_app import celery_app

    # Get task result
    result = celery_app.AsyncResult(task_id)

    if result.state == "PENDING":
        return {
            "task_id": task_id,
            "status": "pending",
            "message": "Task is still processing"
        }

    if result.state == "PROGRESS":
        return {
            "task_id": task_id,
            "status": "processing",
            "progress": result.info
        }

    if result.state == "FAILURE":
        return {
            "task_id": task_id,
            "status": "failed",
            "error": str(result.info)
        }

    # Success
    return {
        "task_id": task_id,
        "status": "completed",
        "result": result.result
    }


# ==============================
# STREAMING ANALYSIS
# ==============================

from fastapi.responses import StreamingResponse


@router.post("/analysis/stream")
async def analyze_stream(
    payload: AnalysisRequest,
    request: Request,
    tenant: TenantContext = Depends(get_current_tenant)
):
    """
    Stream analysis results for long responses.
    
    Returns NDJSON stream with progressive results:
    - First chunk: niche detection
    - Middle chunks: scoring progress
    - Final chunk: complete analysis
    """
    # Rate limiting
    client_ip = request.client.host if request.client else "unknown"
    allowed, limit_info = await rate_limiter.check_limit(client_ip)
    
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "limit_info": limit_info}
        )
    
    # Validate input
    try:
        validate_input_length(payload.title, payload.description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Sanitize
    title, description = sanitize_input(payload.title, payload.description)
    
    # Build prompt
    prompt = build_analysis_prompt(title, description)
    
    async def event_generator() -> AsyncIterator[str]:
        """Generate NDJSON stream events."""
        try:
            # Stream LLM response
            async for chunk in generate_json_stream(prompt):
                # NDJSON format: each line is a separate JSON object
                yield f'data: {json.dumps({"type": "chunk", "content": chunk})}\n\n'
            
            # Send completion event
            yield f'data: {json.dumps({"type": "done"})}\n\n'
            
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield f'data: {json.dumps({"type": "error", "error": str(e)})}\n\n'
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )
