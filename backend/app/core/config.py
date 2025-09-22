"""
Application configuration settings.
"""

import os
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        env_file_encoding="utf-8"
    )
    
    # Application
    APP_NAME: str = "Latexy-Backend"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = "LaTeX resume compilation and optimization service"
    DEBUG: bool = False
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # LaTeX Configuration
    COMPILE_TIMEOUT: int = 30  # seconds
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB
    TEMP_DIR: Path = Path("/tmp/latex_compile")
    
    # Docker
    LATEX_DOCKER_IMAGE: str = "texlive/texlive:latest"
    
    # CORS
    CORS_ORIGINS: List[str] = Field(
        default=[
            "http://localhost:3000",
            "http://127.0.0.1:3000"
        ]
    )
    
    # Logging
    LOG_LEVEL: str = "INFO"


# Global settings instance
settings = Settings()
