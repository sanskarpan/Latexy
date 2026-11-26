"""Privacy-safe template catalog event capture.

Template events live in the existing ``usage_analytics`` JSON metadata column so
no migration is required. Every row stores only:

* a canonical event action (``template_view``, ``template_select``,
  ``template_use``, ``export`` or ``compile``),
* the public template id,
* the server-derived plan family at the time of the event,
* an optional idempotency key supplied by the caller.

No template source, résumé content, document text, IP address, user agent or
free-form client metadata is accepted here. Admin reporting reads aggregate
counts only and never returns per-user template history.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import resolve_plan_family
from ..core.logging import get_logger
from ..database import models

logger = get_logger(__name__)

CLIENT_TEMPLATE_EVENTS = {
    "view": "template_view",
    "select": "template_select",
}
USE_TEMPLATE_EVENT = "template_use"
# The existing growth funnel already records downloads as ``export``; reuse the
# same action so template performance and activation count the same milestone.
EXPORT_TEMPLATE_EVENT = "export"
COMPILE_TEMPLATE_EVENT = "compile"

TEMPLATE_EVENT_ACTIONS = frozenset(
    {
        *CLIENT_TEMPLATE_EVENTS.values(),
        USE_TEMPLATE_EVENT,
        EXPORT_TEMPLATE_EVENT,
        COMPILE_TEMPLATE_EVENT,
    }
)

_ANONYMOUS_PLAN = "anonymous"


def normalize_template_id(value: Any) -> Optional[str]:
    """Return a canonical UUID string, or None when the value is not one."""
    if value is None:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


class TemplateAnalyticsService:
    """Record allowlisted template events with server-owned attribution."""

    async def resolve_actor_plan(
        self,
        db: AsyncSession,
        user_id: Optional[str],
    ) -> str:
        """Resolve the current plan family from server state.

        Anonymous callers are bucketed separately. A lookup failure degrades to
        ``free`` rather than blocking a compile, export or template event.
        """
        if not user_id:
            return _ANONYMOUS_PLAN
        try:
            row = await db.execute(select(models.User.subscription_plan).where(models.User.id == user_id))
            return resolve_plan_family(row.scalar_one_or_none())
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Template event plan lookup failed (%s)", type(exc).__name__)
            return "free"

    async def record_client_event(
        self,
        db: AsyncSession,
        *,
        event: str,
        template_id: str,
        user_id: Optional[str],
        event_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record a browser-originated ``view`` or ``select`` event.

        The template must currently exist. The event id (when supplied) makes a
        retried request idempotent without turning repeated legitimate views
        into a single row.
        """
        action = CLIENT_TEMPLATE_EVENTS.get(event)
        if action is None:
            raise ValueError("event must be view or select")
        canonical_template_id = normalize_template_id(template_id)
        if canonical_template_id is None:
            raise ValueError("template_id must be a valid UUID")

        exists = (
            await db.execute(select(models.ResumeTemplate.id).where(models.ResumeTemplate.id == canonical_template_id))
        ).scalar_one_or_none()
        if exists is None:
            raise LookupError("Template not found")

        plan = await self.resolve_actor_plan(db, user_id)
        duplicate = await self._insert_event(
            db,
            action=action,
            template_id=canonical_template_id,
            user_id=user_id,
            plan=plan,
            event_id=event_id,
        )
        return {
            "recorded": action,
            "template_id": canonical_template_id,
            "plan": plan,
            "duplicate": duplicate,
        }

    async def record_use(
        self,
        db: AsyncSession,
        *,
        template_id: str,
        user_id: str,
        resume_id: str,
    ) -> None:
        """Record a successful template use, keyed by the created résumé.

        Repeated delivery of the same response cannot double count because the
        created résumé id is the idempotency key.
        """
        canonical_template_id = normalize_template_id(template_id)
        if canonical_template_id is None:
            return
        plan = await self.resolve_actor_plan(db, user_id)
        try:
            await self._insert_event(
                db,
                action=USE_TEMPLATE_EVENT,
                template_id=canonical_template_id,
                user_id=user_id,
                plan=plan,
                event_id=f"template-use:{resume_id}",
            )
        except Exception as exc:  # pragma: no cover - analytics never blocks use
            await db.rollback()
            logger.warning("Template use event failed (%s)", type(exc).__name__)

    async def _insert_event(
        self,
        db: AsyncSession,
        *,
        action: str,
        template_id: str,
        user_id: Optional[str],
        plan: str,
        event_id: Optional[str],
    ) -> bool:
        """Insert one event row; return True when an idempotent replay was found."""
        if event_id:
            # Serialize concurrent retries for the same key without a new table
            # or unique index. The lock is released with this transaction.
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"template-event:{action}:{event_id}"},
            )
            existing = (
                await db.execute(
                    select(models.UsageAnalytics.id)
                    .where(
                        models.UsageAnalytics.action == action,
                        models.UsageAnalytics.event_metadata["event_id"].as_string() == event_id,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return True

        metadata: dict[str, Any] = {
            "template_id": template_id,
            "plan": plan,
        }
        if event_id:
            metadata["event_id"] = event_id
        db.add(
            models.UsageAnalytics(
                user_id=user_id,
                action=action,
                resource_type="template",
                event_metadata=metadata,
            )
        )
        await db.commit()
        return False


template_analytics_service = TemplateAnalyticsService()
