"""
Tests for Feature 54: ORCID Publication List Auto-Generator.

Covers:
  - normalize_orcid: bare IDs, URLs, invalid formats
  - fetch-orcid endpoint: valid ID, not-found, invalid format, empty profile
  - Response schema: all required fields present, source_type="orcid"
  - BibTeX quality: entries have bibtex, cite_key, title, year
"""
from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


# ── Unit tests for normalize_orcid ────────────────────────────────────────

class TestNormalizeOrcid:
    def test_bare_id_accepted(self):
        from app.services.reference_service import reference_service
        assert reference_service.normalize_orcid("0000-0001-2345-6789") == "0000-0001-2345-6789"

    def test_orcid_url_stripped(self):
        from app.services.reference_service import reference_service
        result = reference_service.normalize_orcid("https://orcid.org/0000-0001-2345-6789")
        assert result == "0000-0001-2345-6789"

    def test_http_url_stripped(self):
        from app.services.reference_service import reference_service
        result = reference_service.normalize_orcid("http://orcid.org/0000-0002-1825-0097")
        assert result == "0000-0002-1825-0097"

    def test_x_checksum_accepted(self):
        from app.services.reference_service import reference_service
        # ORCID checksum digit can be X
        result = reference_service.normalize_orcid("0000-0003-4567-890X")
        assert result is not None

    def test_invalid_format_returns_none(self):
        from app.services.reference_service import reference_service
        assert reference_service.normalize_orcid("not-an-orcid") is None
        assert reference_service.normalize_orcid("1234-5678") is None
        assert reference_service.normalize_orcid("") is None

    def test_random_url_returns_none(self):
        from app.services.reference_service import reference_service
        assert reference_service.normalize_orcid("https://example.com/profile") is None


# ── Unit tests for _parse_orcid_response ─────────────────────────────────

class TestParseOrcidResponse:
    def _make_response(self, works: list[dict]) -> dict:
        """Build a minimal ORCID /works response from a list of work dicts."""
        groups = []
        for w in works:
            summary: dict = {
                "title": {"title": {"value": w.get("title", "Test Paper")}},
                "type": w.get("type", "journal-article"),
                "external-ids": {
                    "external-id": [
                        {"external-id-type": "doi", "external-id-value": w["doi"]}
                    ] if w.get("doi") else []
                },
                "url": {"value": w.get("url", "")},
            }
            if w.get("year"):
                summary["publication-date"] = {"year": {"value": str(w["year"])}}
            if w.get("journal"):
                summary["journal-title"] = {"value": w["journal"]}
            groups.append({"work-summary": [summary]})
        return {"group": groups}

    def test_extracts_title_and_year(self):
        from app.services.reference_service import reference_service
        data = self._make_response([{"title": "My Paper", "year": 2022, "doi": "10.1234/abc"}])
        result = reference_service._parse_orcid_response(data)
        assert len(result) == 1
        assert result[0]["title"] == "My Paper"
        assert result[0]["year"] == 2022
        assert result[0]["doi"] == "10.1234/abc"

    def test_sorts_by_year_descending(self):
        from app.services.reference_service import reference_service
        data = self._make_response([
            {"title": "Old Paper", "year": 2010},
            {"title": "New Paper", "year": 2023},
            {"title": "Mid Paper", "year": 2015},
        ])
        result = reference_service._parse_orcid_response(data)
        years = [w["year"] for w in result]
        assert years == [2023, 2015, 2010]

    def test_missing_year_handled(self):
        from app.services.reference_service import reference_service
        data = self._make_response([{"title": "No Date Paper"}])
        result = reference_service._parse_orcid_response(data)
        assert result[0]["year"] is None

    def test_no_doi_work_captured(self):
        from app.services.reference_service import reference_service
        data = self._make_response([{"title": "Conference Talk", "year": 2021, "type": "conference-paper"}])
        result = reference_service._parse_orcid_response(data)
        assert result[0]["doi"] is None
        assert result[0]["work_type"] == "conferencepaper"

    def test_empty_groups_returns_empty(self):
        from app.services.reference_service import reference_service
        assert reference_service._parse_orcid_response({"group": []}) == []


# ── Endpoint tests ────────────────────────────────────────────────────────

_SAMPLE_ORCID_RESPONSE = {
    "group": [
        {
            "work-summary": [{
                "title": {"title": {"value": "Deep Learning for LaTeX"}},
                "publication-date": {"year": {"value": "2023"}},
                "journal-title": {"value": "Nature Machine Intelligence"},
                "type": "journal-article",
                "external-ids": {
                    "external-id": [
                        {"external-id-type": "doi", "external-id-value": "10.1038/s42256-023-00001-1"}
                    ]
                },
                "url": {"value": "https://nature.com/articles/s42256-023-00001-1"},
            }]
        },
        {
            "work-summary": [{
                "title": {"title": {"value": "Automated Resume Analysis"}},
                "publication-date": {"year": {"value": "2021"}},
                "journal-title": {"value": "ACM SIGCHI"},
                "type": "conference-paper",
                "external-ids": {"external-id": []},
                "url": {"value": ""},
            }]
        },
    ]
}


@pytest.mark.asyncio
class TestFetchOrcidEndpoint:

    async def test_invalid_orcid_format_returns_422(self, client: AsyncClient):
        """Malformed ORCID ID must return 422."""
        resp = await client.post(
            "/references/fetch-orcid",
            json={"orcid_id": "not-an-orcid"},
        )
        assert resp.status_code == 422

    async def test_orcid_url_accepted(self, client: AsyncClient):
        """ORCID URL format must be accepted (normalized to bare ID)."""
        from app.api.reference_routes import BibTeXEntry as BibTeXEntryModel
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _SAMPLE_ORCID_RESPONSE

        crossref_entry = BibTeXEntryModel(
            identifier="10.1038/s42256-023-00001-1",
            bibtex="@article{test2023, title={{Deep Learning for LaTeX}}}",
            cite_key="test2023",
            title="Deep Learning for LaTeX",
            authors="Smith, J.",
            year=2023,
            source_type="doi",
            error=None,
            cached=False,
        )

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)

            with patch("app.api.reference_routes._fetch_one", new=AsyncMock(return_value=crossref_entry)):
                resp = await client.post(
                    "/references/fetch-orcid",
                    json={"orcid_id": "https://orcid.org/0000-0001-2345-6789"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    async def test_valid_response_schema(self, client: AsyncClient):
        """Response must have: entries, total, successful, processing_time."""
        from app.api.reference_routes import BibTeXEntry as BibTeXEntryModel
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _SAMPLE_ORCID_RESPONSE

        fallback_entry = BibTeXEntryModel(
            identifier="10.1038/s42256-023-00001-1",
            bibtex=None,
            cite_key="fallback2023",
            title="Deep Learning for LaTeX",
            authors=None,
            year=2023,
            source_type="doi",
            error="Not found",
            cached=False,
        )

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)

            with patch("app.api.reference_routes._fetch_one", new=AsyncMock(return_value=fallback_entry)):
                resp = await client.post(
                    "/references/fetch-orcid",
                    json={"orcid_id": "0000-0001-2345-6789"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert "total" in data
        assert "successful" in data
        assert "processing_time" in data
        assert isinstance(data["entries"], list)
        assert data["total"] == len(data["entries"])

    async def test_entries_have_required_fields(self, client: AsyncClient):
        """Each entry must have identifier, cite_key, source_type='orcid'."""
        from app.api.reference_routes import BibTeXEntry as BibTeXEntryModel
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _SAMPLE_ORCID_RESPONSE

        error_entry = BibTeXEntryModel(
            identifier="10.1038/s42256-023-00001-1",
            bibtex=None, cite_key="ref", title=None,
            authors=None, year=None, source_type="doi", error="fail", cached=False,
        )

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)

            with patch("app.api.reference_routes._fetch_one", new=AsyncMock(return_value=error_entry)):
                resp = await client.post(
                    "/references/fetch-orcid",
                    json={"orcid_id": "0000-0001-2345-6789"},
                )

        data = resp.json()
        for entry in data["entries"]:
            assert "identifier" in entry
            assert "cite_key" in entry
            assert entry.get("source_type") == "orcid"

    async def test_no_doi_work_gets_orcid_bibtex(self, client: AsyncClient):
        """Works without DOI must still get a minimal BibTeX entry."""
        no_doi_response = {
            "group": [{
                "work-summary": [{
                    "title": {"title": {"value": "Conference Talk"}},
                    "publication-date": {"year": {"value": "2022"}},
                    "journal-title": {"value": "ICML Proceedings"},
                    "type": "conference-paper",
                    "external-ids": {"external-id": []},
                    "url": {"value": ""},
                }]
            }]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = no_doi_response

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)

            resp = await client.post(
                "/references/fetch-orcid",
                json={"orcid_id": "0000-0001-2345-6789"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        entry = data["entries"][0]
        assert entry["bibtex"] is not None
        assert "Conference Talk" in entry["bibtex"]
        assert entry["year"] == 2022

    async def test_orcid_not_found_returns_404(self, client: AsyncClient):
        """Non-existent ORCID profile (HTTP 404 from ORCID) → 404."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)

            resp = await client.post(
                "/references/fetch-orcid",
                json={"orcid_id": "0000-0000-0000-0000"},
            )

        assert resp.status_code == 404

    async def test_empty_profile_returns_empty_entries(self, client: AsyncClient):
        """Profile with no publications → entries=[], total=0."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"group": []}

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)

            resp = await client.post(
                "/references/fetch-orcid",
                json={"orcid_id": "0000-0001-2345-6789"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["entries"] == []
        assert data["total"] == 0

    async def test_max_results_respected(self, client: AsyncClient):
        """max_results=1 must return at most 1 entry."""
        # Profile with 2 works
        two_works = {
            "group": [
                {"work-summary": [{"title": {"title": {"value": "Paper A"}},
                    "publication-date": {"year": {"value": "2022"}},
                    "type": "journal-article", "external-ids": {"external-id": []}, "url": {"value": ""}}]},
                {"work-summary": [{"title": {"title": {"value": "Paper B"}},
                    "publication-date": {"year": {"value": "2021"}},
                    "type": "journal-article", "external-ids": {"external-id": []}, "url": {"value": ""}}]},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = two_works

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = AsyncMock(return_value=mock_resp)

            resp = await client.post(
                "/references/fetch-orcid",
                json={"orcid_id": "0000-0001-2345-6789", "max_results": 1},
            )

        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_max_results_above_50_rejected(self, client: AsyncClient):
        """max_results > 50 must be rejected with 422."""
        resp = await client.post(
            "/references/fetch-orcid",
            json={"orcid_id": "0000-0001-2345-6789", "max_results": 51},
        )
        assert resp.status_code == 422
