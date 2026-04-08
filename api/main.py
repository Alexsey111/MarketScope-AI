#api\main.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import time
from app.core.scoring_v4 import scoring_engine, ScoringInput
from api.routers import analysis
from api.routers.tenant_analyses import router as tenant_router
from api.routers.celery_analysis import router as celery_router
from api.routers.async_analysis import router as async_router
from api.routers import auth 
from services.tenant_service import init_db as init_tenant_db
from services.usage_tracker import init_db as init_usage_tracker_db



app = FastAPI(
    title="MarketScope API",
    version="4.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Include routers
app.include_router(auth.router, tags=["auth"])
app.include_router(analysis.router, prefix="/api", tags=["analysis"])
app.include_router(tenant_router, tags=["tenant"])
app.include_router(celery_router, tags=["celery"])
app.include_router(async_router, tags=["async-analysis"])


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В prod замени на список доменов
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DOS Protection: Limit request body size
MAX_BODY_SIZE = 100 * 1024  # 100KB


@app.middleware("http")
async def dos_protection_middleware(request: Request, call_next):
    """Middleware for DOS protection."""
    # Check content length
    content_length = request.headers.get("content-length")

    if content_length and int(content_length) > MAX_BODY_SIZE:
        return JSONResponse(
            status_code=413,
            content={
                "error": "Payload too large",
                "message": f"Maximum body size is {MAX_BODY_SIZE/1024}KB"
            }
        )

    # Rate limiting headers
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time

    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Content-Type-Options"] = "nosniff"

    return response


# Security headers
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers."""
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.on_event("startup")
def startup_event():
    """Initialize database tables on application startup."""
    init_tenant_db()
    init_usage_tracker_db()


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "version": "4.0",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/score")
def score(data: ScoringInput):
    return scoring_engine.calculate(data)
