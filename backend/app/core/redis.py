"""
Redis connection and management for Phase 8.
"""

import asyncio
import json
from typing import Any, Optional, Dict, List
import redis.asyncio as aioredis
import redis
from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)

# Global Redis connections
redis_client: Optional[aioredis.Redis] = None
redis_cache_client: Optional[aioredis.Redis] = None
sync_redis_client: Optional[redis.Redis] = None


class RedisManager:
    """Redis connection and management class."""
    
    def __init__(self):
        self.redis_client: Optional[aioredis.Redis] = None
        self.redis_cache_client: Optional[aioredis.Redis] = None
        self.sync_redis_client: Optional[redis.Redis] = None
    
    async def init_redis(self):
        """Initialize Redis connections."""
        global redis_client, redis_cache_client, sync_redis_client
        
        try:
            # Async Redis client for job queue
            redis_client = aioredis.from_url(
                settings.REDIS_URL,
                password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
                max_connections=settings.REDIS_MAX_CONNECTIONS,
                decode_responses=True,
                retry_on_timeout=True
            )
            
            # Async Redis client for caching
            redis_cache_client = aioredis.from_url(
                settings.REDIS_CACHE_URL,
                password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
                max_connections=settings.REDIS_MAX_CONNECTIONS,
                decode_responses=True,
                retry_on_timeout=True
            )
            
            # Sync Redis client for Celery
            sync_redis_client = redis.from_url(
                settings.REDIS_URL,
                password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
                max_connections=settings.REDIS_MAX_CONNECTIONS,
                decode_responses=True,
                retry_on_timeout=True
            )
            
            # Test connections
            await redis_client.ping()
            await redis_cache_client.ping()
            sync_redis_client.ping()
            
            self.redis_client = redis_client
            self.redis_cache_client = redis_cache_client
            self.sync_redis_client = sync_redis_client
            
            logger.info("Redis connections initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Redis connections: {e}")
            raise
    
    async def close_redis(self):
        """Close Redis connections."""
        global redis_client, redis_cache_client, sync_redis_client
        
        try:
            if redis_client:
                await redis_client.close()
                redis_client = None
            
            if redis_cache_client:
                await redis_cache_client.close()
                redis_cache_client = None
            
            if sync_redis_client:
                sync_redis_client.close()
                sync_redis_client = None
            
            logger.info("Redis connections closed")
            
        except Exception as e:
            logger.error(f"Error closing Redis connections: {e}")
    
    async def health_check(self) -> Dict[str, bool]:
        """Check Redis connection health."""
        health = {
            "redis_queue": False,
            "redis_cache": False,
            "redis_sync": False
        }
        
        try:
            if redis_client:
                await redis_client.ping()
                health["redis_queue"] = True
        except Exception as e:
            logger.error(f"Redis queue health check failed: {e}")
        
        try:
            if redis_cache_client:
                await redis_cache_client.ping()
                health["redis_cache"] = True
        except Exception as e:
            logger.error(f"Redis cache health check failed: {e}")
        
        try:
            if sync_redis_client:
                sync_redis_client.ping()
                health["redis_sync"] = True
        except Exception as e:
            logger.error(f"Redis sync health check failed: {e}")
        
        return health


class JobStatusManager:
    """Manager for job status tracking in Redis."""
    
    def __init__(self):
        self.status_prefix = "job_status:"
        self.result_prefix = "job_result:"
        self.progress_prefix = "job_progress:"
    
    async def set_job_status(self, job_id: str, status: str, metadata: Optional[Dict] = None):
        """Set job status in Redis."""
        if not redis_client:
            raise RuntimeError("Redis client not initialized")
        
        status_data = {
            "status": status,
            "updated_at": asyncio.get_event_loop().time(),
            "metadata": metadata or {}
        }
        
        key = f"{self.status_prefix}{job_id}"
        await redis_client.setex(
            key, 
            settings.JOB_RESULT_TTL, 
            json.dumps(status_data)
        )
        
        logger.debug(f"Set job status for {job_id}: {status}")
    
    async def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Get job status from Redis."""
        if not redis_client:
            raise RuntimeError("Redis client not initialized")
        
        key = f"{self.status_prefix}{job_id}"
        data = await redis_client.get(key)
        
        if data:
            return json.loads(data)
        return None
    
    async def set_job_result(self, job_id: str, result: Dict):
        """Set job result in Redis."""
        if not redis_client:
            raise RuntimeError("Redis client not initialized")
        
        key = f"{self.result_prefix}{job_id}"
        await redis_client.setex(
            key, 
            settings.JOB_RESULT_TTL, 
            json.dumps(result)
        )
        
        logger.debug(f"Set job result for {job_id}")
    
    async def get_job_result(self, job_id: str) -> Optional[Dict]:
        """Get job result from Redis."""
        if not redis_client:
            raise RuntimeError("Redis client not initialized")
        
        key = f"{self.result_prefix}{job_id}"
        data = await redis_client.get(key)
        
        if data:
            return json.loads(data)
        return None
    
    async def set_job_progress(self, job_id: str, progress: int, message: Optional[str] = None):
        """Set job progress in Redis."""
        if not redis_client:
            raise RuntimeError("Redis client not initialized")
        
        progress_data = {
            "progress": progress,
            "message": message,
            "updated_at": asyncio.get_event_loop().time()
        }
        
        key = f"{self.progress_prefix}{job_id}"
        await redis_client.setex(
            key, 
            settings.JOB_RESULT_TTL, 
            json.dumps(progress_data)
        )
        
        logger.debug(f"Set job progress for {job_id}: {progress}%")
    
    async def get_job_progress(self, job_id: str) -> Optional[Dict]:
        """Get job progress from Redis."""
        if not redis_client:
            raise RuntimeError("Redis client not initialized")
        
        key = f"{self.progress_prefix}{job_id}"
        data = await redis_client.get(key)
        
        if data:
            return json.loads(data)
        return None
    
    async def delete_job_data(self, job_id: str):
        """Delete all job data from Redis."""
        if not redis_client:
            raise RuntimeError("Redis client not initialized")
        
        keys = [
            f"{self.status_prefix}{job_id}",
            f"{self.result_prefix}{job_id}",
            f"{self.progress_prefix}{job_id}"
        ]
        
        await redis_client.delete(*keys)
        logger.debug(f"Deleted job data for {job_id}")
    
    async def get_active_jobs(self) -> List[str]:
        """Get list of active job IDs."""
        if not redis_client:
            raise RuntimeError("Redis client not initialized")
        
        pattern = f"{self.status_prefix}*"
        keys = await redis_client.keys(pattern)
        
        job_ids = []
        for key in keys:
            job_id = key.replace(self.status_prefix, "")
            job_ids.append(job_id)
        
        return job_ids


class CacheManager:
    """Manager for caching operations."""
    
    def __init__(self):
        self.cache_prefix = "cache:"
    
    async def set(self, key: str, value: Any, ttl: int = 3600):
        """Set cache value."""
        if not redis_cache_client:
            raise RuntimeError("Redis cache client not initialized")
        
        cache_key = f"{self.cache_prefix}{key}"
        serialized_value = json.dumps(value) if not isinstance(value, str) else value
        
        await redis_cache_client.setex(cache_key, ttl, serialized_value)
        logger.debug(f"Set cache for key: {key}")
    
    async def get(self, key: str) -> Optional[Any]:
        """Get cache value."""
        if not redis_cache_client:
            raise RuntimeError("Redis cache client not initialized")
        
        cache_key = f"{self.cache_prefix}{key}"
        value = await redis_cache_client.get(cache_key)
        
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        
        return None
    
    async def delete(self, key: str):
        """Delete cache value."""
        if not redis_cache_client:
            raise RuntimeError("Redis cache client not initialized")
        
        cache_key = f"{self.cache_prefix}{key}"
        await redis_cache_client.delete(cache_key)
        logger.debug(f"Deleted cache for key: {key}")
    
    async def exists(self, key: str) -> bool:
        """Check if cache key exists."""
        if not redis_cache_client:
            raise RuntimeError("Redis cache client not initialized")
        
        cache_key = f"{self.cache_prefix}{key}"
        return await redis_cache_client.exists(cache_key) > 0


# Global instances
redis_manager = RedisManager()
job_status_manager = JobStatusManager()
cache_manager = CacheManager()


# Utility functions
async def get_redis_client() -> aioredis.Redis:
    """Get async Redis client."""
    if not redis_client:
        await redis_manager.init_redis()
    return redis_client


async def get_redis_cache_client() -> aioredis.Redis:
    """Get async Redis cache client."""
    if not redis_cache_client:
        await redis_manager.init_redis()
    return redis_cache_client


def get_sync_redis_client() -> redis.Redis:
    """Get sync Redis client for Celery."""
    if not sync_redis_client:
        # For sync client, we need to initialize synchronously
        import redis as sync_redis
        client = sync_redis.from_url(
            settings.REDIS_URL,
            password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=True,
            retry_on_timeout=True
        )
        return client
    return sync_redis_client
