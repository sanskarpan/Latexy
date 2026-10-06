"""Conservative ESCO skill lookup and normalization.

Only exact preferred/alternative-label matches are normalized. Broad search
hits are returned for discovery but never silently relabel a user's skill.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

import httpx

from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import cache_manager

logger = get_logger(__name__)

ESCO_API_URL = "https://ec.europa.eu/esco/api/search"
ESCO_VERSION = "v1.2.1"
ESCO_LANGUAGES = frozenset(
    {
        "ar",
        "bg",
        "cs",
        "da",
        "de",
        "el",
        "en",
        "es",
        "et",
        "fi",
        "fr",
        "ga",
        "hr",
        "hu",
        "is",
        "it",
        "lt",
        "lv",
        "mt",
        "nl",
        "no",
        "pl",
        "pt",
        "ro",
        "sk",
        "sl",
        "sv",
        "uk",
    }
)
_SKILL_URI_PREFIX = "http://data.europa.eu/esco/skill/"
_CACHE_TTL = 30 * 24 * 60 * 60


def _normalized_label(value: str) -> str:
    return re.sub(r"[^\w+#]+", " ", value.casefold(), flags=re.UNICODE).strip()


class ESCOService:
    async def search(
        self,
        query: str,
        *,
        language: str = "en",
        limit: int = 8,
        client: httpx.AsyncClient | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        query = query.strip()
        if not 2 <= len(query) <= 100:
            raise ValueError("Skill query must contain 2 to 100 characters")
        if language not in ESCO_LANGUAGES:
            raise ValueError("Unsupported ESCO language")
        if not 1 <= limit <= 20:
            raise ValueError("ESCO result limit must be between 1 and 20")
        if settings.normalized_environment == "test" and client is None:
            return [], False

        digest = hashlib.sha256(f"{ESCO_VERSION}:{language}:{query.casefold()}:{limit}".encode()).hexdigest()
        cache_key = f"esco:search:{digest}"
        try:
            cached = await cache_manager.get(cache_key)
            if isinstance(cached, list):
                return cached, True
        except Exception:
            pass

        owns_client = client is None
        http = client or httpx.AsyncClient(
            timeout=httpx.Timeout(6.0),
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "Latexy/1.0 ESCO skill taxonomy"},
        )
        try:
            response = await http.get(
                ESCO_API_URL,
                params={
                    "text": query,
                    "language": language,
                    "type": "skill",
                    "limit": limit,
                    "full": "true",
                    "selectedVersion": ESCO_VERSION,
                    "viewObsolete": "false",
                },
            )
            response.raise_for_status()
            payload = response.json()
            raw_results = payload.get("_embedded", {}).get("results", [])
            if not isinstance(raw_results, list):
                raise ValueError("ESCO returned an invalid result collection")
            results: list[dict[str, Any]] = []
            for raw in raw_results[:limit]:
                if not isinstance(raw, dict):
                    continue
                uri = raw.get("uri")
                preferred = raw.get("preferredLabel")
                alternatives = raw.get("alternativeLabel")
                if not isinstance(uri, str) or not uri.startswith(_SKILL_URI_PREFIX):
                    continue
                preferred_label = (
                    preferred.get(language)
                    if isinstance(preferred, dict) and isinstance(preferred.get(language), str)
                    else raw.get("title")
                )
                if not isinstance(preferred_label, str) or not preferred_label.strip():
                    continue
                alt_labels = (
                    [item for item in alternatives.get(language, []) if isinstance(item, str)][:50]
                    if isinstance(alternatives, dict) and isinstance(alternatives.get(language), list)
                    else []
                )
                results.append(
                    {
                        "uri": uri,
                        "preferred_label": preferred_label.strip(),
                        "alternative_labels": alt_labels,
                        "language": language,
                    }
                )
            try:
                await cache_manager.set(cache_key, results, ttl=_CACHE_TTL)
            except Exception:
                pass
            return results, True
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("ESCO lookup unavailable", extra={"error_type": type(exc).__name__})
            return [], False
        finally:
            if owns_client:
                await http.aclose()

    async def normalize_many(self, skills: list[str], *, language: str = "en") -> tuple[list[dict[str, Any]], bool]:
        unique = list(dict.fromkeys(skill.strip() for skill in skills if skill.strip()))[:40]
        fallback = [
            {
                "input": skill,
                "preferred_label": skill,
                "uri": None,
                "matched": False,
            }
            for skill in unique
        ]
        if not unique or settings.normalized_environment == "test":
            return fallback, False

        semaphore = asyncio.Semaphore(8)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(6.0),
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "Latexy/1.0 ESCO skill taxonomy"},
        ) as client:

            async def normalize(skill: str) -> tuple[dict[str, Any], bool]:
                async with semaphore:
                    results, available = await self.search(skill, language=language, limit=5, client=client)
                needle = _normalized_label(skill)
                for candidate in results:
                    labels = [candidate["preferred_label"], *candidate["alternative_labels"]]
                    if any(_normalized_label(label) == needle for label in labels):
                        return {
                            "input": skill,
                            "preferred_label": candidate["preferred_label"],
                            "uri": candidate["uri"],
                            "matched": True,
                        }, available
                return {
                    "input": skill,
                    "preferred_label": skill,
                    "uri": None,
                    "matched": False,
                }, available

            pairs = await asyncio.gather(*(normalize(skill) for skill in unique))
        return [mapping for mapping, _ in pairs], bool(pairs) and all(available for _, available in pairs)


esco_service = ESCOService()
