"""Server-side PostHog capture with a conservative data boundary.

The backend mirrors first-party product events into PostHog. It never sends
résumé/LaTeX content, prompts, job descriptions, emails, names, tokens, API
keys, or raw provider errors. Only opaque IDs, enums, counts, durations, and
amounts are allowed through. If the SDK or key is absent, every call is a
no-op so analytics can never break a request.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)

_MAX_PROPERTIES = 25
_MAX_STRING_LENGTH = 200
_SENSITIVE_KEY_PARTS = (
    "email",
    "phone",
    "name",
    "address",
    "resume",
    "latex",
    "content",
    "prompt",
    "text",
    "token",
    "secret",
    "password",
    "auth",
    "cookie",
    "ssn",
    "birth",
    "salary",
    "job_description",
    "cover_letter",
)
_SAFE_KEY_ALLOWLIST = frozenset({"feature_key", "plan_key", "event_type", "surface", "route"})
# Client-originated events may only mirror a finite vocabulary. Without this,
# any authenticated caller could create unlimited PostHog event names (data
# poisoning / billable cardinality) through one generic tracking endpoint.
_MIRRORED_EVENT_TYPES = frozenset(
    {
        "page_view",
        "feature_usage",
        "compile",
        "optimize",
        "resume_created",
        "resume_forked",
        "academic_cv_converted",
        "export",
        "signup",
        "login",
        "share_viewed",
        "checkout_started",
        "upgrade_clicked",
        "ats_score",
        "cover_letter",
        "interview_prep",
        "error",
    }
)


def sanitize_posthog_properties(properties: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a bounded, flat property map with direct identifiers removed."""
    if not properties:
        return {}
    safe: Dict[str, Any] = {}
    for raw_key, value in properties.items():
        if len(safe) >= _MAX_PROPERTIES:
            break
        key = str(raw_key)[:80]
        lowered = key.casefold()
        # Never accept SDK-reserved or client-supplied dollar properties. This
        # is what makes the forced geoip/service assignment below authoritative.
        if lowered.startswith("$"):
            continue
        if key not in _SAFE_KEY_ALLOWLIST and any(part in lowered for part in _SENSITIVE_KEY_PARTS):
            continue
        if value is None or isinstance(value, bool):
            safe[key] = value
        elif isinstance(value, (int, float)):
            if value == value and value not in (float("inf"), float("-inf")):
                safe[key] = value
        elif isinstance(value, str):
            safe[key] = value[:_MAX_STRING_LENGTH]
        # Nested objects and arrays are intentionally dropped. They are the
        # easiest way for document content to leak into an analytics payload.
    return safe


class PostHogService:
    def __init__(self) -> None:
        self._client = None
        self._lock = threading.Lock()
        self._attempted = False

    @property
    def configured(self) -> bool:
        # Never send test-suite or local fixture traffic to the production
        # PostHog project. Explicitly configured development environments may
        # opt in by setting ENVIRONMENT=development.
        if settings.ENVIRONMENT.lower() in {"test", "testing"}:
            return False
        return bool(settings.POSTHOG_API_KEY) and bool(settings.POSTHOG_ENABLED)

    def _get_client(self):
        if not self.configured:
            return None
        if self._client is not None or self._attempted:
            return self._client
        with self._lock:
            if self._client is not None or self._attempted:
                return self._client
            self._attempted = True
            try:
                from posthog import Posthog

                self._client = Posthog(
                    settings.POSTHOG_API_KEY,
                    host=settings.POSTHOG_HOST,
                    sync_mode=False,
                    disabled=False,
                    disable_geoip=True,
                )
            except Exception as exc:  # pragma: no cover - import/config failure
                logger.warning("PostHog backend disabled (%s)", type(exc).__name__)
                self._client = None
        return self._client

    def capture(
        self,
        distinct_id: Optional[str],
        event: str,
        properties: Optional[Dict[str, Any]] = None,
        groups: Optional[Dict[str, str]] = None,
    ) -> None:
        if not distinct_id or not event:
            return
        client = self._get_client()
        if client is None:
            return
        payload = sanitize_posthog_properties(properties)
        payload["service"] = "backend"
        payload["environment"] = settings.ENVIRONMENT
        payload["$geoip_disable"] = True
        try:
            client.capture(event, distinct_id=str(distinct_id), properties=payload, groups=groups)
        except Exception as exc:  # pragma: no cover - network/SDK failure
            logger.warning("PostHog capture failed (%s)", type(exc).__name__)

    def capture_event(
        self,
        *,
        user_id: Optional[str],
        event_type: str,
        metadata: Optional[Dict[str, Any]] = None,
        source: str = "first_party_analytics",
    ) -> None:
        """Mirror a first-party telemetry event with a stable event prefix."""
        if not user_id:
            return
        safe_event = "".join(
            character if character.isalnum() or character in "_.:-" else "_"
            for character in str(event_type)
        )[:100]
        if safe_event not in _MIRRORED_EVENT_TYPES:
            # Keep arbitrary first-party event names out of the PostHog event
            # namespace. The first-party table remains available for audits.
            return
        properties = dict(metadata or {})
        properties["event_type"] = safe_event
        properties["source"] = source
        self.capture(str(user_id), f"backend_{safe_event}", properties)


posthog_service = PostHogService()
