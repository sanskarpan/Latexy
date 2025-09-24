"""
Application entry point.
"""

import uvicorn

from app.main import app
from app.core.config import settings


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
