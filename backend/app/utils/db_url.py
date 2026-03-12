"""Shared DATABASE_URL normalisation for asyncpg."""

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
