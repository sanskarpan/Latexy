"""
FastAPI application main module.
"""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .core.config import settings
from .core.event_bus import event_bus
from .core.logging import get_logger, setup_logging
from .core.redis import get_redis_client, redis_manager
from .core.tracing import instrument_fastapi, setup_telemetry
from .database.connection import close_db, init_db
from .middleware.rate_limiting import APIKeyRateLimitMiddleware, RateLimitMiddleware
from .middleware.request_context import RequestContextMiddleware
from .middleware.tenant_middleware import TenantMiddleware
from .services.latex_compiler import latex_compiler

# Setup logging
setup_logging()
setup_telemetry("api")
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Latexy Backend starting up...")

    # Initialize database connection
    try:
        await init_db()
        logger.info("Database connection initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    # Initialize Redis connections
    try:
        await redis_manager.init_redis()
        logger.info("Redis connections initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Redis: {e}")
        # Redis is not critical for basic functionality, so don't raise
        logger.warning("Continuing without Redis - some features may be limited")

    # Initialize EventBusManager (WebSocket → Redis Pub/Sub bridge)
    try:
        async_redis = await get_redis_client()
        await event_bus.init(async_redis)
        logger.info("EventBusManager initialized")
    except Exception as e:
        logger.error(f"Failed to initialize EventBusManager: {e}")
        logger.warning("Real-time WebSocket events will not be available")

    # Check LaTeX installation
    if not latex_compiler.is_available():
        logger.warning(
            "LaTeX compilation is unavailable (mode=%s)",
            latex_compiler.capability_summary(),
        )
    else:
        logger.info(
            "LaTeX compilation available (mode=%s)",
            latex_compiler.capability_summary(),
        )

    # Ensure temp directory exists
    settings.TEMP_DIR.mkdir(exist_ok=True)
    logger.info(f"Temporary directory ready: {settings.TEMP_DIR}")

    yield

    # Shutdown
    logger.info("Latexy Backend shutting down...")
    await close_db()
    await redis_manager.close_redis()


# Initialize FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    lifespan=lifespan
)
instrument_fastapi(app)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID", "X-Device-Fingerprint", "X-Tenant-Slug"],
)

if settings.RATE_LIMIT_ENABLED:
    app.add_middleware(
        RateLimitMiddleware,
        calls_per_minute=settings.RATE_LIMIT_CALLS_PER_MINUTE,
        calls_per_hour=settings.RATE_LIMIT_CALLS_PER_HOUR,
    )
    app.add_middleware(APIKeyRateLimitMiddleware)

# Resolve white-label tenant from Host / X-Tenant-Slug (Feature 85)
app.add_middleware(TenantMiddleware)
app.add_middleware(RequestContextMiddleware)

# Include routes
app.include_router(router)


def main():
    """Application entry point."""
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )


if __name__ == "__main__":
    main()
