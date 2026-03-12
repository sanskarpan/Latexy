"""
pytest configuration and shared fixtures for Latexy backend tests.

Points at the Neon DB (same as development) by default.
Override with TEST_DATABASE_URL env var if you need a separate DB.

Tables are never dropped on teardown — tests use rollbacks + a post-session
cleanup pass that removes rows inserted with the test_ prefix.

pytest-asyncio with asyncio_mode=auto (pytest.ini):
  - All async test functions run automatically in asyncio.
"""

import os
import re
import uuid
from pathlib import Path
from typing import AsyncGenerator

import pytest
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Load .env (backend/ first, project root as fallback) ─────────────────────

_backend_dir = Path(__file__).parent.parent
_root_dir = _backend_dir.parent
load_dotenv(_backend_dir / ".env")
load_dotenv(_root_dir / ".env")

# ── Build asyncpg URL from DATABASE_URL ───────────────────────────────────────


def _to_asyncpg_url(url: str) -> str:
    """Convert a sync postgresql:// URL to postgresql+asyncpg:// format."""
    # Add asyncpg driver
    url = re.sub(r"^postgresql(\+\w+)?://", "postgresql+asyncpg://", url)
    # asyncpg uses ssl=require not sslmode=require
    url = url.replace("sslmode=require", "ssl=require")
    # Remove channel_binding (psycopg3-only param)
    url = re.sub(r"&?channel_binding=\w+", "", url)
    url = url.rstrip("?&")
    return url


_raw_db_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
TEST_DATABASE_URL = _to_asyncpg_url(_raw_db_url) if _raw_db_url else ""

# ── Set env before importing app so settings picks them up ───────────────────

os.environ["SKIP_ENV_VALIDATION"] = "true"
# Always force test secrets — overrides anything in .env so make_jwt() matches settings
os.environ["JWT_SECRET_KEY"] = "test_jwt_secret_32chars_minimum_!"
os.environ["BETTER_AUTH_SECRET"] = "test_secret_key_32chars_minimum_!"
os.environ.setdefault("DATABASE_URL", _raw_db_url)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/15")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/15")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
# DEBUG=true in tests to get verbose error messages in responses.
# Production validation is tested explicitly in test_health.py via DEBUG=false assertions.
os.environ.setdefault("DEBUG", "true")

import sys

sys.path.insert(0, str(_backend_dir))


# ── Infrastructure pre-flight checks ─────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def check_infrastructure():
    """Fail fast if Redis is unavailable."""
    import redis as sync_redis
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        r = sync_redis.from_url(redis_url, socket_connect_timeout=3)
        r.ping()
    except Exception as e:
        pytest.fail(f"Redis not available at {redis_url}: {e}. Start Redis before running tests.")

from app.database.connection import Base, get_db
from app.main import app

# ── Dependency Overrides ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def override_get_db(db_session: AsyncSession):
    """Override get_db dependency to use the test session."""
    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    yield
    app.dependency_overrides.pop(get_db, None)

# ── Session-scoped engine — tables are NOT dropped on teardown ────────────────


@pytest.fixture(scope="session")
async def test_engine():
    if not TEST_DATABASE_URL:
        pytest.skip("DATABASE_URL not set — cannot connect to Neon DB")

    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        # create_all is idempotent — skips tables that already exist
        await conn.run_sync(Base.metadata.create_all)
        # Better Auth tables (not in SQLAlchemy models)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS session (
                id VARCHAR(255) PRIMARY KEY,
                "userId" VARCHAR(255) NOT NULL,
                "expiresAt" TIMESTAMPTZ NOT NULL,
                token VARCHAR(255) NOT NULL UNIQUE,
                "ipAddress" VARCHAR(45),
                "userAgent" TEXT,
                "createdAt" TIMESTAMPTZ DEFAULT NOW(),
                "updatedAt" TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS account (
                id VARCHAR(255) PRIMARY KEY,
                "userId" VARCHAR(255) NOT NULL,
                "accountId" VARCHAR(255) NOT NULL,
                "providerId" VARCHAR(255) NOT NULL,
                "accessToken" TEXT,
                "refreshToken" TEXT,
                "idToken" TEXT,
                "accessTokenExpiresAt" TIMESTAMPTZ,
                "refreshTokenExpiresAt" TIMESTAMPTZ,
                scope VARCHAR(255),
                password VARCHAR(255),
                "createdAt" TIMESTAMPTZ DEFAULT NOW(),
                "updatedAt" TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS verification (
                id VARCHAR(255) PRIMARY KEY,
                identifier VARCHAR(255) NOT NULL,
                value VARCHAR(255) NOT NULL,
                "expiresAt" TIMESTAMPTZ NOT NULL,
                "createdAt" TIMESTAMPTZ DEFAULT NOW(),
                "updatedAt" TIMESTAMPTZ DEFAULT NOW()
            )
        """))

    yield engine

    # Cleanup: delete rows inserted by tests (identified by test_ prefix)
    async with engine.begin() as conn:
        # Delete child rows first (FK constraints)
        await conn.execute(text("DELETE FROM resumes WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_%')"))
        await conn.execute(text("DELETE FROM compilations WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_%')"))
        await conn.execute(text("DELETE FROM optimizations WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_%')"))
        await conn.execute(text("DELETE FROM usage_analytics WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_%')"))
        await conn.execute(text("DELETE FROM deep_analysis_trials WHERE device_fingerprint LIKE 'test_%'"))
        await conn.execute(text("DELETE FROM resume_job_matches WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_%')"))
        # Clean up test templates (inserted by test_template_routes — all prefixed with test_tmpl_)
        await conn.execute(text("DELETE FROM resume_templates WHERE name LIKE 'test_tmpl_%'"))
        # Then delete parent rows
        await conn.execute(text("DELETE FROM session WHERE token LIKE 'test_sess_%'"))
        await conn.execute(text("DELETE FROM users WHERE email LIKE 'test_%@example.com'"))
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


# ── HTTP client (ASGI transport — no network required) ───────────────────────


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── Sample fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def sample_latex() -> str:
    return r"""
\documentclass[letterpaper,11pt]{article}
\usepackage[empty]{fullpage}
\begin{document}
\begin{center}
    \textbf{\Large John Doe} \\
    john@example.com
\end{center}
\section*{Experience}
\textbf{Software Engineer} at \textit{Acme Corp} \hfill 2020--Present \\
\begin{itemize}
    \item Built distributed systems serving 1M+ users
    \item Reduced latency by 40\% through caching
\end{itemize}
\section*{Skills}
Python, TypeScript, PostgreSQL, Redis, Docker
\end{document}
"""


# ── Auth helpers ─────────────────────────────────────────────────────────────


async def _insert_session(db: AsyncSession, user_id: str, expired: bool = False) -> str:
    """Insert a Better Auth session row and return the token."""
    from datetime import datetime, timedelta, timezone
    token = f"test_sess_{uuid.uuid4().hex}"
    delta = timedelta(hours=-1) if expired else timedelta(days=1)
    expires_at = datetime.now(timezone.utc) + delta
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {"id": str(uuid.uuid4()), "uid": user_id, "exp": expires_at, "tok": token},
    )
    await db.commit()
    return token


@pytest.fixture
async def expired_auth_headers(db_session: AsyncSession) -> dict:
    """Create headers with an expired session token."""
    from datetime import datetime, timedelta, timezone

    expired_token = f"test_sess_expired_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    expires_at = now - timedelta(hours=1)

    await db_session.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :user_id, :expires_at, :token) "
            'ON CONFLICT (token) DO UPDATE SET "expiresAt" = :expires_at'
        ),
        {
            "id": str(uuid.uuid4()),
            "user_id": "test-user-for-expired",
            "expires_at": expires_at,
            "token": expired_token,
        },
    )
    await db_session.commit()

    return {"Authorization": f"Bearer {expired_token}"}


@pytest.fixture
async def auth_headers(db_session: AsyncSession) -> dict:
    """Authorization headers with a valid Better Auth session for a test user."""
    user_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Test User', true, 'free', 'active', false) ON CONFLICT DO NOTHING"
        ),
        {"id": user_id, "email": f"test_{user_id[:8]}@example.com"},
    )
    await db_session.commit()
    token = await _insert_session(db_session, user_id)
    return {"Authorization": f"Bearer {token}"}
