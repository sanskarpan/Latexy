"""Load required modules before a worker installs per-task time limits.

Imports create no database engines, sessions, provider clients or renderer VMs.
In particular, asyncpg's native extension must not receive a Celery soft-limit
signal during its first import. Successful preparation is safe to inherit across
prefork children; each child still creates its own Redis and task-local resources.
"""
from functools import lru_cache
from importlib import import_module


@lru_cache(maxsize=1)
def prepare_worker_logging() -> None:
    """Modal inputs do not pass through the API's logging startup."""
    from .logging import setup_logging

    setup_logging()


@lru_cache(maxsize=2)
def prepare_worker_runtime(semantic_enabled: bool = False) -> None:
    from .engine_observability import engine_span

    # Memoization excludes warm no-op calls. This measures native imports and
    # ORM preparation, not image pull/boot or idle time before the first job.
    with engine_span("worker_initialization"):
        for module in (
            "asyncpg",
            "sqlalchemy.dialects.postgresql.asyncpg",
            "app.services.render_engine.cache_policy",
            "app.services.render_engine.artifacts",
            "app.services.render_engine.retention",
            "app.services.render_engine.geometry",
        ):
            import_module(module)
        if semantic_enabled:
            import_module("app.services.resume_engine.service")
        # Mapper relationship configuration is otherwise deferred to the first
        # ownership query. All models are loaded by retention above. Configure in
        # the parent so prefork children inherit the completed CPU-only metadata;
        # this opens no engine, session or socket and fails readiness on bad mappings.
        from ..database.connection import Base

        Base.registry.configure()
