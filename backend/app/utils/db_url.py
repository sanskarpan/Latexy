"""Shared DATABASE_URL resolution + normalisation for asyncpg."""

import os
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def normalize_database_url(url: str) -> str:
    """Normalise a PostgreSQL DSN for use with SQLAlchemy + asyncpg.

    - Converts any postgres:// / postgresql:// / postgresql+driver:// scheme
      to ``postgresql+asyncpg://``.
    - Replaces ``sslmode=require`` with ``ssl=require`` (asyncpg convention).
    - Strips the ``channel_binding`` query parameter (unsupported by asyncpg).
    - Rebuilds the query string cleanly — no orphaned ``?`` or ``&`` characters.
    """
    if not url:
        raise ValueError("DATABASE_URL is empty")

    # Normalise scheme
    url = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql+asyncpg://", url)

    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    # sslmode -> ssl
    if "sslmode" in params:
        params["ssl"] = params.pop("sslmode")

    # Drop channel_binding
    params.pop("channel_binding", None)

    # Rebuild — use doseq=True since parse_qs returns lists
    new_query = urlencode(params, doseq=True)
    cleaned = parsed._replace(query=new_query)
    return urlunparse(cleaned)


def resolve_database_url() -> str:
    """Return the normalised DSN that EVERY worker-side connection must use.

    Worker helpers used to resolve this ad hoc — some read ``os.environ`` only,
    some fell back to ``settings.DATABASE_URL``. Those two can point at
    DIFFERENT databases (the repo's root ``.env`` carries a hosted DSN while the
    dev script exports a local one), which is catastrophic for any code that
    writes rows in one place and verifies them in another (see
    cleanup_worker._prune_orphaned_compilation_objects). One resolver, one
    answer.

    ``settings.DATABASE_URL`` already layers the process environment over the
    .env files, but the env var is read directly first so a value exported after
    settings were constructed still wins.

    Returns "" when nothing is configured (callers must treat that as "cannot
    reach the database", never as "the database said no").
    """
    from ..core.config import settings

    raw = os.environ.get("DATABASE_URL", "") or settings.DATABASE_URL
    return normalize_database_url(raw) if raw else ""


def database_identity(url: str) -> str:
    """Return ``host:port/dbname`` for a DSN — safe to log (no credentials)."""
    if not url:
        return "unconfigured"
    parsed = urlparse(url)
    host = parsed.hostname or "?"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{host}{port}{parsed.path or ''}"
