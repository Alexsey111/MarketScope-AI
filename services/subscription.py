"""
Subscription plan limits and quota management.
"""
from enum import Enum
from typing import Dict
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, DateTime, ForeignKey, func
from services.database import Base, SessionLocal
from config import FREE_DAILY_LIMIT, PRO_DAILY_LIMIT

# Plan limits: max analyses per month
PLAN_LIMITS: Dict[str, int] = {
    "free": 5,
    "starter": 20,
    "professional": 100,
    "business": 1000,
    "enterprise": -1,  # Unlimited
}

# Rate limits: requests per minute
PLAN_RATE_LIMITS: Dict[str, Dict[str, int]] = {
    "free": {"requests_per_minute": 5, "tokens_per_day": 10000},
    "starter": {"requests_per_minute": 20, "tokens_per_day": 50000},
    "professional": {"requests_per_minute": 60, "tokens_per_day": 200000},
    "business": {"requests_per_minute": 120, "tokens_per_day": 1000000},
    "enterprise": {"requests_per_minute": -1, "tokens_per_day": -1},  # Unlimited
}


class QuotaExceeded(Exception):
    """Raised when tenant exceeds their plan limits."""
    pass


def get_plan_limit(plan: str) -> int:
    """Get monthly analysis limit for plan."""
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])


def get_rate_limit(plan: str) -> Dict[str, int]:
    """Get rate limits for plan."""
    return PLAN_RATE_LIMITS.get(plan, PLAN_RATE_LIMITS["free"])


def check_monthly_quota(
    db: Session,
    tenant_id: int,
    plan: str
) -> bool:
    """
    Check if tenant has reached their monthly analysis limit.
    Returns True if within limit, raises QuotaExceeded if not.
    """
    from services.tenant_service import AnalysisDB

    limit = get_plan_limit(plan)

    # Unlimited plan
    if limit == -1:
        return True

    # Count analyses this month
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    count = db.query(AnalysisDB).filter(
        AnalysisDB.tenant_id == tenant_id,
        AnalysisDB.created_at >= month_start,
        AnalysisDB.status.in_(["completed", "processing"])
    ).count()

    if count >= limit:
        raise QuotaExceeded(
            f"Monthly limit reached. Your plan '{plan}' allows {limit} analyses per month."
        )

    return True


def check_rate_limit(
    db: Session,
    tenant_id: int,
    plan: str,
    tokens_used: int = 0
) -> bool:
    """
    Check if tenant is within rate limits.
    Returns True if within limit, raises QuotaExceeded if not.
    """
    from services.tenant_service import UsageLogDB

    limits = get_rate_limit(plan)

    # Unlimited
    if limits["requests_per_minute"] == -1:
        return True

    # Check requests per minute
    minute_ago = datetime.utcnow() - timedelta(minutes=1)
    requests_count = db.query(UsageLogDB).filter(
        UsageLogDB.tenant_id == tenant_id,
        UsageLogDB.created_at >= minute_ago
    ).count()

    if requests_count >= limits["requests_per_minute"]:
        raise QuotaExceeded(
            f"Rate limit exceeded. Your plan allows {limits['requests_per_minute']} requests per minute."
        )

    # Check daily tokens
    day_ago = datetime.utcnow() - timedelta(days=1)
    total_tokens = (
        db.query(func.sum(UsageLogDB.tokens_used))
        .filter(
            UsageLogDB.tenant_id == tenant_id,
            UsageLogDB.created_at >= day_ago,
        )
        .scalar()
        or 0
    )

    if limits["tokens_per_day"] != -1:
        if total_tokens + tokens_used > limits["tokens_per_day"]:
            raise QuotaExceeded(
                f"Daily token limit exceeded. Your plan allows {limits['tokens_per_day']} tokens per day."
            )

    return True


def get_tenant_usage(db: Session, tenant_id: int, plan: str) -> Dict:
    """Get current usage statistics for tenant."""
    from services.tenant_service import AnalysisDB, UsageLogDB

    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    day_ago = datetime.utcnow() - timedelta(days=1)

    # Monthly analyses
    analyses_count = db.query(AnalysisDB).filter(
        AnalysisDB.tenant_id == tenant_id,
        AnalysisDB.created_at >= month_start,
        AnalysisDB.status.in_(["completed", "processing"])
    ).count()

    # Daily requests
    daily_requests = db.query(UsageLogDB).filter(
        UsageLogDB.tenant_id == tenant_id,
        UsageLogDB.created_at >= day_ago
    ).count()

    # Daily tokens
    daily_tokens = (
        db.query(func.sum(UsageLogDB.tokens_used))
        .filter(
            UsageLogDB.tenant_id == tenant_id,
            UsageLogDB.created_at >= day_ago
        )
        .scalar()
        or 0
    )

    limit = get_plan_limit(plan)
    rate_limits = get_rate_limit(plan)

    return {
        "plan": plan,
        "monthly_analyses": {
            "used": analyses_count,
            "limit": limit,
            "remaining": -1 if limit == -1 else max(0, limit - analyses_count)
        },
        "daily_requests": {
            "used": daily_requests,
            "limit": rate_limits["requests_per_minute"],
        },
        "daily_tokens": {
            "used": daily_tokens,
            "limit": rate_limits["tokens_per_day"],
        }
    }


# ==============================
# User-based daily limits
# ==============================

from services.models import UsageCounter  # ✅ Импортируем из models


async def check_usage_limit(tenant_id: int, user_id: int) -> tuple[bool, dict]:
    """Check if user has remaining quota."""
    from services.tenant_service import get_user

    db = SessionLocal()
    try:
        user = get_user(db, user_id)
        if not user:
            return False, {"error": "User not found"}

        # Determine limit based on plan
        from services.tenant_service import get_tenant
        tenant = get_tenant(db, tenant_id)

        if tenant.plan == "professional" or tenant.plan == "enterprise":
            limit = PRO_DAILY_LIMIT
        else:
            limit = FREE_DAILY_LIMIT

        # Get today's usage
        today = datetime.utcnow().date()
        usage = db.query(func.sum(UsageCounter.count)).filter(
            UsageCounter.user_id == user_id,
            func.date(UsageCounter.date) == today
        ).scalar() or 0

        allowed = usage < limit

        return allowed, {
            "used": usage,
            "limit": limit,
            "remaining": max(0, limit - usage),
            "plan": tenant.plan
        }

    finally:
        db.close()


async def increment_usage(tenant_id: int, user_id: int) -> None:
    """Increment usage counter for user."""
    db = SessionLocal()
    try:
        today = datetime.utcnow().date()

        counter = db.query(UsageCounter).filter(
            UsageCounter.user_id == user_id,
            func.date(UsageCounter.date) == today
        ).first()

        if counter:
            counter.count += 1
        else:
            counter = UsageCounter(user_id=user_id, count=1)
            db.add(counter)

        db.commit()
    finally:
        db.close()
