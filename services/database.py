#services\database.py
"""
History storage for analyses, backed by the main PostgreSQL database.

Ранее история хранилась в локальном SQLite (`marketscope.db`), теперь —
в отдельной таблице `history` в той же Postgres‑БД, что и multi‑tenant данные.
"""

import json
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    Float,
    String,
    Text,
    DateTime,
)
from sqlalchemy.pool import QueuePool
from sqlalchemy.orm import sessionmaker, Session

from config import DATABASE_URL
from services.models import Base, HistoryDB  # ✅ Import from models


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,           # Количество постоянных соединений
    max_overflow=20,        # Максимум временных соединений
    pool_pre_ping=True,     # Проверка соединения перед использованием
    echo=False              # Отключи SQL логи в production
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db():
    """Context manager for database sessions to prevent leaks."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _truncate_for_storage(text: str, max_length: int = 500) -> str:
    """Truncate text to prevent data leakage. Store only summary."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "... [truncated]"


def save_history(
    user_id: int,
    text: str,
    score: float,
    scoring_version: str = "v4.0",
    feature_vector: dict | None = None,
    status: AnalysisStatus = AnalysisStatus.COMPLETED,
    store_full_text: bool = False,
) -> int:
    """
    Save analysis to history in PostgreSQL.

    Args:
        user_id: External user ID (например, ID пользователя API или Telegram).
        text: Full text (будет усечён, если store_full_text=False).
        score: Итоговый скор.
        scoring_version: Версия скорингового движка.
        feature_vector: Произвольный JSON с фичами.
        status: Статус анализа.
        store_full_text: Если False — текст усечётся для защиты данных.
    """
    stored_text = text if store_full_text else _truncate_for_storage(text)

    with get_db() as db:
        row = HistoryDB(
            user_id=user_id,
            text=stored_text,
            score=score,
            scoring_version=scoring_version,
            feature_vector=json.dumps(feature_vector) if feature_vector else None,
            analysis_status=status.value,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id


def create_pending_analysis(
    user_id: int,
    text: str,
    scoring_version: str = "v4.0",
) -> int:
    """
    Create a pending analysis record. Returns id.
    """
    with get_db() as db:
        row = HistoryDB(
            user_id=user_id,
            text=text,
            scoring_version=scoring_version,
            analysis_status=AnalysisStatus.PENDING.value,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id


def update_analysis_status(
    analysis_id: int,
    status: AnalysisStatus,
    score: Optional[float] = None,
    feature_vector: Optional[dict] = None,
) -> bool:
    """
    Update analysis status atomically. Returns True if successful.
    """
    with get_db() as db:
        row: HistoryDB | None = db.query(HistoryDB).filter(HistoryDB.id == analysis_id).first()
        if not row:
            return False

        row.analysis_status = status.value
        if status == AnalysisStatus.COMPLETED and score is not None:
            row.score = score
            row.feature_vector = json.dumps(feature_vector) if feature_vector else None

        db.commit()
        return True


def get_analysis(analysis_id: int) -> Optional[dict]:
    """Get analysis by ID as dict."""
    with get_db() as db:
        row: HistoryDB | None = db.query(HistoryDB).filter(HistoryDB.id == analysis_id).first()
        if not row:
            return None

        return {
            "id": row.id,
            "user_id": row.user_id,
            "text": row.text,
            "score": row.score,
            "scoring_version": row.scoring_version,
            "feature_vector": row.feature_vector,
            "analysis_status": row.analysis_status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
