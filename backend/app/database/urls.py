"""Pure database URL conversion for the installed synchronous PostgreSQL driver."""

from urllib.parse import parse_qsl, urlsplit

from sqlalchemy.engine import make_url


def normalize_sync_database_url(database_url: str) -> str:
    """Select pinned psycopg2 explicitly, preserving credentials and URL options.

    SQLAlchemy 2.1 changed the unqualified PostgreSQL default to psycopg 3.
    Synchronous maintenance paths use the repository's psycopg2 dependency;
    asynchronous application connections continue to select asyncpg separately.
    """
    try:
        url = make_url(database_url)
        # SQLAlchemy drops blank query values. Check the original query before
        # conversion so an explicit empty SSL setting cannot select a default.
        blank_ssl_option = any(
            key in {"ssl", "sslmode"} and value == ""
            for key, value in parse_qsl(urlsplit(database_url).query, keep_blank_values=True)
        )
    except Exception:
        raise ValueError("DATABASE_URL must be a valid SQLAlchemy URL") from None
    if blank_ssl_option:
        raise ValueError("DATABASE_URL has a blank SSL query option")
    if url.drivername.partition("+")[0] not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must use a supported PostgreSQL driver")
    return url.set(drivername="postgresql+psycopg2").render_as_string(hide_password=False)
