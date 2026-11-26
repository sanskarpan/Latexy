"""Scheduled, non-destructive retention previews.

The beat task never purges. It runs the same dry-run used by the admin panel for
enabled policies whose schedule is due, recording a bounded run and audit row so
operators can see the next/last preview and affected counts. Destructive purges
always require an explicit, confirmed admin action.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from ..core.celery_app import celery_app
from ..core.logging import get_logger
from ..services import admin_retention_service
from ..services.admin_audit_service import AdminActor

logger = get_logger(__name__)

SYSTEM_PREVIEW_ACTOR = AdminActor(user_id="system", email=None, role="admin")


async def _run_due_previews(limit: int) -> dict[str, Any]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from ..core.config import settings
    from ..utils.db_url import normalize_database_url

    engine = create_async_engine(
        normalize_database_url(settings.DATABASE_URL), poolclass=NullPool
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    previewed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    try:
        async with factory() as session:
            overview = await admin_retention_service.get_overview(
                session, now=datetime.now(timezone.utc)
            )
        due = [
            item["data_class"]
            for item in overview["classes"]
            if item["enabled"] and item["schedule_due"]
        ]
        for data_class in due:
            async with factory() as session:
                try:
                    await admin_retention_service.execute_run(
                        session,
                        data_class=data_class,
                        dry_run=True,
                        reason="Scheduled retention preview",
                        confirm=False,
                        limit=max(1, min(int(limit), 1000)),
                        idempotency_key=None,
                        actor=SYSTEM_PREVIEW_ACTOR,
                    )
                    previewed.append(data_class)
                except admin_retention_service.RetentionConflict:
                    await session.rollback()
                    skipped.append(data_class)
                except Exception as exc:
                    await session.rollback()
                    failed.append(data_class)
                    logger.warning(
                        "Scheduled retention preview failed",
                        extra={"data_class": data_class, "error_type": type(exc).__name__},
                    )
        return {"previewed": previewed, "skipped": skipped, "failed": failed}
    finally:
        await engine.dispose()


@celery_app.task(
    bind=True,
    name="app.workers.retention_worker.run_due_retention_previews_task",
    max_retries=0,
)
def run_due_retention_previews_task(self, limit: int = 200) -> dict[str, Any]:
    """Record dry-run previews for due policies; never deletes or scrubs."""
    try:
        return asyncio.run(_run_due_previews(limit))
    except Exception as exc:  # noqa: BLE001 - a scheduler probe must not crash beat
        logger.warning(
            "Scheduled retention preview sweep deferred",
            extra={"error_type": type(exc).__name__},
        )
        return {"previewed": [], "skipped": [], "failed": ["*"]}
