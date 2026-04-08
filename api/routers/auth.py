# api/routers/auth.py
from datetime import timedelta
import re
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator

from services.tenant_service import get_db, create_user, get_user_by_email, create_tenant
from services.jwt_handler import (
    hash_password, 
    verify_password,
    create_access_token,
    create_refresh_token
)
from config import ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter(prefix="/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ==============================
# REQUEST/RESPONSE MODELS
# ==============================

class RegisterRequest(BaseModel):
    email: str
    password: str
    tenant_name: str = "Personal"

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not EMAIL_RE.match(v):
            raise ValueError("Invalid email address")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not EMAIL_RE.match(v):
            raise ValueError("Invalid email address")
        return v


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# ==============================
# ENDPOINTS
# ==============================

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Register new user and tenant."""
    # Check if user exists
    existing_user = get_user_by_email(db, payload.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # ✅ Create tenant using function
    tenant = create_tenant(db, name=payload.tenant_name, plan="free")
    
    # Create user
    hashed_password = hash_password(payload.password)
    user = create_user(
        db=db,
        tenant_id=tenant.id,
        email=payload.email,
        hashed_password=hashed_password,
        role="admin"  # First user is admin
    )
    
    # Generate tokens
    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "tenant_id": user.tenant_id,
        "role": user.role
    }
    
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token({"sub": str(user.id)})
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Login user."""
    # Find user
    user = get_user_by_email(db, payload.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    # Verify password
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )
    
    # Generate tokens
    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "tenant_id": user.tenant_id,
        "role": user.role
    }
    
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token({"sub": str(user.id)})
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(refresh_token: str, db: Session = Depends(get_db)):
    """Refresh access token."""
    from services.jwt_handler import decode_token, verify_token_type
    
    # Decode refresh token
    payload = decode_token(refresh_token)
    verify_token_type(payload, "refresh")
    
    user_id = int(payload.get("sub"))
    
    # Get user
    from services.tenant_service import get_user
    user = get_user(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    # Generate new access token
    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "tenant_id": user.tenant_id,
        "role": user.role
    }
    
    new_access_token = create_access_token(token_data)
    
    return TokenResponse(
        access_token=new_access_token,
        refresh_token=refresh_token  # Keep same refresh token
    )
