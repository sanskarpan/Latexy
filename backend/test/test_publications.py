"""
Tests for Feature 58 — Publication List Auto-Generator.

Coverage map:
  ── Service unit tests (TestPublicationsServiceUnit) ──────────────────────────
  58U-01  fetch_from_orcid (mocked httpx) returns correctly parsed Publication list
  58U-02  fetch_from_orcid with 404 response raises ValueError containing "not found"
  58U-03  format_as_latex on empty list → ""
  58U-04  format_as_latex produces \\section{Publications}
  58U-05  format_as_latex produces \\begin{enumerate} / \\end{enumerate}
  58U-06  format_as_latex sorts by year descending (newest first)
  58U-07  _map_work_type: journal-article → "journal"
  58U-08  _map_work_type: conference-paper → "conference"
  58U-09  _map_work_type: preprint → "preprint"
  58U-10  _map_work_type: book-chapter → "book_chapter"
  58U-11  DOI produces \\href{https://doi.org/...} in formatted entry
  58U-12  Missing venue produces no \\textit{} in formatted entry

  ── HTTP integration tests (TestPublicationsEndpoint) ─────────────────────────
  58I-01  Valid ORCID → 200 with publications, latex_section, cached fields
  58I-02  Invalid ORCID format (too short) → 422
  58I-03  Invalid ORCID format (non-digit letters) → 422
  58I-04  ORCID 404 → 422 (not 404, not 500), detail contains "not found"
  58I-05  ORCID network error → 502
  58I-06  year_from filter removes publications with year < filter value
  58I-07  year_to filter removes publications with year > filter value
  58I-08  pub_types=["conference"] removes non-conference entries
  58I-09  latex_section contains \\begin{enumerate} and \\section{Publications}
  58I-10  Cache hit: patch cache_manager.get → response has cached=True
  58I-11  Empty ORCID works list (no groups) → 200, publications=[], latex_section=""
  58I-12  source="scholar" → 422 (pattern constraint; only "orcid" accepted for MVP)

  ── Authentication tests (TestPublicationsAuth) ────────────────────────────────
  58A-01  No Authorization header → 200 (endpoint uses get_current_user_optional)
  58A-02  Syntactically invalid Bearer token → 200 (auth failure treated as anonymous)
  58A-03  Expired session token → 200 (optional auth; expired ≠ 401)
  58A-04  Valid authenticated request → 200

Infrastructure notes:
  - httpx mock: always patch app.services.publications_service.httpx.AsyncClient
  - cache mock: patch app.api.ai_routes.cache_manager.get (AsyncMock)
  - No real ORCID network calls in any test
  - db_session: real Neon PostgreSQL, rolls back after each test
  - Redis: real localhost:6379/15, but cache_manager not initialized in tests
    (lifespan doesn't run) — cache tests use mock, not real Redis writes
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.publications_service import Publication, PublicationsService

# ── Shared constants ───────────────────────────────────────────────────────────

VALID_ORCID = "0000-0001-2345-6789"
INVALID_ORCID_SHORT = "0000-0001-2345"          # only 3 groups
INVALID_ORCID_LETTERS = "ABCD-0001-2345-6789"   # non-digit first group

#: Three-entry mock that exercises all three pub_types used by filter tests.
#: years: 2023 (journal), 2021 (conference), 2020 (preprint)
MOCK_ORCID_RESPONSE: dict[str, Any] = {
    "group": [
        {
            "work-summary": [
                {
                    "title": {"title": {"value": "Deep Learning for Resume Parsing"}},
                    "publication-date": {"year": {"value": "2023"}},
                    "journal-title": {"value": "Journal of NLP"},
                    "type": "journal-article",
                    "external-ids": {
                        "external-id": [
                            {
                                "external-id-type": "doi",
                                "external-id-value": "10.1234/test",
                                "external-id-url": {
                                    "value": "https://doi.org/10.1234/test"
                                },
                            }
                        ]
                    },
                }
            ]
        },
        {
            "work-summary": [
                {
                    "title": {"title": {"value": "LaTeX Compiler Optimization"}},
                    "publication-date": {"year": {"value": "2021"}},
                    "journal-title": {"value": "ICSE 2021"},
                    "type": "conference-paper",
                    "external-ids": {"external-id": []},
                }
            ]
        },
        {
            "work-summary": [
                {
                    "title": {"title": {"value": "Survey of ATS Systems"}},
                    "publication-date": {"year": {"value": "2020"}},
                    "journal-title": {"value": "arXiv"},
                    "type": "preprint",
                    "external-ids": {"external-id": []},
                }
            ]
        },
    ]
}

MOCK_ORCID_EMPTY: dict[str, Any] = {"group": []}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_200(json_data: Any) -> MagicMock:
    """Build a mock httpx.Response that returns status 200 + json_data."""
    mock = MagicMock(spec=Response)
    mock.status_code = 200
    mock.json.return_value = json_data
    mock.raise_for_status = MagicMock()
    return mock


def _make_404() -> MagicMock:
    """Build a mock httpx.Response for a 404 Not Found."""
    mock = MagicMock(spec=Response)
    mock.status_code = 404
    mock.raise_for_status = MagicMock()
    return mock


@contextmanager
def _patch_orcid(mock_resp: MagicMock):
    """
    Context manager that patches httpx.AsyncClient used by PublicationsService
    and forces a cache miss so Redis state cannot pollute test results in CI.

    Usage::

        with _patch_orcid(_make_200(MOCK_ORCID_RESPONSE)):
            resp = await client.post("/ai/generate-publications", json={...})
    """
    with patch("app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None), \
         patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock), \
         patch("app.services.publications_service.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        yield mock_cls


@contextmanager
def _patch_orcid_error(exc: Exception):
    """Context manager that makes the ORCID GET raise exc, with cache bypassed."""
    with patch("app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None), \
         patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock), \
         patch("app.services.publications_service.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=exc)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        yield mock_cls


# ── Fixtures ───────────────────────────────────────────────────────────────────

# conftest already provides: client, auth_headers, expired_auth_headers, db_session
# Import _insert_session locally so auth tests can build their own sessions.
from conftest import _insert_session  # noqa: E402


@pytest.fixture
async def test_user(db_session: AsyncSession) -> dict[str, str]:
    """Create a minimal user row and return its id + email."""
    from sqlalchemy import text

    user_id = str(uuid.uuid4())
    email = f"test_{user_id.replace('-', '')}@example.com"
    await db_session.execute(
        text(
            "INSERT INTO users "
            "(id, email, name, email_verified, subscription_plan, "
            "subscription_status, trial_used) "
            "VALUES (:id, :email, 'Pub Test User', true, 'free', 'active', false) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": email},
    )
    await db_session.commit()
    return {"id": user_id, "email": email}


@pytest.fixture
async def pub_auth_headers(
    db_session: AsyncSession, test_user: dict[str, str]
) -> dict[str, str]:
    """Valid Bearer token for the test_user created above."""
    token = await _insert_session(db_session, test_user["id"])
    return {"Authorization": f"Bearer {token}"}


# ── Service unit tests ─────────────────────────────────────────────────────────


class TestPublicationsServiceUnit:
    """58U-xx — direct service tests, no HTTP, no database."""

    # 58U-01 ─────────────────────────────────────────────────────────────────
    async def test_fetch_from_orcid_returns_publications(self) -> None:
        """fetch_from_orcid with mocked httpx returns correctly parsed list."""
        svc = PublicationsService()
        with _patch_orcid(_make_200(MOCK_ORCID_RESPONSE)):
            pubs = await svc.fetch_from_orcid(VALID_ORCID)

        assert len(pubs) == 3
        titles = {p.title for p in pubs}
        assert "Deep Learning for Resume Parsing" in titles
        assert "LaTeX Compiler Optimization" in titles
        assert "Survey of ATS Systems" in titles

        doi_pub = next(p for p in pubs if p.title == "Deep Learning for Resume Parsing")
        assert doi_pub.doi == "10.1234/test"
        assert doi_pub.year == 2023
        assert doi_pub.pub_type == "journal"
        assert doi_pub.venue == "Journal of NLP"

    # 58U-02 ─────────────────────────────────────────────────────────────────
    async def test_fetch_from_orcid_404_raises_value_error(self) -> None:
        """fetch_from_orcid with 404 raises ValueError containing 'not found'."""
        svc = PublicationsService()
        with _patch_orcid(_make_404()):
            with pytest.raises(ValueError, match="not found"):
                await svc.fetch_from_orcid(VALID_ORCID)

    # 58U-03 ─────────────────────────────────────────────────────────────────
    def test_format_as_latex_empty_list(self) -> None:
        """format_as_latex on empty list returns empty string."""
        assert PublicationsService().format_as_latex([]) == ""

    # 58U-04 ─────────────────────────────────────────────────────────────────
    def test_format_as_latex_contains_section(self) -> None:
        r"""format_as_latex produces \section{Publications}."""
        pubs = [Publication("X", [], "Y", 2020, None, None, "journal")]
        result = PublicationsService().format_as_latex(pubs)
        assert r"\section{Publications}" in result

    # 58U-05 ─────────────────────────────────────────────────────────────────
    def test_format_as_latex_contains_enumerate(self) -> None:
        r"""format_as_latex produces \begin{enumerate} and \end{enumerate}."""
        pubs = [
            Publication("Test Paper", ["A. Author"], "Journal", 2022, None, None, "journal")
        ]
        result = PublicationsService().format_as_latex(pubs)
        assert r"\begin{enumerate}" in result
        assert r"\end{enumerate}" in result

    # 58U-06 ─────────────────────────────────────────────────────────────────
    def test_format_as_latex_sorted_year_descending(self) -> None:
        """format_as_latex sorts publications newest-first."""
        pubs = [
            Publication("Old Paper", [], "Venue", 2015, None, None, "journal"),
            Publication("New Paper", [], "Venue", 2023, None, None, "journal"),
        ]
        result = PublicationsService().format_as_latex(pubs)
        assert result.find("New Paper") < result.find("Old Paper"), (
            "Newest publication should appear before older one"
        )

    # 58U-07 ─────────────────────────────────────────────────────────────────
    def test_map_work_type_journal(self) -> None:
        assert PublicationsService._map_work_type("journal-article") == "journal"

    # 58U-08 ─────────────────────────────────────────────────────────────────
    def test_map_work_type_conference(self) -> None:
        assert PublicationsService._map_work_type("conference-paper") == "conference"

    # 58U-09 ─────────────────────────────────────────────────────────────────
    def test_map_work_type_preprint(self) -> None:
        assert PublicationsService._map_work_type("preprint") == "preprint"

    # 58U-10 ─────────────────────────────────────────────────────────────────
    def test_map_work_type_book_chapter(self) -> None:
        assert PublicationsService._map_work_type("book-chapter") == "book_chapter"

    # 58U-11 ─────────────────────────────────────────────────────────────────
    def test_format_entry_doi_produces_href(self) -> None:
        r"""DOI produces \href{https://doi.org/...} in the formatted entry."""
        pub = Publication("DOI Paper", [], "Journal", 2023, "10.99/test", None, "journal")
        result = PublicationsService().format_as_latex([pub])
        assert r"\href{https://doi.org/10.99/test}" in result

    # 58U-12 ─────────────────────────────────────────────────────────────────
    def test_format_entry_missing_venue_no_textit(self) -> None:
        r"""Missing venue does not produce a \textit{} in the formatted entry."""
        pub = Publication("No Venue Paper", [], "", 2023, None, None, "journal")
        result = PublicationsService().format_as_latex([pub])
        assert r"\textit{}" not in result


# ── HTTP integration tests ─────────────────────────────────────────────────────


class TestPublicationsEndpoint:
    """58I-xx — full HTTP round-trips via ASGI TestClient."""

    # 58I-01 ─────────────────────────────────────────────────────────────────
    async def test_valid_orcid_returns_200_with_all_fields(
        self, client: AsyncClient
    ) -> None:
        """Valid ORCID → 200 with publications, latex_section, cached fields."""
        with _patch_orcid(_make_200(MOCK_ORCID_RESPONSE)):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "publications" in body
        assert "latex_section" in body
        assert "cached" in body
        assert isinstance(body["publications"], list)
        assert len(body["publications"]) == 3
        assert isinstance(body["cached"], bool)

    # 58I-02 ─────────────────────────────────────────────────────────────────
    async def test_invalid_orcid_short_returns_422(
        self, client: AsyncClient
    ) -> None:
        """ORCID with only 3 groups → 422 validation error."""
        resp = await client.post(
            "/ai/generate-publications",
            json={"identifier": INVALID_ORCID_SHORT},
        )
        assert resp.status_code == 422

    # 58I-03 ─────────────────────────────────────────────────────────────────
    async def test_invalid_orcid_letters_returns_422(
        self, client: AsyncClient
    ) -> None:
        """ORCID with non-digit characters in first group → 422."""
        resp = await client.post(
            "/ai/generate-publications",
            json={"identifier": INVALID_ORCID_LETTERS},
        )
        assert resp.status_code == 422

    # 58I-04 ─────────────────────────────────────────────────────────────────
    async def test_orcid_not_found_returns_422_not_404(
        self, client: AsyncClient
    ) -> None:
        """ORCID 404 from upstream → 422 (not 404, not 500)."""
        with _patch_orcid(_make_404()):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID},
            )

        assert resp.status_code == 422
        assert "not found" in resp.json()["detail"].lower()

    # 58I-05 ─────────────────────────────────────────────────────────────────
    async def test_orcid_network_error_returns_502(
        self, client: AsyncClient
    ) -> None:
        """ORCID API unreachable → 502 Bad Gateway."""
        with _patch_orcid_error(Exception("Connection refused")):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID},
            )

        assert resp.status_code == 502

    # 58I-06 ─────────────────────────────────────────────────────────────────
    async def test_year_from_filter_removes_older_publications(
        self, client: AsyncClient
    ) -> None:
        """year_from=2022 keeps only the 2023 paper, drops 2021 and 2020."""
        with _patch_orcid(_make_200(MOCK_ORCID_RESPONSE)):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID, "year_from": 2022},
            )

        assert resp.status_code == 200
        pubs = resp.json()["publications"]
        assert len(pubs) == 1
        assert pubs[0]["year"] == 2023
        assert all((p["year"] or 0) >= 2022 for p in pubs)

    # 58I-07 ─────────────────────────────────────────────────────────────────
    async def test_year_to_filter_removes_newer_publications(
        self, client: AsyncClient
    ) -> None:
        """year_to=2021 keeps 2021 and 2020, drops the 2023 paper."""
        with _patch_orcid(_make_200(MOCK_ORCID_RESPONSE)):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID, "year_to": 2021},
            )

        assert resp.status_code == 200
        pubs = resp.json()["publications"]
        assert len(pubs) == 2
        assert all((p["year"] or 9999) <= 2021 for p in pubs)

    # 58I-08 ─────────────────────────────────────────────────────────────────
    async def test_pub_types_conference_filter(
        self, client: AsyncClient
    ) -> None:
        """pub_types=['conference'] returns only the conference entry."""
        with _patch_orcid(_make_200(MOCK_ORCID_RESPONSE)):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID, "pub_types": ["conference"]},
            )

        assert resp.status_code == 200
        pubs = resp.json()["publications"]
        assert len(pubs) == 1
        assert pubs[0]["pub_type"] == "conference"
        assert all(p["pub_type"] == "conference" for p in pubs)

    # 58I-09 ─────────────────────────────────────────────────────────────────
    async def test_latex_section_contains_enumerate_and_section(
        self, client: AsyncClient
    ) -> None:
        r"""Response latex_section contains \begin{enumerate} and \section{Publications}."""
        with _patch_orcid(_make_200(MOCK_ORCID_RESPONSE)):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID},
            )

        assert resp.status_code == 200
        latex = resp.json()["latex_section"]
        assert r"\begin{enumerate}" in latex
        assert r"\section{Publications}" in latex

    # 58I-10 ─────────────────────────────────────────────────────────────────
    async def test_cache_hit_returns_cached_true(
        self, client: AsyncClient
    ) -> None:
        """When cache_manager.get returns a payload, response has cached=True."""
        cached_payload = {
            "publications": [],
            "latex_section": r"\section{Publications}\begin{enumerate}\end{enumerate}",
        }
        with patch(
            "app.api.ai_routes.cache_manager.get",
            new_callable=AsyncMock,
            return_value=cached_payload,
        ):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["cached"] is True
        assert body["latex_section"] == cached_payload["latex_section"]
        assert body["publications"] == []

    # 58I-11 ─────────────────────────────────────────────────────────────────
    async def test_empty_orcid_works_list_returns_200_empty(
        self, client: AsyncClient
    ) -> None:
        """ORCID profile with no works → 200, publications=[], latex_section=''."""
        with _patch_orcid(_make_200(MOCK_ORCID_EMPTY)):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["publications"] == []
        assert body["latex_section"] == ""

    # 58I-12 ─────────────────────────────────────────────────────────────────
    async def test_source_scholar_returns_422(
        self, client: AsyncClient
    ) -> None:
        """source='scholar' violates the '^orcid$' pattern constraint → 422."""
        resp = await client.post(
            "/ai/generate-publications",
            json={"identifier": VALID_ORCID, "source": "scholar"},
        )
        assert resp.status_code == 422

    # ── Publication field integrity ────────────────────────────────────────

    async def test_publication_fields_in_response(
        self, client: AsyncClient
    ) -> None:
        """Each publication in the response carries all required fields."""
        with _patch_orcid(_make_200(MOCK_ORCID_RESPONSE)):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID},
            )

        assert resp.status_code == 200
        for pub in resp.json()["publications"]:
            assert "title" in pub
            assert "authors" in pub
            assert "venue" in pub
            assert "year" in pub
            assert "doi" in pub
            assert "url" in pub
            assert "pub_type" in pub

    async def test_doi_pub_has_correct_doi_value(
        self, client: AsyncClient
    ) -> None:
        """The journal entry in the mock has DOI 10.1234/test."""
        with _patch_orcid(_make_200(MOCK_ORCID_RESPONSE)):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID},
            )

        assert resp.status_code == 200
        journal_pubs = [
            p for p in resp.json()["publications"] if p["pub_type"] == "journal"
        ]
        assert len(journal_pubs) == 1
        assert journal_pubs[0]["doi"] == "10.1234/test"

    async def test_combined_year_and_type_filter(
        self, client: AsyncClient
    ) -> None:
        """Combining year_from and pub_types keeps only matching entries."""
        with _patch_orcid(_make_200(MOCK_ORCID_RESPONSE)):
            resp = await client.post(
                "/ai/generate-publications",
                json={
                    "identifier": VALID_ORCID,
                    "year_from": 2020,
                    "year_to": 2022,
                    "pub_types": ["conference", "preprint"],
                },
            )

        assert resp.status_code == 200
        pubs = resp.json()["publications"]
        # 2023 journal excluded by year_from+type; 2021 conference and 2020 preprint remain
        assert len(pubs) == 2
        for pub in pubs:
            assert pub["pub_type"] in ("conference", "preprint")
            assert 2020 <= (pub["year"] or 0) <= 2022


# ── Authentication tests ───────────────────────────────────────────────────────


class TestPublicationsAuth:
    """
    58A-xx — verify that /ai/generate-publications uses get_current_user_optional
    and therefore never blocks unauthenticated or malformed requests.
    """

    # 58A-01 ─────────────────────────────────────────────────────────────────
    async def test_unauthenticated_no_token_returns_200(
        self, client: AsyncClient
    ) -> None:
        """No Authorization header → endpoint still returns 200."""
        with _patch_orcid(_make_200(MOCK_ORCID_RESPONSE)):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID},
                # no headers — anonymous request
            )
        assert resp.status_code == 200

    # 58A-02 ─────────────────────────────────────────────────────────────────
    async def test_invalid_bearer_token_returns_200(
        self, client: AsyncClient
    ) -> None:
        """A syntactically valid but unknown Bearer token → 200, not 401."""
        bogus_headers = {"Authorization": "Bearer totally-made-up-token-xyz"}
        with _patch_orcid(_make_200(MOCK_ORCID_RESPONSE)):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID},
                headers=bogus_headers,
            )
        assert resp.status_code == 200

    # 58A-03 ─────────────────────────────────────────────────────────────────
    async def test_expired_token_returns_200(
        self, client: AsyncClient, expired_auth_headers: dict
    ) -> None:
        """Expired session token → 200 (optional auth ignores expiry failures)."""
        with _patch_orcid(_make_200(MOCK_ORCID_RESPONSE)):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID},
                headers=expired_auth_headers,
            )
        assert resp.status_code == 200

    # 58A-04 ─────────────────────────────────────────────────────────────────
    async def test_authenticated_request_returns_200(
        self, client: AsyncClient, pub_auth_headers: dict
    ) -> None:
        """Valid authenticated request succeeds as expected."""
        with _patch_orcid(_make_200(MOCK_ORCID_RESPONSE)):
            resp = await client.post(
                "/ai/generate-publications",
                json={"identifier": VALID_ORCID},
                headers=pub_auth_headers,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["publications"]) == 3
