"""
FastAPI application main module.
"""

import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .core.config import settings
from .core.logging import setup_logging, get_logger
from .services.latex_service import latex_service

# Setup logging
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Latexy Backend starting up...")
    
    # Check LaTeX installation
    if not latex_service.check_latex_installation():
        logger.warning("LaTeX installation not found or not working properly")
    else:
        logger.info("LaTeX installation verified successfully")
    
    # Ensure temp directory exists
    settings.TEMP_DIR.mkdir(exist_ok=True)
    logger.info(f"Temporary directory ready: {settings.TEMP_DIR}")
    
    yield
    
    # Shutdown
    logger.info("Latexy Backend shutting down...")


# Initialize FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
