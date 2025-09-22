"""
Logging configuration.
"""

import logging
import sys
from typing import Dict, Any

from .config import settings


def setup_logging() -> None:
    """Configure application logging."""
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper()),
        format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s", "module": "%(name)s"}',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    
    # Set specific loggers
    loggers_config: Dict[str, Dict[str, Any]] = {
        "uvicorn": {"level": "INFO"},
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {"level": "WARNING"},
        "fastapi": {"level": "INFO"},
    }
    
    for logger_name, config in loggers_config.items():
        logger = logging.getLogger(logger_name)
        logger.setLevel(getattr(logging, config["level"]))


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)
