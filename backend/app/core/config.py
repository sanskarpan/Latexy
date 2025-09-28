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
    
    # Multi-Provider & BYOK (Phase 10)
    API_KEY_ENCRYPTION_KEY: str = Field(default="", description="Encryption key for storing user API keys")
    ANTHROPIC_API_KEY: str = Field(default="", description="Default Anthropic API key")
    OPENROUTER_API_KEY: str = Field(default="", description="Default OpenRouter API key")
    GEMINI_API_KEY: str = Field(default="", description="Default Google Gemini API key")
    
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
    
    # Razorpay Configuration
    RAZORPAY_KEY_ID: str = Field(default="", description="Razorpay API Key ID")
    RAZORPAY_KEY_SECRET: str = Field(default="", description="Razorpay API Key Secret")
    RAZORPAY_WEBHOOK_SECRET: str = Field(default="", description="Razorpay Webhook Secret")
    
    # Redis Config
    REDIS_URL: str = Field(default="redis://localhost:6379/0", description="Redis URL for job queue")
    REDIS_CACHE_URL: str = Field(default="redis://localhost:6379/1", description="Redis URL for caching")
    REDIS_PASSWORD: str = Field(default="", description="Redis password")
    REDIS_MAX_CONNECTIONS: int = Field(default=20, description="Redis max connections")
    
    # Celery Configuration 
    CELERY_BROKER_URL: str = Field(default="redis://localhost:6379/0", description="Celery broker URL")
    CELERY_RESULT_BACKEND: str = Field(default="redis://localhost:6379/0", description="Celery result backend URL")
    CELERY_TASK_SERIALIZER: str = Field(default="json", description="Celery task serializer")
    CELERY_RESULT_SERIALIZER: str = Field(default="json", description="Celery result serializer")
    CELERY_ACCEPT_CONTENT: List[str] = Field(default=["json"], description="Celery accepted content types")
    CELERY_TIMEZONE: str = Field(default="UTC", description="Celery timezone")
    CELERY_ENABLE_UTC: bool = Field(default=True, description="Enable UTC in Celery")
    
    # Job Management Configuration 
    JOB_RESULT_TTL: int = Field(default=86400, description="Job result TTL in seconds (24 hours)")
    JOB_RETRY_ATTEMPTS: int = Field(default=3, description="Maximum job retry attempts")
    JOB_RETRY_DELAY: int = Field(default=60, description="Job retry delay in seconds")
    
    # WebSocket Configuration 
    WEBSOCKET_ENABLED: bool = Field(default=True, description="Enable WebSocket for real-time updates")
    WEBSOCKET_HEARTBEAT_INTERVAL: int = Field(default=30, description="WebSocket heartbeat interval in seconds")
    
    # Subscription Plans
    SUBSCRIPTION_PLANS: dict = Field(default={
        "free": {
            "name": "Free Trial",
            "price": 0,
            "currency": "INR",
            "interval": "month",
            "features": {
                "compilations": 3,
                "optimizations": 0,
                "historyRetention": 0,
                "prioritySupport": False,
                "apiAccess": False
            }
        },
        "basic": {
            "name": "Basic",
            "price": 29900,  # 299 INR in paise
            "currency": "INR",
            "interval": "month",
            "features": {
                "compilations": 50,
                "optimizations": 10,
                "historyRetention": 30,
                "prioritySupport": False,
                "apiAccess": False
            }
        },
        "pro": {
            "name": "Pro",
            "price": 59900,  # 599 INR in paise
            "currency": "INR",
            "interval": "month",
            "features": {
                "compilations": "unlimited",
                "optimizations": "unlimited",
                "historyRetention": 365,
                "prioritySupport": True,
                "apiAccess": True
            }
        },
        "byok": {
            "name": "BYOK (Bring Your Own Key)",
            "price": 19900,  # 199 INR in paise
            "currency": "INR",
            "interval": "month",
            "features": {
                "compilations": "unlimited",
                "optimizations": "unlimited",
                "historyRetention": 365,
                "prioritySupport": True,
                "apiAccess": True,
                "customModels": True
            }
        }
    })


# Global settings instance
settings = Settings()
