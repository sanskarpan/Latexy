"""
Rate limiting middleware for API endpoints.
"""

import time
from typing import Dict, Optional
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import redis_manager

logger = get_logger(__name__)

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using Redis for storage."""
    
    def __init__(self, app, calls_per_minute: int = 60, calls_per_hour: int = 1000):
        super().__init__(app)
        self.calls_per_minute = calls_per_minute
        self.calls_per_hour = calls_per_hour
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks and static files
        if request.url.path in ["/health", "/docs", "/openapi.json"] or request.url.path.startswith("/static"):
            return await call_next(request)
        
        # Get client identifier (IP address or user ID)
        client_id = self.get_client_id(request)
        
        # Check rate limits
        try:
            await self.check_rate_limit(client_id, request.url.path)
        except HTTPException as e:
            return Response(
                content=f'{{"error": "{e.detail}", "retry_after": 60}}',
                status_code=e.status_code,
                headers={"Content-Type": "application/json", "Retry-After": "60"}
            )
        
        response = await call_next(request)
        return response
    
    def get_client_id(self, request: Request) -> str:
        """Get client identifier for rate limiting."""
        # Try to get user ID from headers (in production, this would come from JWT)
        user_id = request.headers.get("X-User-ID")
        if user_id:
            return f"user:{user_id}"
        
        # Fall back to IP address
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        
        return f"ip:{client_ip}"
    
    async def check_rate_limit(self, client_id: str, endpoint: str):
        """Check if client has exceeded rate limits."""
        if not redis_manager.redis_client:
            # If Redis is not available, allow the request
            logger.warning("Redis not available for rate limiting")
            return
        
        current_time = int(time.time())
        minute_key = f"rate_limit:{client_id}:minute:{current_time // 60}"
        hour_key = f"rate_limit:{client_id}:hour:{current_time // 3600}"
        
        try:
            # Check minute limit
            minute_count = await redis_manager.redis_client.get(minute_key)
            if minute_count and int(minute_count) >= self.calls_per_minute:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded: {self.calls_per_minute} calls per minute"
                )
            
            # Check hour limit
            hour_count = await redis_manager.redis_client.get(hour_key)
            if hour_count and int(hour_count) >= self.calls_per_hour:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded: {self.calls_per_hour} calls per hour"
                )
            
            # Increment counters
            pipe = redis_manager.redis_client.pipeline()
            pipe.incr(minute_key)
            pipe.expire(minute_key, 60)  # Expire after 1 minute
            pipe.incr(hour_key)
            pipe.expire(hour_key, 3600)  # Expire after 1 hour
            await pipe.execute()
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            # If there's an error with rate limiting, allow the request
            pass


class APIKeyRateLimitMiddleware(BaseHTTPMiddleware):
    """Enhanced rate limiting for API key operations."""
    
    def __init__(self, app):
        super().__init__(app)
        self.byok_limits = {
            "validate": {"calls": 10, "window": 300},  # 10 validations per 5 minutes
            "add_key": {"calls": 5, "window": 3600},   # 5 key additions per hour
            "delete_key": {"calls": 10, "window": 3600} # 10 deletions per hour
        }
    
    async def dispatch(self, request: Request, call_next):
        # Only apply to BYOK endpoints
        if not request.url.path.startswith("/byok/"):
            return await call_next(request)
        
        # Determine operation type
        operation = self.get_operation_type(request)
        if not operation:
            return await call_next(request)
        
        client_id = self.get_client_id(request)
        
        try:
            await self.check_operation_limit(client_id, operation)
        except HTTPException as e:
            return Response(
                content=f'{{"error": "{e.detail}", "retry_after": {self.byok_limits[operation]["window"]}}}',
                status_code=e.status_code,
                headers={"Content-Type": "application/json", "Retry-After": str(self.byok_limits[operation]["window"])}
            )
        
        response = await call_next(request)
        return response
    
    def get_operation_type(self, request: Request) -> Optional[str]:
        """Determine the type of BYOK operation."""
        path = request.url.path
        method = request.method
        
        if path == "/byok/validate" and method == "POST":
            return "validate"
        elif path == "/byok/api-keys" and method == "POST":
            return "add_key"
        elif path.startswith("/byok/api-keys/") and method == "DELETE":
            return "delete_key"
        
        return None
    
    def get_client_id(self, request: Request) -> str:
        """Get client identifier for rate limiting."""
        user_id = request.headers.get("X-User-ID")
        if user_id:
            return f"user:{user_id}"
        
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        
        return f"ip:{client_ip}"
    
    async def check_operation_limit(self, client_id: str, operation: str):
        """Check operation-specific rate limits."""
        if not redis_manager.redis_client:
            logger.warning("Redis not available for operation rate limiting")
            return
        
        limit_config = self.byok_limits[operation]
        current_time = int(time.time())
        window_start = current_time - limit_config["window"]
        
        key = f"op_limit:{client_id}:{operation}"
        
        try:
            # Use sorted set to track requests in time window
            pipe = redis_manager.redis_client.pipeline()
            
            # Remove old entries
            pipe.zremrangebyscore(key, 0, window_start)
            
            # Count current requests in window
            pipe.zcard(key)
            
            # Add current request
            pipe.zadd(key, {str(current_time): current_time})
            
            # Set expiration
            pipe.expire(key, limit_config["window"])
            
            results = await pipe.execute()
            current_count = results[1]  # Result of zcard
            
            if current_count >= limit_config["calls"]:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Operation rate limit exceeded: {limit_config['calls']} {operation} operations per {limit_config['window']} seconds"
                )
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Operation rate limiting error: {e}")
            # If there's an error, allow the request
            pass
