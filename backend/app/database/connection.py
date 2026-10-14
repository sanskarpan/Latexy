"""Database connection and session management."""

from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from ..core.config import settings
from ..core.logging import get_logger
from ..core.tracing import instrument_sqlalchemy

logger = get_logger(__name__)

# Database engine
engine = None
SessionLocal = None

class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


def normalize_async_database_url(database_url: str) -> str:
    """Convert PostgreSQL URL options structurally for asyncpg.

    asyncpg uses ``ssl`` where psycopg clients use ``sslmode`` and does not
    accept ``channel_binding``, which is removed for compatibility. SQLAlchemy
    parses and re-renders URL components so credentials or other query values
    containing these strings stay intact.
    """
    try:
        url = make_url(database_url)
    except Exception:
        # SQLAlchemy parse errors may include the supplied URL. Keep credentials
        # out of startup logs and caller-visible exception text.
        raise ValueError("DATABASE_URL must be a valid SQLAlchemy URL") from None

    # SQLAlchemy drops blank query values while parsing. Reject them from the
    # original query so an explicit empty SSL setting cannot silently fall back
    # to another value or a driver default.
    try:
        raw_query = urlsplit(database_url).query
        blank_ssl_option = any(
            key in {"ssl", "sslmode"} and value == ""
            for key, value in parse_qsl(raw_query, keep_blank_values=True)
        )
    except ValueError:
        raise ValueError("DATABASE_URL must be a valid SQLAlchemy URL") from None
    if blank_ssl_option:
        raise ValueError("DATABASE_URL has a blank SSL query option")

    base_driver = url.drivername.partition("+")[0]
    if base_driver not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must use a supported PostgreSQL driver")

    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    existing_ssl = query.get("ssl")

    def single_ssl_value(value):
        if isinstance(value, str):
            return value
        if isinstance(value, tuple) and value and all(item == value[0] for item in value):
            return value[0]
        raise ValueError("DATABASE_URL has ambiguous SSL query options")

    if existing_ssl is not None:
        existing_ssl = single_ssl_value(existing_ssl)
        query["ssl"] = existing_ssl

    if sslmode is not None:
        sslmode = single_ssl_value(sslmode)
        if existing_ssl is not None:
            if existing_ssl != sslmode:
                raise ValueError("DATABASE_URL has conflicting ssl and sslmode options")
        query["ssl"] = sslmode

    query.pop("channel_binding", None)
    normalized = url.set(drivername="postgresql+asyncpg", query=query)
    return normalized.render_as_string(hide_password=False)

async def init_db():
    """Initialize database connection."""
    global engine, SessionLocal

    if not settings.DATABASE_URL:
        logger.error("DATABASE_URL not configured")
        raise ValueError("DATABASE_URL not configured")

    database_url = normalize_async_database_url(settings.DATABASE_URL)

    # Create async engine
    engine = create_async_engine(
        database_url,
        echo=settings.SQL_ECHO,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
    )
    instrument_sqlalchemy(engine.sync_engine)

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

@asynccontextmanager
async def get_async_db_session():
    """Async context manager for database sessions (for use in Celery workers)."""
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
    global engine, SessionLocal
    current_engine = engine
    # Clear published references before awaiting disposal. This makes shutdown
    # idempotent and prevents a later lifespan (or test event loop) from
    # borrowing a session factory backed by an engine that has been disposed.
    engine = None
    SessionLocal = None
    if current_engine:
        await current_engine.dispose()
        logger.info("Database connection closed")
