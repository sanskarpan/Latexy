"""
pytest configuration and shared fixtures for Latexy backend tests.

Backend tests must run against an isolated test database. Resolution order:
1. TEST_DATABASE_URL when explicitly provided
2. DATABASE_URL only when it already points at a test database
3. local Docker default: postgresql+asyncpg://latexy:latexy_password@localhost:5434/latexy_test

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
from urllib.parse import urlparse

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
    # Normalise any postgres:// or postgresql+driver:// to asyncpg
    url = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql+asyncpg://", url)
    # asyncpg uses ssl=require not sslmode=require
    url = url.replace("sslmode=require", "ssl=require")
    # Remove channel_binding (psycopg3-only param)
    url = re.sub(r"&?channel_binding=\w+", "", url)
    url = url.rstrip("?&")
    return url


DEFAULT_LOCAL_TEST_DB_URL = "postgresql+asyncpg://latexy:latexy_password@localhost:5434/latexy_test"


def _looks_like_test_db_url(url: str) -> bool:
    """Return True only for URLs that clearly target a test database."""
    if not url:
        return False
    parsed = urlparse(url)
    db_name = parsed.path.rsplit("/", 1)[-1].strip()
    return db_name.endswith("_test") or db_name in {"test", "testing"}


_explicit_test_db_url = os.environ.get("TEST_DATABASE_URL", "")
_env_database_url = os.environ.get("DATABASE_URL", "")

if _explicit_test_db_url:
    if not _looks_like_test_db_url(_explicit_test_db_url):
        raise RuntimeError(
            "TEST_DATABASE_URL must point at an isolated test database "
            "(expected a database name ending in '_test')."
        )
    _raw_db_url = _explicit_test_db_url
elif _looks_like_test_db_url(_env_database_url):
    _raw_db_url = _env_database_url
else:
    _raw_db_url = DEFAULT_LOCAL_TEST_DB_URL

TEST_DATABASE_URL = _to_asyncpg_url(_raw_db_url) if _raw_db_url else ""

# ── Set env before importing app so settings picks them up ───────────────────

os.environ["SKIP_ENV_VALIDATION"] = "true"
os.environ.setdefault("ENVIRONMENT", "test")
# Always force test secrets — overrides anything in .env so make_jwt() matches settings
os.environ["JWT_SECRET_KEY"] = "test_jwt_secret_32chars_minimum_!"
os.environ["BETTER_AUTH_SECRET"] = "test_secret_key_32chars_minimum_!"
os.environ.setdefault("API_KEY_ENCRYPTION_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
# Redis DB 15 is the test DB and reset_test_redis() flushes it wholesale. These
# must be assigned, not setdefault: load_dotenv() above already imported the dev
# REDIS_URL (db 0), so a setdefault left the suite flushing the running dev
# stack's job keys mid-run — jobs vanished seconds after completing and
# GET /jobs/{id}/state started answering "Job not found".
_TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
os.environ["REDIS_URL"] = _TEST_REDIS_URL
os.environ["CELERY_BROKER_URL"] = _TEST_REDIS_URL
os.environ["CELERY_RESULT_BACKEND"] = _TEST_REDIS_URL
os.environ["OPENAI_API_KEY"] = ""  # always disable live LLM in tests — use mocks instead
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
# DEBUG=true in tests to get verbose error messages in responses.
# Production validation is tested explicitly in test_health.py via DEBUG=false assertions.
os.environ.setdefault("DEBUG", "true")

import sys

sys.path.insert(0, str(_backend_dir))


# ── Infrastructure pre-flight checks ─────────────────────────────────────────


# Static suites (e.g. test_modal_deployment_parity.py) only read source files, so
# they must stay runnable in a bare CI job with no Postgres and no Redis — a guard
# that needs a whole stack to run is a guard that ends up skipped.
_SKIP_INFRA = os.environ.get("SKIP_INFRA_CHECK", "").lower() in {"1", "true", "yes"}


@pytest.fixture(scope="session", autouse=True)
def check_infrastructure():
    """Fail fast if Redis is unavailable."""
    if _SKIP_INFRA:
        return
    import redis as sync_redis
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        r = sync_redis.from_url(redis_url, socket_connect_timeout=3)
        r.ping()
    except Exception as e:
        pytest.fail(f"Redis not available at {redis_url}: {e}. Start Redis before running tests.")


@pytest.fixture(scope="session", autouse=True)
def reset_test_redis():
    """Flush the dedicated Redis test DB so repeated runs stay deterministic."""
    if _SKIP_INFRA:
        yield
        return
    import redis as sync_redis

    client = sync_redis.from_url(_TEST_REDIS_URL, socket_connect_timeout=3)
    client.flushdb()
    yield
    client.flushdb()

from app.database.connection import get_db
from app.main import app

# ── LaTeX recorder-file confinement ───────────────────────────────────────
# The engine writes <jobname>.fls only when it actually runs; the worker unit tests
# mock subprocess.Popen, so no recorder file is ever produced and the fail-closed
# "no recorder file" rule would trip in every one of them. Relax THAT rule only —
# reads outside the jail and a clobbered recorder file stay detected. The real
# function, missing-file rule included, is exercised in test_latex_sandbox.py.


@pytest.fixture(autouse=True)
def _reset_async_redis_singletons():
    """Drop the async Redis client singletons before each test.

    aioredis connection pools bind to the event loop that created their
    connections. A test that drives a coroutine via ``asyncio.run()`` (its own
    short-lived loop — common when exercising Celery task bodies) can leave a
    connection bound to a now-closed loop inside the *shared* module-level
    client. A later test that reuses that client then raises "Event loop is
    closed" — which surfaces, since the quota meter added in this branch, as a
    503 on the first authenticated job submission that runs afterwards.

    Clearing the async singletons (module globals + manager attributes) forces
    each test to lazily re-init the clients on its own running loop via
    get_redis_client()/get_redis_cache_client(). Sync clients are untouched (no
    loop affinity), and production is single-loop so this is test-only.
    """
    import app.core.redis as _redis_mod

    _redis_mod.redis_client = None
    _redis_mod.redis_cache_client = None
    _redis_mod.redis_manager.redis_client = None
    _redis_mod.redis_manager.redis_cache_client = None
    yield


@pytest.fixture(autouse=True)
def relax_missing_recorder_file(monkeypatch):
    from app.services import latex_service as _ls

    _real = _ls.find_recorder_read_escape

    def _tolerate_missing(fls_file, workspace, *, require_recorder=True):
        return _real(fls_file, workspace, require_recorder=False)

    for module in (
        "app.services.latex_service",
        "app.workers.latex_worker",
        "app.workers.orchestrator",
    ):
        monkeypatch.setattr(f"{module}.find_recorder_read_escape", _tolerate_missing)
    yield


# ── Dependency Overrides ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def override_get_db(request):
    """Override get_db dependency to use the test session.

    ``db_session`` is resolved lazily so a static suite (which touches no route
    and no model) does not drag in Postgres via this autouse fixture — see
    ``_SKIP_INFRA`` above.
    """
    if _SKIP_INFRA:
        yield
        return

    db_session: AsyncSession = request.getfixturevalue("db_session")

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
        required_columns = {
            ("users", "role"),
            ("users", "github_access_token"),
            ("users", "dropbox_access_token"),
            ("resumes", "archived_at"),
            ("resumes", "dropbox_sync_enabled"),
            ("resumes", "document_type"),
            ("resumes", "structured_content"),
            ("resumes", "structured_version"),
            ("resumes", "selected_template_id"),
            ("resumes", "content_source"),
            ("resumes", "builder_status"),
        }
        for table_name, column_name in required_columns:
            result = await conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = :table_name
                      AND column_name = :column_name
                    """
                ),
                {"table_name": table_name, "column_name": column_name},
            )
            if result.scalar() != 1:
                pytest.fail(
                    "Test database schema is out of date. "
                    "Run `make test-db-setup` before running backend tests."
                )
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

    # Cleanup: delete rows inserted by tests (identified by test_ prefix).
    # Wrapped in try/except to survive transient deadlocks that can occur when
    # multiple session-scoped fixture teardowns run concurrently (pytest-asyncio).
    try:
        async with engine.begin() as conn:
            # Delete child rows first (FK constraints)
            await conn.execute(text("DELETE FROM resumes WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_%')"))
            await conn.execute(text("DELETE FROM compilations WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_%')"))
            await conn.execute(text("DELETE FROM optimizations WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_%')"))
            await conn.execute(text("DELETE FROM usage_analytics WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_%')"))
            await conn.execute(text("DELETE FROM deep_analysis_trials WHERE device_fingerprint LIKE 'test_%'"))
            await conn.execute(text("DELETE FROM resume_job_matches WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_%')"))
            await conn.execute(text("DELETE FROM cover_letters WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_%')"))
            await conn.execute(text("DELETE FROM job_applications WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_%')"))
            await conn.execute(text("DELETE FROM interview_prep WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_%')"))
            # Clean up test templates (inserted by test_template_routes — all prefixed with test_tmpl_)
            await conn.execute(text("DELETE FROM resume_templates WHERE name LIKE 'test_tmpl_%'"))
            # Clean up workspace data (CASCADE from user deletion handles this too, but be explicit)
            await conn.execute(text("DELETE FROM workspaces WHERE owner_id IN (SELECT id FROM users WHERE email LIKE 'test_%@example.com')"))
            # Then delete parent rows
            await conn.execute(text("DELETE FROM session WHERE token LIKE 'test_sess_%'"))
            await conn.execute(text("DELETE FROM users WHERE email LIKE 'test_%@example.com'"))
    except Exception:
        # Teardown cleanup is best-effort; a deadlock or connection error here
        # does not indicate a test failure — rows will be cleaned on next run.
        pass
    await engine.dispose()


@pytest.fixture(scope="session")
async def db_session_factory(test_engine):
    """Expose the async session factory for tests that need to inject it."""
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture
async def db_session(db_session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with db_session_factory() as session:
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
    # ON CONFLICT (id) only suppresses the primary-key collision (effectively impossible
    # with a fresh UUID). Email conflicts will raise clearly rather than silently skip
    # the INSERT, which would leave user_id absent from the users table.
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Test User', true, 'free', 'active', false) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": f"test_{user_id.replace('-', '')}@example.com"},
    )
    await db_session.commit()
    token = await _insert_session(db_session, user_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def pro_auth_headers(db_session: AsyncSession) -> dict:
    """Authorization headers for a PRO test user (unlimited plan quotas).

    The default ``auth_headers`` user is on the FREE plan, whose compile and
    optimization allowances are enforced by the usage meter (see
    test_usage_quotas.py). Tests that exercise the mechanics of an
    AI/optimization route — rather than the money meter itself — should use this
    fixture so the allowance is never the thing under test.
    """
    user_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Pro Test User', true, 'pro', 'active', false) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": f"test_{user_id.replace('-', '')}@example.com"},
    )
    await db_session.commit()
    token = await _insert_session(db_session, user_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def auth_headers2(db_session: AsyncSession) -> dict:
    """Authorization headers for a second independent test user."""
    user_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Test User 2', true, 'free', 'active', false) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": f"test_{user_id.replace('-', '')}@example.com"},
    )
    await db_session.commit()
    token = await _insert_session(db_session, user_id)
    return {"Authorization": f"Bearer {token}"}
