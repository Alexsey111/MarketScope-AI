"""
Usage tracking backed by the main PostgreSQL database.

Ранее использовался отдельный SQLite (`usage.db`), теперь лог агрегированной
статистики хранится в таблице `usage_logs_agg` той же Postgres‑БД.
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    Float,
    String,
    Boolean,
    DateTime,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from config import DATABASE_URL


Base = declarative_base()


class UsageLogAgg(Base):
    __tablename__ = "usage_logs_agg"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True)
    tokens_used = Column(Integer, default=0)
    analysis_time_ms = Column(Float, default=0.0)
    scoring_version = Column(String(20), nullable=True)
    niche = Column(String(100), nullable=True)
    final_score = Column(Float, nullable=True)
    cached = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create the usage tracking table if it does not exist."""
    Base.metadata.create_all(bind=engine)


class UsageTracker:
    """Track token usage and analysis metrics in PostgreSQL."""

    def log(
        self,
        user_id: int,
        tokens_used: int,
        analysis_time_ms: float,
        scoring_version: str,
        niche: str,
        final_score: float,
        cached: bool = False,
    ):
        """Log an analysis request."""
        db: Session = SessionLocal()
        try:
            row = UsageLogAgg(
                user_id=user_id,
                tokens_used=tokens_used,
                analysis_time_ms=analysis_time_ms,
                scoring_version=scoring_version,
                niche=niche,
                final_score=final_score,
                cached=cached,
            )
            db.add(row)
            db.commit()
        finally:
            db.close()

    def get_stats(self, user_id: Optional[int] = None, days: int = 30) -> dict:
        """Get usage statistics."""
        db: Session = SessionLocal()
        try:
            since = datetime.utcnow() - timedelta(days=days)

            query = db.query(UsageLogAgg).filter(UsageLogAgg.created_at > since)
            if user_id:
                query = query.filter(UsageLogAgg.user_id == user_id)

            rows = query.all()

            if not rows:
                return {
                    "total_requests": 0,
                    "total_tokens": 0,
                    "avg_analysis_time_ms": 0.0,
                    "avg_score": 0.0,
                }

            total_requests = len(rows)
            total_tokens = sum(r.tokens_used or 0 for r in rows)
            avg_time = sum(r.analysis_time_ms or 0 for r in rows) / total_requests

            scored = [r.final_score for r in rows if r.final_score is not None]
            avg_score = sum(scored) / len(scored) if scored else 0.0

            return {
                "total_requests": total_requests,
                "total_tokens": total_tokens,
                "avg_analysis_time_ms": round(avg_time, 2),
                "avg_score": round(avg_score, 2),
            }
        finally:
            db.close()


# Global tracker instance
usage_tracker = UsageTracker()
