"""
JWT token handling and password hashing.
Implements secure authentication with blacklist support.
"""
import re
import uuid
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status
from redis import Redis

from config import (
    SECRET_KEY, 
    ALGORITHM, 
    ACCESS_TOKEN_EXPIRE_MINUTES, 
    REFRESH_TOKEN_EXPIRE_DAYS,
    REDIS_URL
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
redis_client = Redis.from_url(REDIS_URL, decode_responses=True)


# ==============================
# PASSWORD VALIDATION
# ==============================

class PasswordStrengthError(Exception):
    """Raised when password doesn't meet requirements."""
    pass


def validate_password_strength(password: str) -> None:
    """
    Validate password meets security requirements.
    
    Requirements:
    - At least 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 digit
    - At least 1 special character
    
    Raises:
        PasswordStrengthError: If password is weak
    """
    if len(password) < 8:
        raise PasswordStrengthError("Password must be at least 8 characters long")
    
    if not re.search(r"[A-Z]", password):
        raise PasswordStrengthError("Password must contain at least one uppercase letter")
    
    if not re.search(r"[a-z]", password):
        raise PasswordStrengthError("Password must contain at least one lowercase letter")
    
    if not re.search(r"\d", password):
        raise PasswordStrengthError("Password must contain at least one digit")
    
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        raise PasswordStrengthError("Password must contain at least one special character")
    
    # Check against common passwords
    common_passwords = {
        "password", "12345678", "qwerty", "admin", "letmein",
        "welcome", "monkey", "dragon", "master", "sunshine"
    }
    if password.lower() in common_passwords:
        raise PasswordStrengthError("Password is too common")


# ==============================
# PASSWORD HASHING
# ==============================

def hash_password(password: str) -> str:
    """
    Hash password with bcrypt after validation.
    
    Args:
        password: Plain text password
    
    Returns:
        Hashed password
    
    Raises:
        PasswordStrengthError: If password is weak
    """
    validate_password_strength(password)
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify password against hash with timing attack protection.
    
    Args:
        plain_password: Plain text password from user
        hashed_password: Stored hash from database
    
    Returns:
        True if password matches, False otherwise
    """
    if not plain_password or not hashed_password:
        # Maintain constant time by performing dummy hash
        pwd_context.hash("dummy_password_to_maintain_timing")
        return False
    
    try:
        result = pwd_context.verify(plain_password, hashed_password)
        return result
    except Exception:
        # Ensure consistent timing even on error
        pwd_context.hash("dummy_password_to_maintain_timing")
        return False


# ==============================
# JWT TOKEN GENERATION
# ==============================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create JWT access token with all standard claims.
    
    Args:
        data: Payload data (must include 'sub' (user_id) and 'tenant_id')
        expires_delta: Custom expiration time
    
    Returns:
        Encoded JWT token
    
    Raises:
        ValueError: If required fields are missing
    """
    to_encode = data.copy()
    
    # Validate required fields
    if "sub" not in to_encode:
        raise ValueError("Missing 'sub' (user_id) in token data")
    
    if "tenant_id" not in to_encode:
        raise ValueError("Missing 'tenant_id' in token data")
    
    now = datetime.utcnow()
    
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    jti = str(uuid.uuid4())
    
    to_encode.update({
        "exp": expire,
        "iat": now,
        "nbf": now,  # Not Before
        "type": "access",
        "jti": jti,  # JWT ID for blacklist
        "iss": "marketscope-api"  # Issuer
    })
    
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """
    Create JWT refresh token.
    
    Args:
        data: Payload data (must include 'sub' and 'tenant_id')
    
    Returns:
        Encoded JWT refresh token
    """
    to_encode = data.copy()
    
    now = datetime.utcnow()
    expire = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    jti = str(uuid.uuid4())
    
    to_encode.update({
        "exp": expire,
        "iat": now,
        "nbf": now,
        "type": "refresh",
        "jti": jti,
        "iss": "marketscope-api"
    })
    
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ==============================
# JWT TOKEN VALIDATION
# ==============================

def decode_token(token: str) -> dict:
    """
    Decode and validate JWT token with all claims.
    
    Args:
        token: JWT token string
    
    Returns:
        Decoded payload
    
    Raises:
        HTTPException: If token is invalid, expired, or not yet valid
    """
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iat": True,
                "require_exp": True,
                "require_iat": True,
            }
        )
        return payload
    
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    except jwt.ImmatureSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token not yet valid",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


def verify_token_type(payload: dict, expected_type: str) -> None:
    """
    Verify token type (access/refresh).
    
    Args:
        payload: Decoded token payload
        expected_type: Expected token type ("access" or "refresh")
    
    Raises:
        HTTPException: If token type doesn't match
    """
    token_type = payload.get("type")
    if token_type != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token type. Expected: {expected_type}, got: {token_type}"
        )


# ==============================
# TOKEN BLACKLIST (LOGOUT)
# ==============================

def blacklist_token(token: str) -> None:
    """
    Add token to blacklist (used for logout).
    
    Args:
        token: JWT token to blacklist
    """
    try:
        payload = decode_token(token)
        jti = payload.get("jti")
        exp = payload.get("exp")
        
        if not jti:
            return  # Old tokens without jti
        
        # Calculate TTL (time until expiration)
        ttl = exp - datetime.utcnow().timestamp()
        
        if ttl > 0:
            # Store in Redis with expiration
            redis_client.setex(
                name=f"blacklist:{jti}",
                time=int(ttl),
                value="1"
            )
    except Exception:
        pass  # Token already invalid or expired


def is_token_blacklisted(token: str) -> bool:
    """
    Check if token is blacklisted.
    
    Args:
        token: JWT token to check
    
    Returns:
        True if blacklisted, False otherwise
    """
    try:
        payload = decode_token(token)
        jti = payload.get("jti")
        
        if not jti:
            return False  # Old tokens without jti
        
        return redis_client.exists(f"blacklist:{jti}") > 0
    
    except Exception:
        return False


# ==============================
# USER EXTRACTION
# ==============================

def get_user_id_from_token(token: str) -> int:
    """
    Extract user_id from JWT access token.
    
    Args:
        token: JWT token string
    
    Returns:
        User ID
    
    Raises:
        HTTPException: If token is invalid or missing user_id
    """
    payload = decode_token(token)
    verify_token_type(payload, "access")
    
    # Check blacklist
    if is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked"
        )
    
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload: missing user_id"
        )
    
    return int(user_id)


def get_tenant_id_from_token(token: str) -> int:
    """
    Extract tenant_id from JWT token.
    
    Args:
        token: JWT token string
    
    Returns:
        Tenant ID
    
    Raises:
        HTTPException: If token is invalid or missing tenant_id
    """
    payload = decode_token(token)
    tenant_id = payload.get("tenant_id")
    
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing tenant context in token"
        )
    
    return int(tenant_id)


def get_user_id_from_refresh_token(token: str) -> int:
    """
    Extract user_id from refresh token.
    
    Args:
        token: JWT refresh token string
    
    Returns:
        User ID
    
    Raises:
        HTTPException: If token is invalid or revoked
    """
    payload = decode_token(token)
    verify_token_type(payload, "refresh")
    
    # Check blacklist for refresh tokens
    if is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked"
        )
    
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload: missing user_id"
        )
    
    return int(user_id)
