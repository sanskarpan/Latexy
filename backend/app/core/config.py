"""
Application configuration settings.
"""

import os
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve paths relative to this file so they work regardless of CWD
_backend_dir = Path(__file__).parent.parent.parent   # backend/
_root_dir = _backend_dir.parent                      # Latexy/


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        # Load root .env first, then backend/.env (backend overrides root)
        env_file=(_root_dir / ".env", _backend_dir / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",   # silently ignore NEXT_PUBLIC_*, etc.
    )

    # Application
    APP_NAME: str = "Latexy-Backend"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = "LaTeX resume compilation and optimization service"
    DEBUG: bool = False

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8030

    # LaTeX Configuration
    COMPILE_TIMEOUT: int = 30  # seconds — fallback for unauthenticated/unknown plan
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB
    TEMP_DIR: Path = Path("/tmp/latex_compile")
    ALLOWED_LATEX_COMPILERS: List[str] = ["pdflatex", "xelatex", "lualatex"]
    DEFAULT_LATEX_COMPILER: str = "pdflatex"

    # Compile timeout per subscription plan (seconds)
    COMPILE_TIMEOUT_FREE: int = 30
    COMPILE_TIMEOUT_BASIC: int = 120
    COMPILE_TIMEOUT_PRO: int = 240
    COMPILE_TIMEOUT_BYOK: int = 240

    # Docker
    LATEX_DOCKER_IMAGE: str = "texlive/texlive:latest"

    # CORS
    CORS_ORIGINS: List[str] = Field(
        default=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5180",
            "http://127.0.0.1:5180",
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

    # MinIO / S3 Configuration
    MINIO_ENDPOINT: str = Field(default="http://localhost:9000", description="MinIO S3 endpoint URL")
    MINIO_ACCESS_KEY: str = Field(default="minioadmin", description="MinIO access key")
    MINIO_SECRET_KEY: str = Field(default="minioadmin_secret", description="MinIO secret key")
    MINIO_BUCKET: str = Field(default="latexy", description="MinIO bucket name")

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
    BETTER_AUTH_URL: str = Field(default="http://localhost:5180", description="Better-Auth URL")

    # Frontend URL (used to build shareable resume links)
    FRONTEND_URL: str = Field(default="http://localhost:5180", description="Frontend base URL for share links")

    # Comma-separated list of emails that get TEST_TRIAL_LIMIT instead of TRIAL_LIMIT
    TEST_USER_EMAILS: str = Field(default="", description="Comma-separated test user emails with elevated trial quota")

    # Number of free deep analysis uses per device (anonymous users)
    DEEP_ANALYSIS_TRIAL_LIMIT: int = Field(default=2, description="Number of free deep analysis uses per device")

    # JWT Configuration
    JWT_SECRET_KEY: str = Field(default="", description="JWT secret key for token signing")
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    JWT_EXPIRATION_HOURS: int = Field(default=24, description="JWT token expiration in hours")

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

    def model_post_init(self, __context) -> None:
        """Validate required settings at startup."""
        if os.environ.get("SKIP_ENV_VALIDATION") == "true":
            return
        missing = []
        if not self.DATABASE_URL:
            missing.append("DATABASE_URL")
        if not self.BETTER_AUTH_SECRET:
            missing.append("BETTER_AUTH_SECRET")
        if not self.JWT_SECRET_KEY:
            missing.append("JWT_SECRET_KEY")
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}. "
                f"Copy backend/.env.example to backend/.env and fill in the values."
            )


# Global settings instance
settings = Settings()


def get_compile_timeout(user_plan: str) -> int:
    """Return compile timeout (seconds) for a given subscription plan."""
    return {
        "free":  settings.COMPILE_TIMEOUT_FREE,
        "basic": settings.COMPILE_TIMEOUT_BASIC,
        "pro":   settings.COMPILE_TIMEOUT_PRO,
        "byok":  settings.COMPILE_TIMEOUT_BYOK,
    }.get(user_plan, settings.COMPILE_TIMEOUT_FREE)
