"""
Authentication and authorization layer.
Handles JWT validation, tenant isolation, and RBAC.
"""
from typing import Optional
import logging
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import jwt

from services.tenant_service import get_db, get_user, UserDB
from services.jwt_handler import get_user_id_from_token, get_tenant_id_from_token

security = HTTPBearer()
security_logger = logging.getLogger("security")


class TenantContext:
    """Tenant context for request isolation."""
    def __init__(self, tenant_id: int, user_id: int, role: str, user: Optional[UserDB] = None):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.role = role
        self.user = user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> UserDB:
    """
    Extract and validate user from JWT token.
    
    Raises:
        HTTPException: If token is invalid, expired, or user not found
    """
    token = credentials.credentials
    user_id = None
    
    try:
        # Decode JWT and extract user_id
        user_id = get_user_id_from_token(token)
        
        if user_id is None:
            security_logger.warning("Token decode failed: user_id is None")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    except jwt.ExpiredSignatureError:
        security_logger.warning(f"Expired token attempt: user_id={user_id or 'unknown'}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    except jwt.InvalidTokenError as e:
        security_logger.error(f"Invalid token attempt: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Fetch user from database
    user = get_user(db, user_id)
    
    if not user:
        security_logger.warning(f"User not found: user_id={user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    if not user.is_active:
        security_logger.warning(f"Inactive user login attempt: user_id={user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled"
        )
    
    # TODO: Check token blacklist for logout support
    # if await is_token_blacklisted(token):
    #     security_logger.warning(f"Blacklisted token used: user_id={user_id}")
    #     raise HTTPException(status_code=401, detail="Token has been revoked")
    
    security_logger.info(f"User authenticated: user_id={user.id}, tenant_id={user.tenant_id}")
    
    return user


async def get_current_tenant(
    user: UserDB = Depends(get_current_user)
) -> TenantContext:
    """
    Get current tenant context from authenticated user.
    
    Returns:
        TenantContext with tenant_id, user_id, role
    """
    return TenantContext(
        tenant_id=user.tenant_id,
        user_id=user.id,
        role=user.role,
        user=user
    )


def require_role(*allowed_roles: str):
    """
    Dependency factory to require specific roles.
    
    Usage:
        @router.get("/admin", dependencies=[Depends(require_role("admin"))])
    """
    async def role_checker(tenant: TenantContext = Depends(get_current_tenant)):
        if tenant.role not in allowed_roles:
            security_logger.warning(
                f"Insufficient permissions: user_id={tenant.user_id}, "
                f"role={tenant.role}, required={allowed_roles}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {', '.join(allowed_roles)}"
            )
        return tenant
    
    return role_checker


async def require_tenant_analysis(
    analysis_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant)
):
    """
    Verify analysis belongs to current tenant.
    
    Args:
        analysis_id: Analysis ID to verify
        db: Database session
        tenant: Current tenant context
    
    Returns:
        AnalysisDB object
    
    Raises:
        HTTPException: If analysis not found or access denied
    """
    from services.tenant_service import AnalysisDB
    
    analysis = db.query(AnalysisDB).filter(
        AnalysisDB.id == analysis_id,
        AnalysisDB.tenant_id == tenant.tenant_id,
        AnalysisDB.deleted_at.is_(None)  # Respect soft deletes
    ).first()
    
    if not analysis:
        security_logger.warning(
            f"Unauthorized analysis access attempt: "
            f"analysis_id={analysis_id}, tenant_id={tenant.tenant_id}, user_id={tenant.user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found or access denied"
        )
    
    return analysis


async def require_tenant_project(
    project_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant)
):
    """Verify project belongs to current tenant."""
    from services.tenant_service import ProjectDB
    
    project = db.query(ProjectDB).filter(
        ProjectDB.id == project_id,
        ProjectDB.tenant_id == tenant.tenant_id,
        ProjectDB.is_active == True
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found or access denied"
        )
    
    return project

