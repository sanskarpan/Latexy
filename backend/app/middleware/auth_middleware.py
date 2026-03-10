"""
Authentication middleware.

Validation order for every protected request:
  1. Better Auth session token — extracted from Authorization: Bearer <token>
     or from the better-auth.session_token cookie.
     Validated by querying the `session` table in PostgreSQL.
  2. Legacy JWT fallback — for tokens signed with JWT_SECRET_KEY (HS256).
     Preserved for backward compatibility during migration.

Device fingerprint and client info helpers are unchanged.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..database.connection import get_db

logger = logging.getLogger(__name__)

# Security scheme for Bearer token extraction
security = HTTPBearer(auto_error=False)


# ------------------------------------------------------------------ #
#  Better Auth session validation (stateful, PostgreSQL-backed)       #
# ------------------------------------------------------------------ #

async def _validate_better_auth_session(
    token: str,
    db: AsyncSession,
) -> Optional[str]:
    """Return userId if the Better Auth session token is valid, else None."""
    try:
        result = await db.execute(
            text(
                'SELECT "userId" FROM session '
                'WHERE token = :token AND "expiresAt" > :now'
            ),
            {"token": token, "now": datetime.now(timezone.utc)},
        )
        row = result.fetchone()
        return row[0] if row else None
    except Exception as exc:
        logger.debug(f"Better Auth session lookup failed: {exc}")
        return None


# ------------------------------------------------------------------ #
#  Legacy JWT validation (stateless, for backward compatibility)      #
# ------------------------------------------------------------------ #

class _LegacyJWTValidator:
    """Validates HS256 JWTs issued before Better Auth was introduced."""

    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        self.algorithm = "HS256"

    def decode(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            return jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        except jwt.ExpiredSignatureError:
            logger.debug("Legacy JWT expired")
        except jwt.InvalidTokenError:
            logger.debug("Legacy JWT invalid")
        return None

    def user_id(self, token: str) -> Optional[str]:
        payload = self.decode(token)
        if payload:
            return payload.get("sub") or payload.get("user_id")
        return None

    def is_admin(self, token: str) -> bool:
        payload = self.decode(token)
        if payload:
            return payload.get("role") == "admin" or payload.get("is_admin", False)
        return False


_jwt_validator = _LegacyJWTValidator(
    secret_key=settings.JWT_SECRET_KEY or "change-me-in-production"
)

# Expose for callers that still reference auth_middleware.is_admin()
auth_middleware = _jwt_validator


# ------------------------------------------------------------------ #
#  Token extraction helper                                            #
# ------------------------------------------------------------------ #

def _extract_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[str]:
    """Return the raw token string from Bearer header or session cookie."""
    if credentials and credentials.credentials:
        return credentials.credentials
    # Cookie fallback for same-origin requests
    return request.cookies.get("better-auth.session_token")


# ------------------------------------------------------------------ #
#  FastAPI dependency functions                                        #
# ------------------------------------------------------------------ #

async def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[str]:
    """
    Return the current user_id, or None if no valid credentials are present.
    Never raises — safe for endpoints accessible by both anonymous and
    authenticated users.
    """
    token = _extract_token(request, credentials)
    if not token:
        return None

    # 1. Better Auth session lookup
    user_id = await _validate_better_auth_session(token, db)
    if user_id:
        return user_id

    # 2. Legacy JWT fallback
    return _jwt_validator.user_id(token)


async def get_current_user_required(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> str:
    """
    Return the current user_id or raise HTTP 401.
    Use as a FastAPI dependency on protected endpoints.
    """
    user_id = await get_current_user_optional(request, credentials, db)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id


async def require_admin(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> str:
    """
    Return the current user_id if the user has admin privileges, else raise.
    Admin status is encoded in legacy JWTs; Better Auth sessions do not
    carry role claims — extend this if RBAC is required.
    """
    token = _extract_token(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = await get_current_user_optional(request, credentials, db)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not _jwt_validator.is_admin(token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )

    return user_id


# ------------------------------------------------------------------ #
#  Backward-compatibility aliases                                      #
#  These must be full FastAPI dependencies so DI injects credentials  #
#  and db correctly — not bare callables missing required params.     #
# ------------------------------------------------------------------ #

async def get_user_id_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[str]:
    return await get_current_user_optional(request, credentials, db)


async def get_user_id_required(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> str:
    return await get_current_user_required(request, credentials, db)


# ------------------------------------------------------------------ #
#  Device / client info helpers (unchanged)                           #
# ------------------------------------------------------------------ #

def extract_device_fingerprint(request: Request) -> Optional[str]:
    """Extract device fingerprint from request headers."""
    fingerprint = request.headers.get("X-Device-Fingerprint")
    if not fingerprint:
        user_agent = request.headers.get("User-Agent", "")
        client_ip = request.client.host if request.client else ""
        if user_agent or client_ip:
            import hashlib
            fingerprint = hashlib.md5(f"{user_agent}:{client_ip}".encode()).hexdigest()
    return fingerprint


def extract_client_info(request: Request) -> Dict[str, Optional[str]]:
    """Extract client information from request."""
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("User-Agent"),
        "device_fingerprint": extract_device_fingerprint(request),
    }
