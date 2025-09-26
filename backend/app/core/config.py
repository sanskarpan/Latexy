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
    
    # OpenAI Configuration
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API key for LLM services")
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_MAX_TOKENS: int = 4000
    OPENAI_TEMPERATURE: float = 0.7
    
    # File Management
    PDF_RETENTION_TIME: int = 3600  # Keep PDFs for 1 hour (3600 seconds)
    
    # Database Configuration
    DATABASE_URL: str = Field(default="", description="PostgreSQL database URL")
    DB_HOST: str = Field(default="localhost", description="Database host")
    DB_PORT: int = Field(default=5432, description="Database port")
    DB_USER: str = Field(default="postgres", description="Database user")
    DB_PASSWORD: str = Field(default="", description="Database password")
    DB_NAME: str = Field(default="postgres", description="Database name")
    
    # Social Authentication (for Better-Auth)
    GOOGLE_CLIENT_ID: str = Field(default="", description="Google OAuth client ID")
    GOOGLE_CLIENT_SECRET: str = Field(default="", description="Google OAuth client secret")
    GITHUB_CLIENT_ID: str = Field(default="", description="GitHub OAuth client ID")
    GITHUB_CLIENT_SECRET: str = Field(default="", description="GitHub OAuth client secret")
    
    # Better-Auth Configuration
    BETTER_AUTH_SECRET: str = Field(default="", description="Better-Auth secret key")
    BETTER_AUTH_URL: str = Field(default="http://localhost:3000", description="Better-Auth URL")


# Global settings instance
settings = Settings()
