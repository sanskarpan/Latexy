"""
Authentication middleware for protecting routes and extracting user information.
"""

import jwt
from typing import Optional, Dict, Any
from fastapi import HTTPException, status, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import logging

logger = logging.getLogger(__name__)

# Security scheme for JWT tokens
security = HTTPBearer(auto_error=False)

class AuthMiddleware:
    """Authentication middleware for JWT token validation."""
    
    def __init__(self, secret_key: str = "your-secret-key"):
        self.secret_key = secret_key
        self.algorithm = "HS256"
    
    def decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Decode and validate JWT token."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except jwt.InvalidTokenError:
            logger.warning("Invalid token")
            return None
    
    def extract_user_id(self, token: str) -> Optional[str]:
        """Extract user ID from JWT token."""
        payload = self.decode_token(token)
        if payload:
            return payload.get("sub") or payload.get("user_id")
        return None
    
    def is_admin(self, token: str) -> bool:
        """Check if user has admin privileges."""
        payload = self.decode_token(token)
        if payload:
            return payload.get("role") == "admin" or payload.get("is_admin", False)
        return False

# Global auth middleware instance
auth_middleware = AuthMiddleware()

async def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[str]:
    """
    Get current user ID from JWT token (optional - doesn't raise error if no token).
    Returns None if no valid token is provided.
    """
    if not credentials:
        return None
    
    try:
        user_id = auth_middleware.extract_user_id(credentials.credentials)
        return user_id
    except Exception as e:
        logger.warning(f"Error extracting user from token: {e}")
        return None

async def get_current_user_required(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> str:
    """
    Get current user ID from JWT token (required - raises error if no valid token).
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        user_id = auth_middleware.extract_user_id(credentials.credentials)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user_id
    except Exception as e:
        logger.error(f"Error validating token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def require_admin(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> str:
    """
    Require admin privileges for accessing the endpoint.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        user_id = auth_middleware.extract_user_id(credentials.credentials)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        if not auth_middleware.is_admin(credentials.credentials):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin privileges required"
            )
        
        return user_id
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating admin token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

# Convenience functions for backward compatibility
async def get_user_id_optional(request: Request) -> Optional[str]:
    """Get user ID optionally (for backward compatibility)."""
    return await get_current_user_optional(request)

async def get_user_id_required(request: Request) -> str:
    """Get user ID required (for backward compatibility)."""
    return await get_current_user_required(request)

# Device fingerprint extraction
def extract_device_fingerprint(request: Request) -> Optional[str]:
    """Extract device fingerprint from request headers."""
    # Try to get from custom header first
    fingerprint = request.headers.get("X-Device-Fingerprint")
    
    if not fingerprint:
        # Fallback: create basic fingerprint from user agent and IP
        user_agent = request.headers.get("User-Agent", "")
        client_ip = request.client.host if request.client else ""
        
        if user_agent or client_ip:
            import hashlib
            fingerprint_data = f"{user_agent}:{client_ip}"
            fingerprint = hashlib.md5(fingerprint_data.encode()).hexdigest()
    
    return fingerprint

def extract_client_info(request: Request) -> Dict[str, Optional[str]]:
    """Extract client information from request."""
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("User-Agent"),
        "device_fingerprint": extract_device_fingerprint(request)
    }
