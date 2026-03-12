"""
Auto-save worker — creates checkpoint records after successful compilations.

Runs on the 'cleanup' queue (lightweight, no Redis pub/sub needed).
Uses synchronous DB access via sqlalchemy sync engine to avoid asyncio
complications inside Celery workers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from ..core.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.auto_save_worker.record_auto_save_checkpoint",
    queue="cleanup",
    max_retries=1,
    soft_time_limit=30,
    time_limit=60,
    ignore_result=True,
)
def record_auto_save_checkpoint(
    resume_id: str,
    user_id: str,
    latex_content: str,
) -> None:
    """
    Create an auto-save checkpoint after a successful compile.

    Dedup: skip if latest auto-save for this resume is < 5 minutes old.
    Pruning: keep at most 20 auto-saves per resume (delete oldest).
    """
    import asyncio

    asyncio.run(_do_auto_save(resume_id, user_id, latex_content))


async def _do_auto_save(resume_id: str, user_id: str, latex_content: str) -> None:
    # Build async engine from settings
    import os

    from sqlalchemy import delete as sa_delete
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ..database.models import Optimization
    from ..utils.db_url import normalize_database_url
    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        logger.warning("DATABASE_URL not set — cannot auto-save checkpoint")
        return
    db_url = normalize_database_url(raw_url)
    engine = create_async_engine(db_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with Session() as session:
            # Dedup: check if latest auto-save is < 5 min old
            result = await session.execute(
                select(Optimization)
                .where(
                    Optimization.resume_id == resume_id,
                    Optimization.user_id == user_id,
                    Optimization.is_auto_save.is_(True),
                )
                .order_by(Optimization.created_at.desc())
                .limit(1)
            )
            latest = result.scalar_one_or_none()

            if latest and latest.created_at:
                # Make comparison timezone-aware
                latest_time = latest.created_at
                if latest_time.tzinfo is None:
                    latest_time = latest_time.replace(tzinfo=timezone.utc)
                threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
                if latest_time > threshold:
                    logger.debug(
                        f"Skipping auto-save for resume {resume_id}: "
                        f"last auto-save was {latest_time}"
                    )
                    return

            # Insert new auto-save checkpoint
            now = datetime.now(timezone.utc)
            label = f"Auto-save — {now.strftime('%b %d, %H:%M')}"

            cp = Optimization(
                id=str(uuid4()),
                user_id=user_id,
                resume_id=resume_id,
                original_latex=latex_content,
                optimized_latex=latex_content,
                job_description="",
                provider="auto_save",
                model="auto",
                is_checkpoint=True,
                is_auto_save=True,
                checkpoint_label=label,
            )
            session.add(cp)
            await session.commit()

            # Pruning: keep at most 20 auto-saves per resume
            count_result = await session.execute(
                select(Optimization.id)
                .where(
                    Optimization.resume_id == resume_id,
                    Optimization.user_id == user_id,
                    Optimization.is_auto_save.is_(True),
                )
                .order_by(Optimization.created_at.desc())
            )
            all_ids = [row[0] for row in count_result.all()]

            if len(all_ids) > 20:
                ids_to_delete = all_ids[20:]
                await session.execute(
                    sa_delete(Optimization).where(
                        Optimization.id.in_(ids_to_delete)
                    )
                )
                await session.commit()
                logger.info(
                    f"Pruned {len(ids_to_delete)} old auto-saves for resume {resume_id}"
                )

            logger.info(f"Auto-save checkpoint created for resume {resume_id}")
    finally:
        await engine.dispose()
