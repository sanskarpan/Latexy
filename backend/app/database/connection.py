"""Database connection and session management."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)

# Database engine
engine = None
SessionLocal = None

class Base(DeclarativeBase):
    """Base class for all database models."""
    pass

async def init_db():
    """Initialize database connection."""
    global engine, SessionLocal
    
    if not settings.DATABASE_URL:
        logger.error("DATABASE_URL not configured")
        raise ValueError("DATABASE_URL not configured")
    
    # Convert PostgreSQL URL to asyncpg format
    database_url = settings.DATABASE_URL
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    # Create async engine
    engine = create_async_engine(
        database_url,
        echo=settings.DEBUG,
        pool_pre_ping=True,
        pool_recycle=300,
    )
    
    # Create session factory
    SessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    logger.info("Database connection initialized")

async def get_db():
    """Get database session."""
    global SessionLocal
    if SessionLocal is None:
        await init_db()
    
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

async def close_db():
    """Close database connection."""
    global engine
    if engine:
        await engine.dispose()
        logger.info("Database connection closed")
