"""GitHub project-import service (Feature 1 — external sources to resume).

Pure, testable building blocks that turn a connected user's **public** GitHub
projects into resume-ready ``ProjectEvidence`` records:

    fetch_candidate_repos → rank_repos → (fetch_repo_readme + fetch_repo_languages)
        → summarize_project → build_project_evidence

PRIVACY: this module reads PUBLIC repository data only. The GraphQL query is
scoped to ``ownerAffiliations: OWNER`` and every REST call targets a repo the
authenticated user owns, but only public fields (README, languages, stars) are
consumed. No private repository content is ever read, summarized, or stored.

All network + LLM calls are injectable (pass a ``client``) so tests can mock
them without touching the network. Per-user REST calls are made serially by the
caller (the worker) to stay well under GitHub's secondary rate limits.
"""

from __future__ import annotations

import base64
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL = "https://api.github.com/graphql"

# Minimum README length (chars) for a repo to count as documented. Repos with a
# shorter/absent README are excluded from ranking — there is nothing to summarize.
_MIN_README_CHARS = 100

# README excerpt is truncated to ~1500 tokens before it reaches the LLM. ~4 chars
# per token is the usual English approximation, so 6000 chars is the ceiling.
_README_TRUNCATE_CHARS = 6000

_MAX_RESULTS = 6


# ── HTTP helpers ─────────────────────────────────────────────────────────────


def _headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


# One GraphQL call fetches pinned + top-starred owned, non-fork repos plus README
# existence, staying at ~1 point of the 5,000/hr budget. ``viewer`` is the
# authenticated user, so no username round-trip is needed.
_REPO_FIELDS = """
  name
  description
  url
  stargazerCount
  forkCount
  isArchived
  pushedAt
  primaryLanguage { name }
  repositoryTopics(first: 10) { nodes { topic { name } } }
  owner { login }
  readmeMd: object(expression: "HEAD:README.md") { ... on Blob { byteSize } }
  readmePlain: object(expression: "HEAD:README") { ... on Blob { byteSize } }
  readmeRst: object(expression: "HEAD:README.rst") { ... on Blob { byteSize } }
  readmeLower: object(expression: "HEAD:readme.md") { ... on Blob { byteSize } }
"""

_CANDIDATES_QUERY = f"""
query {{
  viewer {{
    login
    pinnedItems(first: 6, types: REPOSITORY) {{
      nodes {{ ... on Repository {{ {_REPO_FIELDS} }} }}
    }}
    repositories(
      first: 100
      ownerAffiliations: OWNER
      isFork: false
      orderBy: {{ field: STARGAZERS, direction: DESC }}
    ) {{
      nodes {{ {_REPO_FIELDS} }}
    }}
  }}
}}
"""


def _readme_bytes(node: Dict[str, Any]) -> int:
    """Largest byteSize across the README aliases (0 when none exist)."""
    sizes = []
    for alias in ("readmeMd", "readmePlain", "readmeRst", "readmeLower"):
        obj = node.get(alias)
        if isinstance(obj, dict) and isinstance(obj.get("byteSize"), int):
            sizes.append(obj["byteSize"])
    return max(sizes) if sizes else 0


def _parse_repo_node(node: Dict[str, Any], pinned: bool) -> Optional[Dict[str, Any]]:
    """Normalize a GraphQL Repository node to a flat candidate dict."""
    if not node or not node.get("name"):
        return None

    primary = node.get("primaryLanguage") or {}
    topic_nodes = (node.get("repositoryTopics") or {}).get("nodes") or []
    topics = [
        t["topic"]["name"]
        for t in topic_nodes
        if isinstance(t, dict) and t.get("topic", {}).get("name")
    ]
    owner = (node.get("owner") or {}).get("login") or ""

    return {
        "name": node["name"],
        "owner": owner,
        "description": node.get("description"),
        "url": node.get("url"),
        "stars": node.get("stargazerCount") or 0,
        "forks": node.get("forkCount") or 0,
        "primary_language": primary.get("name"),
        "topics": topics,
        "pushed_at": node.get("pushedAt"),
        "is_archived": bool(node.get("isArchived")),
        "readme_bytes": _readme_bytes(node),
        "pinned": pinned,
    }


def fetch_candidate_repos(
    token: str, *, client: Optional[httpx.Client] = None
) -> List[Dict[str, Any]]:
    """Fetch pinned + top owned public repos in ONE GraphQL call.

    Returns a de-duplicated list of normalized candidate dicts. Pinned repos are
    flagged (``pinned=True``) so ranking can boost them.
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=20)
    try:
        resp = client.post(
            GITHUB_GRAPHQL,
            headers=_headers(token),
            json={"query": _CANDIDATES_QUERY},
        )
        resp.raise_for_status()
        data = resp.json()
    finally:
        if owns_client:
            client.close()

    if data.get("errors"):
        logger.warning(f"GitHub GraphQL returned errors: {data['errors']}")

    viewer = (data.get("data") or {}).get("viewer") or {}
    pinned_nodes = (viewer.get("pinnedItems") or {}).get("nodes") or []
    repo_nodes = (viewer.get("repositories") or {}).get("nodes") or []

    by_key: Dict[str, Dict[str, Any]] = {}
    # Pinned first so a repo appearing in both keeps pinned=True.
    for node in pinned_nodes:
        parsed = _parse_repo_node(node, pinned=True)
        if parsed:
            by_key[f"{parsed['owner']}/{parsed['name']}"] = parsed
    for node in repo_nodes:
        parsed = _parse_repo_node(node, pinned=False)
        if parsed:
            key = f"{parsed['owner']}/{parsed['name']}"
            if key not in by_key:
                by_key[key] = parsed

    return list(by_key.values())


# ── Ranking (pure) ───────────────────────────────────────────────────────────


def _months_since(pushed_at: Optional[str]) -> float:
    """Months since the last push. Large (→ recency term ~0) when unknown."""
    if not pushed_at:
        return 120.0
    try:
        dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 120.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    return max(delta.days, 0) / 30.0


# A pinned repo is user-curated — the single strongest signal — so it always
# outranks organic repos. Larger than any organic score the formula can produce.
_PINNED_BOOST = 100.0


def _score(repo: Dict[str, Any]) -> float:
    stars = repo.get("stars", 0) or 0
    forks = repo.get("forks", 0) or 0
    has_readme = 1.0 if (repo.get("readme_bytes", 0) or 0) >= _MIN_README_CHARS else 0.0
    has_topics = 1.0 if repo.get("topics") else 0.0
    has_description = 1.0 if repo.get("description") else 0.0

    score = (
        3.0 * math.log10(stars + 1)
        + 1.5 * math.log10(forks + 1)
        + 2.0 * math.exp(-_months_since(repo.get("pushed_at")) / 12.0)
        + 1.0 * has_readme
        + 0.5 * has_topics
        + 0.5 * has_description
    )
    if repo.get("pinned"):
        score += _PINNED_BOOST
    return score


def rank_repos(repos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rank candidate repos and return the top ``_MAX_RESULTS``.

    Excludes archived repos and repos whose README is shorter than
    ``_MIN_README_CHARS`` (nothing worth summarizing). Pinned repos always sort
    to the top via a large boost. Each returned dict carries its ``score``.
    """
    ranked: List[Dict[str, Any]] = []
    for repo in repos:
        if repo.get("is_archived"):
            continue
        if (repo.get("readme_bytes", 0) or 0) < _MIN_README_CHARS:
            continue
        scored = dict(repo)
        scored["score"] = _score(repo)
        ranked.append(scored)

    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked[:_MAX_RESULTS]


# ── Per-repo REST fetches ────────────────────────────────────────────────────


def fetch_repo_readme(
    token: str, owner: str, name: str, *, client: Optional[httpx.Client] = None
) -> Optional[str]:
    """Fetch and base64-decode a repo's README. None when absent/too short/error."""
    owns_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        resp = client.get(
            f"{GITHUB_API}/repos/{owner}/{name}/readme", headers=_headers(token)
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning(f"README fetch failed for {owner}/{name}: {exc}")
        return None
    finally:
        if owns_client:
            client.close()

    content = data.get("content")
    if not content:
        return None
    try:
        text = base64.b64decode(content).decode("utf-8", errors="replace")
    except (ValueError, TypeError) as exc:
        logger.warning(f"README decode failed for {owner}/{name}: {exc}")
        return None

    return text if len(text.strip()) >= _MIN_README_CHARS else None


def fetch_repo_languages(
    token: str, owner: str, name: str, *, client: Optional[httpx.Client] = None
) -> Dict[str, int]:
    """Fetch a repo's language byte breakdown ({language: bytes}). Empty on error."""
    owns_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        resp = client.get(
            f"{GITHUB_API}/repos/{owner}/{name}/languages", headers=_headers(token)
        )
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning(f"Languages fetch failed for {owner}/{name}: {exc}")
        return {}
    finally:
        if owns_client:
            client.close()

    return {k: v for k, v in data.items() if isinstance(v, int)}


# ── LLM summarization ────────────────────────────────────────────────────────

_SUMMARY_SYSTEM_PROMPT = (
    "You are a resume-writing assistant. Given a GitHub project's metadata and "
    "README, produce concise, resume-ready material. Respond with ONLY a JSON "
    "object, no prose and no markdown fences, of the exact shape:\n"
    '{"summary": "one or two sentences on what the project does and its impact", '
    '"suggested_bullets": ["achievement-oriented resume bullet", "..."], '
    '"tech": ["Key", "Technologies"]}\n'
    "Rules: 2-4 suggested_bullets, each starting with a strong action verb and "
    "quantified where the README supports it; never invent metrics that are not "
    "present; tech is the concrete stack (languages, frameworks, infra)."
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json_object(text: str) -> Dict[str, Any]:
    """Best-effort parse of an LLM JSON object (tolerates markdown fences)."""
    if not text:
        return {}
    candidate = text.strip()
    fence = _JSON_FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _normalize_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if isinstance(v, (str, int, float)) and str(v).strip()]


def summarize_project(
    repo: Dict[str, Any],
    readme: Optional[str],
    languages: Dict[str, int],
    api_key: Optional[str],
    *,
    client: Any = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Summarize one project into ``{summary, suggested_bullets, tech}`` via the LLM.

    The README is truncated to ~1500 tokens before it reaches the prompt. The
    caller's BYOK key takes precedence over the platform OpenAI key. On any LLM
    error, or when neither key exists, the function degrades to a metadata-only
    summary so a single bad repo never fails the whole import.
    """
    truncated_readme = (readme or "")[:_README_TRUNCATE_CHARS]
    lang_names = list(languages.keys())

    user_prompt = (
        f"Project: {repo.get('name')}\n"
        f"Description: {repo.get('description') or '(none)'}\n"
        f"Primary language: {repo.get('primary_language') or '(unknown)'}\n"
        f"Languages: {', '.join(lang_names) if lang_names else '(unknown)'}\n"
        f"Topics: {', '.join(repo.get('topics') or []) or '(none)'}\n"
        f"Stars: {repo.get('stars', 0)}  Forks: {repo.get('forks', 0)}\n\n"
        f"README (truncated):\n{truncated_readme or '(no README)'}"
    )

    fallback_tech = list(dict.fromkeys(lang_names + (repo.get("topics") or [])))[:8]

    effective_api_key = api_key or settings.OPENAI_API_KEY
    if not effective_api_key:
        return {
            "summary": repo.get("description") or "",
            "suggested_bullets": [],
            "tech": fallback_tech,
        }

    try:
        if client is None:
            import openai  # noqa: PLC0415 — lazy so import stays cheap/offline-safe

            client = openai.OpenAI(api_key=effective_api_key)
        response = client.chat.completions.create(
            model=model or settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=600,
            temperature=0.4,
        )
        raw = response.choices[0].message.content or ""
    except Exception as exc:
        logger.warning(f"summarize_project LLM call failed for {repo.get('name')}: {exc}")
        return {
            "summary": repo.get("description") or "",
            "suggested_bullets": [],
            "tech": fallback_tech,
        }

    parsed = _extract_json_object(raw)
    tech = _normalize_str_list(parsed.get("tech")) or fallback_tech
    return {
        "summary": (str(parsed.get("summary")).strip() if parsed.get("summary") else "")
        or repo.get("description")
        or "",
        "suggested_bullets": _normalize_str_list(parsed.get("suggested_bullets")),
        "tech": tech,
    }


# ── Evidence normalization ───────────────────────────────────────────────────


def build_project_evidence(repo: Dict[str, Any], summary: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a repo + its LLM summary into a ``ProjectEvidence`` record."""
    return {
        "source": "github",
        "title": repo.get("name"),
        "description": summary.get("summary") or repo.get("description") or "",
        "tech": summary.get("tech") or [],
        "metrics": {
            "stars": repo.get("stars", 0) or 0,
            "forks": repo.get("forks", 0) or 0,
        },
        "dates": {"last_active": repo.get("pushed_at")},
        "url": repo.get("url"),
        "suggested_bullets": summary.get("suggested_bullets") or [],
        "raw_excerpt": (repo.get("raw_excerpt") or "")[:2000],
    }


# ── Redis result envelope (shared by worker + endpoint) ──────────────────────

# Candidate evidence is cached in Redis (not Postgres) for v1 — Modal does not
# auto-run migrations, so a DB table would need a manual migration step. TTL ~1h.
IMPORT_RESULT_TTL = 3600


def import_result_key(job_id: str) -> str:
    """Redis key holding an import job's result envelope."""
    return f"latexy:github_import:{job_id}"


def encode_result(payload: Dict[str, Any]) -> str:
    """Serialize a result envelope to a base64(JSON) string for Redis."""
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def decode_result(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """Decode a base64(JSON) result envelope. None on miss/corruption."""
    if not raw:
        return None
    try:
        return json.loads(base64.b64decode(raw).decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
