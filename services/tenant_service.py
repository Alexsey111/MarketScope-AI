"""
Multi-tenant database setup and operations.
"""
from datetime import datetime
from typing import Optional, List

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from config import DATABASE_URL

# ✅ Импорт моделей из services.models
from services.models import (
    Base,
    TenantDB,
    UserDB,
    ProjectDB,
    AnalysisDB,
    UsageLogDB,
)

# ==============================
# DATABASE SETUP
# ==============================

engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==============================
# CRUD OPERATIONS
# ==============================

def create_tenant(db: Session, name: str, plan: str = "free") -> TenantDB:
    """Create new tenant."""
    tenant = TenantDB(name=name, plan=plan)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def get_tenant(db: Session, tenant_id: int) -> Optional[TenantDB]:
    return db.query(TenantDB).filter(TenantDB.id == tenant_id).first()


def get_user(db: Session, user_id: int) -> Optional[UserDB]:
    return db.query(UserDB).filter(UserDB.id == user_id).first()


def get_user_by_email(db: Session, email: str) -> Optional[UserDB]:
    return db.query(UserDB).filter(UserDB.email == email).first()


def create_user(
    db: Session,
    tenant_id: int,
    email: str,
    hashed_password: str,
    role: str = "viewer"
) -> UserDB:
    """Create new user."""
    user = UserDB(
        tenant_id=tenant_id,
        email=email,
        hashed_password=hashed_password,
        role=role
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_project(db: Session, project_id: int, tenant_id: int) -> Optional[ProjectDB]:
    return db.query(ProjectDB).filter(
        ProjectDB.id == project_id,
        ProjectDB.tenant_id == tenant_id
    ).first()


def get_projects(db: Session, tenant_id: int, skip: int = 0, limit: int = 100) -> List[ProjectDB]:
    return db.query(ProjectDB).filter(
        ProjectDB.tenant_id == tenant_id
    ).offset(skip).limit(limit).all()


def create_project(db: Session, tenant_id: int, name: str, description: str = None) -> ProjectDB:
    project = ProjectDB(
        tenant_id=tenant_id,
        name=name,
        description=description
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def create_analysis(
    db: Session,
    tenant_id: int,
    user_id: int,
    title: str,
    description: str,
    project_id: int = None
) -> AnalysisDB:
    """Create new analysis record."""
    analysis = AnalysisDB(
        tenant_id=tenant_id,
        user_id=user_id,
        title=title,
        description=description,
        project_id=project_id,
        status="pending"
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def update_analysis(
    db: Session,
    analysis_id: int,
    tenant_id: int,
    **kwargs
) -> Optional[AnalysisDB]:
    analysis = db.query(AnalysisDB).filter(
        AnalysisDB.id == analysis_id,
        AnalysisDB.tenant_id == tenant_id
    ).first()

    if not analysis:
        return None

    for key, value in kwargs.items():
        if hasattr(analysis, key):
            setattr(analysis, key, value)

    if kwargs.get("status") == "completed":
        analysis.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(analysis)
    return analysis


def get_analysis(db: Session, analysis_id: int) -> Optional[AnalysisDB]:
    """Get single analysis by id without tenant check (for internal helpers)."""
    return db.query(AnalysisDB).filter(AnalysisDB.id == analysis_id).first()


def get_analyses(
    db: Session,
    tenant_id: int,
    project_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100
) -> List[AnalysisDB]:
    query = db.query(AnalysisDB).filter(AnalysisDB.tenant_id == tenant_id)

    if project_id:
        query = query.filter(AnalysisDB.project_id == project_id)

    return query.order_by(AnalysisDB.created_at.desc()).offset(skip).limit(limit).all()


def log_usage(
    db: Session,
    tenant_id: int,
    user_id: int,
    endpoint: str,
    tokens_used: int = 0,
    latency_ms: float = 0,
    status_code: int = 200
) -> UsageLogDB:
    log = UsageLogDB(
        tenant_id=tenant_id,
        user_id=user_id,
        endpoint=endpoint,
        tokens_used=tokens_used,
        latency_ms=latency_ms,
        status_code=status_code
    )
    db.add(log)
    db.commit()
    return log
