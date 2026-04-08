"""
Celery tasks for async analysis.
"""
import json
import uuid
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Any, Optional
from functools import wraps

from celery_app import celery_app
from app.core.scoring_v4 import scoring_engine, ScoringInput, Niche
from app.core.llm_wrapper import LLMWrapper
from app.core.calibration import calibration_engine, simple_calibrator, CalibrationLayer
from app.models.job import JobStatus
from services.tenant_service import (
    SessionLocal,
    create_analysis,
    update_analysis,
    get_analysis,
)
from config import OPENAI_API_KEY, MODEL_NAME

from celery import Task
import asyncio

logger = logging.getLogger(__name__)


# ============================================================
# SAFE ASYNC EXECUTION (prevents event loop leaks)
# ============================================================

def run_async(func):
    """
    Decorator to run async function in sync context without event loop leaks.
    
    Handles existing loop or creates new one properly.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Try to get existing loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            # No event loop exists, create new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        try:
            return loop.run_until_complete(func(*args, **kwargs))
        finally:
            # Only close if we created a new loop
            try:
                if not loop.is_closed():
                    loop.close()
            except RuntimeError:
                pass  # Loop already closed
    
    return wrapper


# ============================================================
# SAFE DB SESSION MANAGEMENT
# ============================================================

@contextmanager
def get_db_session():
    """
    Context manager for safe DB session handling.
    
    Guarantees:
    - Session is always closed, even on exceptions
    - Commit on success, rollback on error
    - No session leaks
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def update_analysis_status_safe(db, analysis_id: int, status: str, error: Optional[str] = None):
    """Update analysis status within existing session."""
    analysis = get_analysis(db, analysis_id)
    if not analysis:
        logger.warning(f"Analysis {analysis_id} not found for status update")
        return

    update_analysis(
        db=db,
        analysis_id=analysis_id,
        tenant_id=analysis.tenant_id,
        status=status,
        error_message=error,
    )


# ==============================
# LLM CLIENT INSTANCE
# ==============================

def get_llm_wrapper() -> LLMWrapper:
    """Get or create LLM wrapper instance."""
    return LLMWrapper(api_key=OPENAI_API_KEY, model=MODEL_NAME)


# ==============================
# GRACEFUL TERMINATION
# ============================================================

import signal
from celery.exceptions import SoftTimeLimitExceeded

# Task time limits (in seconds)
TASK_TIME_LIMIT = 300        # Hard limit: 5 minutes
TASK_SOFT_TIME_LIMIT = 270   # Soft limit: 4.5 minutes


def setup_signal_handlers(task_instance):
    """Register signal handlers for graceful termination."""
    def signal_handler(signum, frame):
        logger.warning(
            f"Task {task_instance.request.id} received signal {signum}, "
            f"initiating graceful shutdown..."
        )
        raise SoftTimeLimitExceeded()

    # Register handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


def handle_soft_timeout(job_id: int, db_session=None):
    """Handle soft time limit exceeded - save partial results."""
    logger.warning(f"Task soft timeout for job {job_id}, saving partial results...")
    
    try:
        # Try to update status if we have a session
        if db_session:
            update_analysis_status_safe(
                db_session,
                job_id,
                JobStatus.TIMEOUT.value,
                error="Task exceeded soft time limit (4.5 min)"
            )
    except Exception as e:
        logger.error(f"Failed to update timeout status: {e}")


# ============================================================
# PROMETHEUS METRICS (optional)
# ============================================================

import importlib

try:
    prometheus_client = importlib.import_module("prometheus_client")
    Counter = prometheus_client.Counter
    Histogram = prometheus_client.Histogram
    Gauge = prometheus_client.Gauge
    PROMETHEUS_AVAILABLE = True
except ImportError:
    # Prometheus not available - create no-op metrics
    from typing import Any
    class _NoOpCounter:
        def __init__(self, *args: Any, **kwargs: Any): pass
        def labels(self, **kwargs: Any): return self
        def inc(self, n: int = 1): pass
    class _NoOpHistogram:
        def __init__(self, *args: Any, **kwargs: Any): pass
        def labels(self, **kwargs: Any): return self
        def observe(self, n: float): pass
    class _NoOpGauge:
        def __init__(self, *args: Any, **kwargs: Any): pass
        def labels(self, **kwargs: Any): return self
        def inc(self, n: int = 1): pass
        def dec(self, n: int = 1): pass
    
    Counter = _NoOpCounter  # type: ignore
    Histogram = _NoOpHistogram  # type: ignore
    Gauge = _NoOpGauge  # type: ignore
    PROMETHEUS_AVAILABLE = False

# Define metrics
TASK_STARTED = Counter(
    'celery_task_started_total',
    'Total tasks started',
    ['task_name']
)
TASK_COMPLETED = Counter(
    'celery_task_completed_total',
    'Total tasks completed',
    ['task_name', 'status']
)
TASK_DURATION = Histogram(
    'celery_task_duration_seconds',
    'Task execution duration',
    ['task_name'],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 300.0)
)
ACTIVE_TASKS = Gauge(
    'celery_active_tasks',
    'Currently active tasks',
    ['task_name']
)
LLM_CALLS = Counter(
    'llm_calls_total',
    'Total LLM API calls',
    ['model', 'status']
)
LLM_TOKENS = Counter(
    'llm_tokens_total',
    'Total LLM tokens used',
    ['model', 'token_type']
)
LLM_COST = Counter(
    'llm_cost_usd_total',
    'Total LLM cost in USD',
    ['model']
)


class MonitoredTask(Task):
    """Task with Prometheus metrics."""
    
    def before_start(self, task_id, args, kwargs):
        """Record task start."""
        TASK_STARTED.labels(task_name=self.name).inc()
        ACTIVE_TASKS.labels(task_name=self.name).inc()
        
        # Store start time in Redis for duration calculation
        r = get_redis_client()
        r.set(f"task_start:{task_id}", datetime.utcnow().timestamp(), ex=3600)
    
    def on_success(self, retval, task_id, args, kwargs):
        """Record successful completion."""
        TASK_COMPLETED.labels(task_name=self.name, status='success').inc()
        self._record_duration(task_id)
        ACTIVE_TASKS.labels(task_name=self.name).dec()
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Record failure."""
        TASK_COMPLETED.labels(task_name=self.name, status='failure').inc()
        self._record_duration(task_id)
        ACTIVE_TASKS.labels(task_name=self.name).dec()
    
    def _record_duration(self, task_id):
        """Record task execution duration."""
        r = get_redis_client()
        start_time = r.get(f"task_start:{task_id}")
        
        if start_time:
            try:
                duration = datetime.utcnow().timestamp() - float(start_time)
                TASK_DURATION.labels(task_name=self.name).observe(duration)
            finally:
                r.delete(f"task_start:{task_id}")


def record_llm_call(model: str, status: str, tokens: int = 0, cost: float = 0.0):
    """Record LLM API call metrics."""
    LLM_CALLS.labels(model=model, status=status).inc()
    
    if tokens > 0:
        LLM_TOKENS.labels(model=model, token_type='prompt').inc(tokens // 2)
        LLM_TOKENS.labels(model=model, token_type='completion').inc(tokens // 2)
    
    if cost > 0:
        LLM_COST.labels(model=model).inc(cost)


# ============================================================
# RATE LIMITING
# ============================================================

import redis
from config import REDIS_URL

# Redis client for rate limiting
_redis_client = None

def get_redis_client() -> redis.Redis:
    """Get or create Redis client for rate limiting."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


class RateLimitedTask(Task):
    """Task with concurrent rate limiting using Redis."""
    
    rate_limit_key = "celery:rate_limit"
    max_concurrent = 10  # Max concurrent tasks per worker
    rate_limit_ttl = 60  # Auto-cleanup TTL in seconds
    
    def before_start(self, task_id, args, kwargs):
        """Check rate limit before starting task."""
        r = get_redis_client()
        key = f"{self.rate_limit_key}:count"
        
        # Try to acquire slot
        current_count = r.incr(key)
        
        if current_count > self.max_concurrent:
            # Release slot and retry
            r.decr(key)
            logger.warning(
                f"Rate limit exceeded for {self.name}, retrying in 5s",
                extra={"task_id": task_id, "current": current_count, "max": self.max_concurrent}
            )
            raise self.retry(countdown=5, exc=Exception("Rate limit exceeded"))

        # Set TTL for auto-cleanup
        r.expire(key, self.rate_limit_ttl)
        
        logger.debug(
            f"Rate limit check passed: {self.name}",
            extra={"task_id": task_id, "current_count": current_count}
        )
    
    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        """Release slot after task completes."""
        r = get_redis_client()
        key = f"{self.rate_limit_key}:count"
        
        # Decrement counter
        new_count = r.decr(key)
        
        # Prevent negative values
        if new_count < 0:
            r.set(key, 0)
        
        logger.debug(
            f"Rate limit released: {self.name}",
            extra={"task_id": task_id, "released_count": new_count}
        )


# ============================================================
# LOGGING TASK BASE
# ============================================================

class LoggingTask(Task):
    """Task with comprehensive lifecycle logging."""
    
    def before_start(self, task_id, args, kwargs):
        """Log before task starts."""
        logger.info(
            f"📋 Task starting: {self.name} (id={task_id})",
            extra={
                "task_id": task_id,
                "task_name": self.name,
                "args": args,
                "kwargs": kwargs
            }
        )
    
    def on_success(self, retval, task_id, args, kwargs):
        """Log successful completion."""
        result_summary = ""
        if isinstance(retval, dict):
            status = retval.get("status", "unknown")
            result_summary = f"status={status}"
            if "result" in retval:
                result_summary += f", score={retval['result'].get('final_score', 'N/A')}"
        
        logger.info(
            f"✅ Task completed: {self.name} (id={task_id}) {result_summary}",
            extra={
                "task_id": task_id,
                "task_name": self.name,
                "result": retval,
                "status": "success"
            }
        )
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Log failure with traceback."""
        logger.error(
            f"❌ Task failed: {self.name} (id={task_id}): {exc}",
            extra={
                "task_id": task_id,
                "task_name": self.name,
                "exception": str(exc),
                "traceback": einfo.traceback if einfo else None
            },
            exc_info=True
        )
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Log retry attempt."""
        logger.warning(
            f"🔄 Task retrying: {self.name} (id={task_id}), attempt={self.request.retries}: {exc}",
            extra={
                "task_id": task_id,
                "task_name": self.name,
                "retry_count": self.request.retries,
                "exception": str(exc)
            }
        )


# ==============================
# IDEMPOTENT TASK BASE
# ==============================

class IdempotentTask(MonitoredTask, RateLimitedTask, LoggingTask):
    """Task with rate limiting, idempotency check and lifecycle logging."""
    
    # Track running tasks in memory (use Redis for distributed systems)
    _running_tasks: set = set()
    
    def apply_async(self, args=None, kwargs=None, task_id=None, **options):
        """Check for duplicate tasks before queuing."""
        if task_id and task_id in IdempotentTask._running_tasks:
            logger.info(f"Task {task_id} already running, skipping")
            from celery.result import AsyncResult
            return AsyncResult(task_id)
        
        if task_id:
            IdempotentTask._running_tasks.add(task_id)
        
        return super(LoggingTask, self).apply_async(args, kwargs, task_id, **options)
    
    def on_success(self, retval, task_id, args, kwargs):
        """Clean up after success + logging."""
        IdempotentTask._running_tasks.discard(task_id)
        super().on_success(retval, task_id, args, kwargs)
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Clean up after failure + logging."""
        IdempotentTask._running_tasks.discard(task_id)
        super().on_failure(exc, task_id, args, kwargs, einfo)


# ============================================================
# LOGGING TASK BASE
# ============================================================

class LoggingTask(Task):
    """Task with comprehensive lifecycle logging."""
    
    def before_start(self, task_id, args, kwargs):
        """Log before task starts."""
        logger.info(
            f"📋 Task starting: {self.name} (id={task_id})",
            extra={
                "task_id": task_id,
                "task_name": self.name,
                "args": args,
                "kwargs": kwargs
            }
        )
    
    def on_success(self, retval, task_id, args, kwargs):
        """Log successful completion."""
        # Extract status from result
        status = retval.get("status") if isinstance(retval, dict) else "unknown"
        cached = retval.get("cached") if isinstance(retval, dict) else False
        
        logger.info(
            f"✅ Task completed: {self.name} (id={task_id}, status={status}, cached={cached})",
            extra={
                "task_id": task_id,
                "task_name": self.name,
                "status": status,
                "cached": cached
            }
        )
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Log failure with traceback."""
        logger.error(
            f"❌ Task failed: {self.name} (id={task_id}): {exc}",
            extra={
                "task_id": task_id,
                "task_name": self.name,
                "exception": str(exc),
                "traceback": str(einfo)
            },
            exc_info=True
        )
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Log retry attempt."""
        retry_count = getattr(self.request, "retries", 0)
        logger.warning(
            f"🔄 Task retrying: {self.name} (id={task_id}, attempt={retry_count}): {exc}",
            extra={
                "task_id": task_id,
                "task_name": self.name,
                "retry_count": retry_count,
                "exception": str(exc)
            }
        )


# Combined task base: Logging + Idempotent
class AnalysisTask(LoggingTask, IdempotentTask):
    """Combined task base with logging and idempotency."""
    pass


# ==============================
# CELERY TASKS
# ==============================

@celery_app.task(
    bind=True,
    name="analysis.process",
    base=IdempotentTask,
    autoretry_for=(ConnectionError, TimeoutError, asyncio.TimeoutError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
    time_limit=TASK_TIME_LIMIT,          # Hard limit: 5 min
    soft_time_limit=TASK_SOFT_TIME_LIMIT, # Soft limit: 4.5 min
    acks_late=True,                       # Acknowledge after completion
    reject_on_worker_lost=True            # Reject if worker lost
)
def process_analysis(self, job_id: int, data: Dict[str, Any]) -> Dict:
    """
    Idempotent analysis task with graceful termination.
    
    Prevents duplicate processing by checking DB status before running.
    """
    with get_db_session() as db:
        try:
            # Check if already completed (idempotency)
            analysis = get_analysis(db, job_id)
            
            if analysis:
                if analysis.status == JobStatus.SUCCESS.value:
                    logger.info(f"Analysis {job_id} already completed, returning cached result")
                    return {
                        "status": "success",
                        "result": json.loads(analysis.analysis_result) if analysis.analysis_result else {},
                        "cached": True
                    }
                
                if analysis.status == JobStatus.STARTED.value:
                    # Check if task is still running (heartbeat)
                    task_id = str(job_id)
                    if task_id in IdempotentTask._running_tasks:
                        logger.info(f"Analysis {job_id} already running")
                        return {"status": "running", "job_id": job_id}
            
            # Proceed with analysis
            update_analysis_status_safe(db, job_id, JobStatus.STARTED.value)

            title = data.get("title", "")
            description = data.get("description", "")
            tenant_id = data.get("tenant_id")
            user_id = data.get("user_id")

            # Step 1: Call LLM for product analysis
            llm_result = _call_llm_analysis(title, description)

            # Step 2: Build scoring input from LLM result
            niche_str = llm_result.get("niche", "default")
            
            # Map niche string to Niche enum
            try:
                niche = Niche(niche_str)
            except ValueError:
                niche = Niche.default

            scoring_input = ScoringInput(
                niche=niche,
                completeness=llm_result.get("completeness", 50),
                seo_score=llm_result.get("seo_score", 50),
                usp_score=llm_result.get("usp_score", 50),
                visual_quality=llm_result.get("visual_quality", 50),
                price_position=llm_result.get("price_position", 50),
                competition_intensity=llm_result.get("competition_intensity", 50),
                differentiation=llm_result.get("differentiation", 50),
                entry_barrier=llm_result.get("entry_barrier", 50),
                demand_proxy=llm_result.get("demand_proxy", 50),
                price_alignment=llm_result.get("price_alignment", 50),
                category_maturity=llm_result.get("category_maturity", 50),
                brand_dependency=llm_result.get("brand_dependency", 50),
                logistics_complexity=llm_result.get("logistics_complexity", 50),
                margin_percent=llm_result.get("margin_percent", 25),
                upsell_potential=llm_result.get("upsell_potential", 50),
                repeat_purchase=llm_result.get("repeat_purchase", 50),
                expansion_vector=llm_result.get("expansion_vector", 50)
            )

            # Step 3: Calculate scores
            result = scoring_engine.calculate(scoring_input)

            # Add LLM raw data for debugging
            result["llm_analysis"] = llm_result

            # Update analysis in DB
            update_analysis(
                db=db,
                analysis_id=job_id,
                tenant_id=tenant_id,
                final_score=result["final_score"],
                confidence=result["confidence"],
                risk_penalty=result["risk_penalty"],
                risk_flags=json.dumps(result["risk_flags"]),
                feature_vector=json.dumps(llm_result),  # Store raw LLM metrics
                analysis_result=json.dumps(result),
                status=JobStatus.SUCCESS.value,
            )

            logger.info(f"Analysis {job_id} completed with score {result['final_score']}")

            return {
                "status": "success",
                "result": result,
                "cached": False
            }

        except SoftTimeLimitExceeded:
            # Graceful timeout handling
            logger.warning(f"Task soft timeout for job {job_id}")
            
            try:
                update_analysis_status_safe(
                    db, job_id, JobStatus.TIMEOUT.value, 
                    error="Task exceeded soft time limit (4.5 min)"
                )
            except Exception:
                pass
                
            # Re-raise to let Celery handle it
            raise
            
        except Exception as e:
            logger.error(f"Analysis task failed: {e}", exc_info=True)
            
            # Update status within same session
            try:
                update_analysis_status_safe(db, job_id, JobStatus.FAILURE.value, error=str(e))
            except Exception:
                pass  # Status update failure is not critical

            # Retry on transient errors - Celery will handle via autoretry
            if isinstance(e, (ConnectionError, TimeoutError, asyncio.TimeoutError)):
                raise self.retry(exc=e, countdown=60, max_retries=3)

            return {
                "status": "failure",
                "error": str(e),
            }


def _call_llm_analysis(title: str, description: str) -> dict:
    """
    Call LLM to analyze product card using safe async execution.
    """
    from services.llm_service import generate_json
    from services.prompt_builder import build_card_prompt
    
    # Build prompt - build_card_prompt returns (system_prompt, user_prompt)
    _, user_prompt = build_card_prompt(f"{title}\n{description}")
    
    @run_async
    async def _run_llm():
        result, usage = await generate_json(
            prompt=user_prompt,
            temperature=0.0,
            use_cache=True
        )
        
        # Record metrics
        record_llm_call(
            model=usage.model,
            status='success',
            tokens=usage.total_tokens,
            cost=usage.cost_usd
        )

        logger.info(f"LLM call successful: tokens={usage.total_tokens}, cost=${usage.cost_usd:.6f}")
        return result
    
    try:
        return _run_llm()
    except Exception as e:
        # Record failed LLM call
        record_llm_call(model='gpt-4o-mini', status='error')
        logger.error(f"LLM call failed: {e}", exc_info=True)
        # Return fallback values on LLM failure
        return {
            "niche": "default",
            "completeness": 50,
            "seo_score": 50,
            "usp_score": 50,
            "visual_quality": 50,
            "price_position": 50,
            "competition_intensity": 50,
            "differentiation": 50,
            "entry_barrier": 50,
            "demand_proxy": 50,
            "price_alignment": 50,
            "category_maturity": 50,
            "brand_dependency": 50,
            "logistics_complexity": 50,
            "margin_percent": 25,
            "upsell_potential": 50,
            "repeat_purchase": 50,
            "expansion_vector": 50,
        }


@celery_app.task(bind=True, name="analysis.batch")
def process_batch(self, batch_id: str, items: list) -> Dict:
    """
    Process batch of analyses with DB persistence and logging.
    """
    logger.info(f"📦 Batch starting: {batch_id}, items={len(items)}")
    
    results = []
    success_count = 0
    error_count = 0

    with get_db_session() as db:
        for i, item in enumerate(items):
            self.update_state(
                state="PROGRESS",
                meta={"current": i + 1, "total": len(items)}
            )

            try:
                # Create analysis record in DB first
                analysis = create_analysis(
                    db,
                    tenant_id=item.get("tenant_id"),
                    user_id=item.get("user_id"),
                    title=item.get("title", ""),
                    description=item.get("description", ""),
                )
                
                # Commit to get the ID
                db.commit()

                # Process with real DB analysis_id
                result = process_analysis(
                    job_id=analysis.id,
                    data=item
                )
                
                results.append({
                    "id": item.get("id"),
                    "analysis_id": analysis.id,
                    "status": "success",
                    "result": result
                })
                success_count += 1
                
            except Exception as e:
                logger.error(f"Batch item failed: {e}")
                results.append({
                    "id": item.get("id"),
                    "status": "error",
                    "error": str(e)
                })
                error_count += 1

    logger.info(
        f"📦 Batch completed: {batch_id}, "
        f"total={len(items)}, success={success_count}, failed={error_count}"
    )

    return {
        "batch_id": batch_id,
        "total": len(items),
        "success_count": success_count,
        "failed_count": error_count,
        "results": results
    }


@celery_app.task(bind=True, name="analysis.retry_failed")
def retry_failed_analysis(self, analysis_id: int) -> Dict:
    """
    Retry failed analysis.
    """
    db = SessionLocal()
    try:
        analysis = get_analysis(db, analysis_id)

        if not analysis:
            return {"status": "error", "message": "Analysis not found"}

        if analysis.status != JobStatus.FAILURE.value:
            return {"status": "error", "message": "Analysis is not in failed state"}

        # Create new job id for Celery task
        new_job_id = str(uuid.uuid4())

        # Update status of existing analysis
        update_analysis_status(analysis_id, JobStatus.RETRY.value)

        # Queue new processing task (reuse same analysis row)
        process_analysis.apply_async(
            args=[analysis.id],
            kwargs={
                "data": {
                    "title": analysis.title,
                    "description": analysis.description,
                    "tenant_id": analysis.tenant_id,
                    "user_id": analysis.user_id,
                }
            },
            task_id=new_job_id,
        )

        return {
            "status": "retry",
            "new_job_id": new_job_id,
        }
    finally:
        db.close()


# ==============================
# HELPERS
# ==============================

def update_analysis_status(analysis_id: int, status: str, error: Optional[str] = None):
    """Update analysis status in database."""
    db = SessionLocal()
    try:
        analysis = get_analysis(db, analysis_id)
        if not analysis:
            return

        update_analysis(
            db=db,
            analysis_id=analysis_id,
            tenant_id=analysis.tenant_id,
            status=status,
            error_message=error,
        )
    finally:
        db.close()


def create_async_analysis(tenant_id: int, user_id: int, title: str, description: str) -> str:
    """Create and queue async analysis."""
    import uuid

    job_id = str(uuid.uuid4())

    # Create pending analysis in DB
    db = SessionLocal()
    try:
        analysis = create_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            title=title,
            description=description,
        )
    finally:
        db.close()

    # Queue Celery task
    process_analysis.apply_async(
        args=[analysis.id],
        kwargs={
            "data": {
                "title": title,
                "description": description,
                "tenant_id": tenant_id,
                "user_id": user_id
            }
        },
        task_id=str(analysis.id)
    )

    return str(analysis.id)


# ==============================
# NEW ANALYSIS TASK
# ==============================

class CallbackTask(Task):
    """Task with callback support."""

    def on_success(self, retval, task_id, args, kwargs):
        """Success callback."""
        print(f"✅ Task {task_id} completed successfully")

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Failure callback."""
        print(f"❌ Task {task_id} failed: {exc}")


@celery_app.task(
    name="analysis.run_batch",
    base=CallbackTask,
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def run_batch_analysis(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run batch analysis on multiple items.

    Args:
        payload: {
            "items": [...],
            "calibration_params": {...},
            "api_key": "...",
            "temperature": 0.2
        }

    Returns:
        {
            "results": [...],
            "success_count": N,
            "failed_count": M
        }
    """
    items = payload.get("items", [])
    calibration_params = payload.get("calibration_params", {})

    results = []
    success_count = 0
    failed_count = 0

    for idx, item in enumerate(items):
        try:
            # Update progress
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": idx + 1,
                    "total": len(items),
                    "status": f"Processing item {idx + 1}/{len(items)}"
                }
            )

            # Build scoring input
            scoring_input = ScoringInput(
                niche=Niche(item.get("niche", "default")),
                completeness=item.get("completeness", 50),
                seo_score=item.get("seo_score", 50),
                usp_score=item.get("usp_score", 50),
                visual_quality=item.get("visual_quality", 50),
                price_position=item.get("price_position", 50),
                competition_intensity=item.get("competition_intensity", 50),
                differentiation=item.get("differentiation", 50),
                entry_barrier=item.get("entry_barrier", 50),
                demand_proxy=item.get("demand_proxy", 50),
                price_alignment=item.get("price_alignment", 50),
                category_maturity=item.get("category_maturity", 50),
                brand_dependency=item.get("brand_dependency", 50),
                logistics_complexity=item.get("logistics_complexity", 50),
                margin_percent=item.get("margin_percent", 25),
                upsell_potential=item.get("upsell_potential", 50),
                repeat_purchase=item.get("repeat_purchase", 50),
                expansion_vector=item.get("expansion_vector", 50),
            )

            # Calculate score
            score_result = scoring_engine.calculate(scoring_input)

            # Apply calibration
            if calibration_params:
                scale = calibration_params.get("scale", 1.0)
                offset = calibration_params.get("offset", 0.0)
                score_result["final_score"] = min(100, max(0,
                    score_result["final_score"] * scale + offset
                ))

            results.append({
                "id": item.get("id"),
                "score": score_result["final_score"],
                "confidence": score_result["confidence"],
                "product_score": score_result["product_score"],
                "market_score": score_result["market_score"],
                "platform_score": score_result["platform_score"],
                "growth_score": score_result["growth_score"],
                "risk_penalty": score_result["risk_penalty"],
                "risk_flags": score_result["risk_flags"],
            })

            success_count += 1

        except Exception as e:
            results.append({
                "id": item.get("id"),
                "error": str(e),
                "score": 0,
                "confidence": 0
            })
            failed_count += 1

    return {
        "results": results,
        "success_count": success_count,
        "failed_count": failed_count,
        "total": len(items)
    }


@celery_app.task(name="analysis.single")
def run_single_analysis(
    title: str,
    description: str,
    niche: str = "default"
) -> Dict[str, Any]:
    """
    Run single analysis task.

    This is a simpler task for single-item analysis without LLM.
    """
    # Placeholder scoring (no LLM)
    scoring_input = ScoringInput(
        niche=Niche(niche),
        completeness=50,
        seo_score=50,
        usp_score=50,
        visual_quality=50,
        price_position=50,
        competition_intensity=50,
        differentiation=50,
        entry_barrier=50,
        demand_proxy=50,
        price_alignment=50,
        category_maturity=50,
        brand_dependency=50,
        logistics_complexity=50,
        margin_percent=25,
        upsell_potential=50,
        repeat_purchase=50,
        expansion_vector=50,
    )

    return scoring_engine.calculate(scoring_input)


# ============================================================
# TASK WORKFLOWS (Chaining & Chords)
# ============================================================

from celery import chain, group, chord
from celery.result import AsyncResult


@celery_app.task(name="analysis.preprocess")
def preprocess_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Preprocess input data before analysis.
    
    - Clean text
    - Validate required fields
    - Normalize data
    """
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    
    # Validate
    if not title or len(title) < 2:
        raise ValueError("Title must be at least 2 characters")
    
    return {
        **data,
        "title": title,
        "description": description,
        "preprocessed": True
    }


@celery_app.task(name="analysis.postprocess")
def postprocess_results(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Post-process analysis results.
    
    - Apply calibration
    - Generate recommendations
    - Format output
    """
    if not result or result.get("status") != "success":
        return result
    
    analysis_result = result.get("result", {})
    final_score = analysis_result.get("final_score", 0)
    
    # Generate recommendation based on score
    if final_score >= 70:
        recommendation = "high_potential"
    elif final_score >= 50:
        recommendation = "moderate_potential"
    elif final_score >= 30:
        recommendation = "low_potential"
    else:
        recommendation = "not_recommended"
    
    return {
        **result,
        "recommendation": recommendation,
        "postprocessed": True
    }


@celery_app.task(name="analysis.aggregate")
def aggregate_results(results: list) -> Dict[str, Any]:
    """
    Aggregate batch results.
    
    Called by chord after all parallel tasks complete.
    """
    total = len(results)
    success = sum(1 for r in results if r.get("status") == "success")
    failed = total - success
    
    avg_score = 0
    if success > 0:
        scores = [
            r.get("result", {}).get("final_score", 0)
            for r in results
            if r.get("status") == "success"
        ]
        avg_score = sum(scores) / len(scores) if scores else 0
    
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "avg_score": round(avg_score, 2),
        "results": results,
        "aggregated": True
    }


# ============================================================
# WORKFLOW HELPERS
# ============================================================

def run_full_analysis_workflow(job_id: int, data: Dict[str, Any]) -> AsyncResult:
    """
    Run complete analysis workflow with chaining.
    
    Flow: preprocess -> process_analysis -> postprocess
    
    Each task waits for previous to complete.
    """
    workflow = chain(
        preprocess_data.s(data),
        process_analysis.s(job_id),
        postprocess_results.s()
    )
    
    logger.info(f"Starting workflow for job {job_id}")
    return workflow.apply_async()


def run_batch_workflow_parallel(items: list) -> AsyncResult:
    """
    Process batch in parallel with chord.
    
    Flow: [process_analysis for each item] -> aggregate_results
    
    All items processed in parallel, then aggregated.
    """
    # Create parallel tasks
    tasks = [process_analysis.s(item) for item in items]
    
    # Chord: run all in parallel, then aggregate
    workflow = chord(tasks, aggregate_results.s())
    
    logger.info(f"Starting parallel batch workflow: {len(items)} items")
    return workflow.apply_async()


def run_batch_workflow_group(items: list) -> AsyncResult:
    """
    Process batch with group (simpler than chord).
    
    Returns list of results, no aggregation callback.
    """
    workflow = group([process_analysis.s(item) for item in items])
    
    logger.info(f"Starting group batch workflow: {len(items)} items")
    return workflow.apply_async()


def run_analysis_pipeline(
    job_id: int,
    data: Dict[str, Any],
    use_preprocess: bool = True,
    use_postprocess: bool = True,
    calibration: Dict = None
) -> AsyncResult:
    """
    Flexible analysis pipeline.
    
    Args:
        job_id: Analysis job ID
        data: Input data
        use_preprocess: Enable preprocessing
        use_postprocess: Enable postprocessing
        calibration: Optional calibration params
        
    Returns:
        AsyncResult for the workflow
    """
    # Build workflow chain
    if use_preprocess and use_postprocess:
        workflow = chain(
            preprocess_data.s(data),
            process_analysis.s(job_id),
            postprocess_results.s()
        )
    elif use_preprocess:
        workflow = chain(
            preprocess_data.s(data),
            process_analysis.s(job_id)
        )
    elif use_postprocess:
        workflow = chain(
            process_analysis.s(job_id),
            postprocess_results.s()
        )
    else:
        workflow = process_analysis.s(job_id)
    
    logger.info(
        f"Starting pipeline: preprocess={use_preprocess}, "
        f"postprocess={use_postprocess}, job={job_id}"
    )
    return workflow.apply_async()
