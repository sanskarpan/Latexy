"""
Tests for the BibTeX Smart Import feature (Feature 14).

Covers:
  - ReferenceService.detect_type / normalize_identifier
  - ReferenceService._parse_arxiv_xml (via mock httpx)
  - POST /references/fetch endpoint
  - POST /references/detect endpoint
  - Caching behaviour (second call uses cached result — no second httpx call)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# ── Helpers ────────────────────────────────────────────────────────────────────

# Minimal Crossref BibTeX response for a known DOI
_SAMPLE_DOI_BIBTEX = """\
@article{Vaswani_2017,
  title = {{Attention Is All You Need}},
  author = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki},
  year = {2017},
  journal = {Advances in Neural Information Processing Systems},
  volume = {30},
}
"""

# Minimal arXiv Atom XML for 1706.03762
_SAMPLE_ARXIV_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v5</id>
    <title>Attention Is All You Need</title>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <author><name>Niki Parmar</name></author>
    <published>2017-06-12T17:00:00Z</published>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
"""

# arXiv error XML (invalid ID)
_ARXIV_ERROR_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/9999.99999</id>
    <title>Error</title>
  </entry>
</feed>
"""


def _mock_httpx_response(status_code: int, text: str):
    """Build a mock httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


# ── Service unit tests ─────────────────────────────────────────────────────────


class TestReferenceServiceDetect:
    """detect_type / normalize_identifier."""

    def _svc(self):
        from app.services.reference_service import reference_service
        return reference_service

    def test_detect_bare_doi(self):
        assert self._svc().detect_type("10.1145/1327452.1327492") == "doi"

    def test_detect_doi_url(self):
        assert self._svc().detect_type("https://doi.org/10.1145/1327452.1327492") == "doi"

    def test_detect_arxiv_new(self):
        assert self._svc().detect_type("1706.03762") == "arxiv"

    def test_detect_arxiv_with_version(self):
        assert self._svc().detect_type("1706.03762v5") == "arxiv"

    def test_detect_arxiv_url(self):
        assert self._svc().detect_type("https://arxiv.org/abs/1706.03762") == "arxiv"

    def test_detect_unknown(self):
        assert self._svc().detect_type("not-an-id") is None

    def test_normalize_strips_doi_url(self):
        norm, typ = self._svc().normalize_identifier("https://doi.org/10.1145/1327452.1327492")
        assert norm == "10.1145/1327452.1327492"
        assert typ == "doi"

    def test_normalize_strips_arxiv_version(self):
        norm, typ = self._svc().normalize_identifier("1706.03762v5")
        assert norm == "1706.03762"
        assert typ == "arxiv"

    def test_normalize_arxiv_url(self):
        norm, typ = self._svc().normalize_identifier("https://arxiv.org/abs/1706.03762v3")
        assert norm == "1706.03762"
        assert typ == "arxiv"


class TestArxivXmlParser:
    """_parse_arxiv_xml (pure, no network)."""

    def _svc(self):
        from app.services.reference_service import reference_service
        return reference_service

    def test_parse_valid_xml(self):
        bibtex, meta = self._svc()._parse_arxiv_xml(_SAMPLE_ARXIV_XML, "1706.03762")
        assert "@misc" in bibtex
        assert "Attention Is All You Need" in bibtex
        assert meta["year"] == 2017
        assert "Vaswani" in meta["authors"]

    def test_parse_includes_eprint(self):
        bibtex, _ = self._svc()._parse_arxiv_xml(_SAMPLE_ARXIV_XML, "1706.03762")
        assert "eprint" in bibtex
        assert "1706.03762" in bibtex

    def test_parse_includes_archiveprefix(self):
        bibtex, _ = self._svc()._parse_arxiv_xml(_SAMPLE_ARXIV_XML, "1706.03762")
        assert "archivePrefix" in bibtex
        assert "arXiv" in bibtex

    def test_parse_error_entry_raises(self):
        svc = self._svc()
        with pytest.raises(ValueError, match="not found"):
            svc._parse_arxiv_xml(_ARXIV_ERROR_XML, "9999.99999")


# ── Endpoint tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestFetchReferencesEndpoint:
    """POST /references/fetch"""

    async def test_valid_doi_returns_bibtex(self, client: AsyncClient):
        """Known DOI → returns entry with '@' BibTeX."""
        mock_resp = _mock_httpx_response(200, _SAMPLE_DOI_BIBTEX)
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_cm)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_cm.get = AsyncMock(return_value=mock_resp)

        with patch("app.services.reference_service.cache_manager.get", return_value=None), \
             patch("app.services.reference_service.cache_manager.set", return_value=None), \
             patch("app.services.reference_service.httpx.AsyncClient", return_value=mock_cm):
            resp = await client.post(
                "/references/fetch",
                json={"identifiers": ["10.1145/1327452.1327492"]},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["successful"] == 1
        entry = data["entries"][0]
        assert entry["bibtex"] is not None
        assert "@" in entry["bibtex"]
        assert entry["source_type"] == "doi"
        assert entry["error"] is None

    async def test_known_arxiv_returns_bibtex(self, client: AsyncClient):
        """arXiv ID 1706.03762 → returns BibTeX for 'Attention Is All You Need'."""
        mock_resp = _mock_httpx_response(200, _SAMPLE_ARXIV_XML)
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_cm)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_cm.get = AsyncMock(return_value=mock_resp)

        with patch("app.services.reference_service.cache_manager.get", return_value=None), \
             patch("app.services.reference_service.cache_manager.set", return_value=None), \
             patch("app.services.reference_service.httpx.AsyncClient", return_value=mock_cm):
            resp = await client.post(
                "/references/fetch",
                json={"identifiers": ["1706.03762"]},
            )

        assert resp.status_code == 200
        data = resp.json()
        entry = data["entries"][0]
        assert entry["bibtex"] is not None
        assert "Attention Is All You Need" in entry["bibtex"]
        assert entry["source_type"] == "arxiv"

    async def test_invalid_doi_returns_error_not_500(self, client: AsyncClient):
        """Invalid DOI → entry with error field, not a 500."""
        mock_resp = _mock_httpx_response(404, "Not Found")
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_cm)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_cm.get = AsyncMock(return_value=mock_resp)

        with patch("app.services.reference_service.cache_manager.get", return_value=None), \
             patch("app.services.reference_service.cache_manager.set", return_value=None), \
             patch("app.services.reference_service.httpx.AsyncClient", return_value=mock_cm):
            resp = await client.post(
                "/references/fetch",
                json={"identifiers": ["10.9999/does.not.exist"]},
            )

        assert resp.status_code == 200
        data = resp.json()
        entry = data["entries"][0]
        assert entry["bibtex"] is None
        assert entry["error"] is not None
        assert data["successful"] == 0

    async def test_invalid_arxiv_returns_error(self, client: AsyncClient):
        """Invalid arXiv ID → entry with error."""
        mock_resp = _mock_httpx_response(200, _ARXIV_ERROR_XML)
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_cm)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_cm.get = AsyncMock(return_value=mock_resp)

        with patch("app.services.reference_service.cache_manager.get", return_value=None), \
             patch("app.services.reference_service.cache_manager.set", return_value=None), \
             patch("app.services.reference_service.httpx.AsyncClient", return_value=mock_cm):
            resp = await client.post(
                "/references/fetch",
                json={"identifiers": ["9999.99999"]},
            )

        assert resp.status_code == 200
        entry = resp.json()["entries"][0]
        assert entry["bibtex"] is None
        assert entry["error"] is not None

    async def test_unknown_identifier_returns_error(self, client: AsyncClient):
        """Unrecognised string → error, source_type = 'unknown'."""
        resp = await client.post(
            "/references/fetch",
            json={"identifiers": ["not-a-doi-or-arxiv"]},
        )
        assert resp.status_code == 200
        entry = resp.json()["entries"][0]
        assert entry["source_type"] == "unknown"
        assert entry["error"] is not None

    async def test_batch_of_three(self, client: AsyncClient):
        """Batch with two valid + one invalid → 2 successful, 1 error."""
        doi_resp = _mock_httpx_response(200, _SAMPLE_DOI_BIBTEX)
        arxiv_resp = _mock_httpx_response(200, _SAMPLE_ARXIV_XML)
        doi_404 = _mock_httpx_response(404, "Not Found")

        call_count = {"n": 0}

        async def _mock_get(url, **_kwargs):
            n = call_count["n"]
            call_count["n"] += 1
            if n == 0:
                return doi_resp
            elif n == 1:
                return arxiv_resp
            else:
                return doi_404

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_cm)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_cm.get = _mock_get

        with patch("app.services.reference_service.cache_manager.get", return_value=None), \
             patch("app.services.reference_service.cache_manager.set", return_value=None), \
             patch("app.services.reference_service.httpx.AsyncClient", return_value=mock_cm):
            resp = await client.post(
                "/references/fetch",
                json={"identifiers": [
                    "10.1145/1327452.1327492",
                    "1706.03762",
                    "10.9999/bad",
                ]},
            )

        data = resp.json()
        assert data["total"] == 3
        assert data["successful"] == 2

    async def test_empty_identifiers_rejected(self, client: AsyncClient):
        """Empty list → 422."""
        resp = await client.post("/references/fetch", json={"identifiers": []})
        assert resp.status_code == 422

    async def test_too_many_identifiers_rejected(self, client: AsyncClient):
        """More than 20 identifiers → 422."""
        resp = await client.post(
            "/references/fetch",
            json={"identifiers": [f"1706.{str(i).zfill(5)}" for i in range(21)]},
        )
        assert resp.status_code == 422

    async def test_cache_hit_no_second_httpx_call(self, client: AsyncClient):
        """Second call for same DOI returns cached=True and makes no HTTP request."""
        cached_entry = {
            "bibtex": _SAMPLE_DOI_BIBTEX,
            "cite_key": "Vaswani_2017",
            "title": "Attention Is All You Need",
            "authors": "Vaswani, Ashish",
            "year": 2017,
            "cached": False,
        }

        get_call_count = {"n": 0}
        httpx_call_count = {"n": 0}

        async def _mock_cache_get(key):
            if get_call_count["n"] > 0:
                return {**cached_entry, "cached": True}
            get_call_count["n"] += 1
            return None

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_cm)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        async def _mock_httpx_get(*_a, **_kw):
            httpx_call_count["n"] += 1
            return _mock_httpx_response(200, _SAMPLE_DOI_BIBTEX)

        mock_cm.get = _mock_httpx_get

        with patch("app.services.reference_service.cache_manager.get", side_effect=_mock_cache_get), \
             patch("app.services.reference_service.cache_manager.set", return_value=None), \
             patch("app.services.reference_service.httpx.AsyncClient", return_value=mock_cm):
            # First call — cache miss, HTTP request made
            resp1 = await client.post(
                "/references/fetch",
                json={"identifiers": ["10.1145/1327452.1327492"]},
            )
            # Second call — cache hit, no HTTP request
            resp2 = await client.post(
                "/references/fetch",
                json={"identifiers": ["10.1145/1327452.1327492"]},
            )

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp2.json()["entries"][0]["cached"] is True
        assert httpx_call_count["n"] == 1  # second call used cache

    async def test_response_has_required_fields(self, client: AsyncClient):
        """Response schema includes entries, total, successful, processing_time."""
        resp = await client.post(
            "/references/fetch",
            json={"identifiers": ["not-an-id"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert "total" in data
        assert "successful" in data
        assert "processing_time" in data


@pytest.mark.asyncio
class TestDetectReferencesEndpoint:
    """POST /references/detect"""

    async def test_detects_bare_doi(self, client: AsyncClient):
        resp = await client.post(
            "/references/detect",
            json={"text": "See 10.1145/1327452.1327492 for details."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        doi_items = [d for d in data["detected"] if d["type"] == "doi"]
        assert doi_items

    async def test_detects_arxiv_id(self, client: AsyncClient):
        resp = await client.post(
            "/references/detect",
            json={"text": "Based on 1706.03762 (Transformer paper)."},
        )
        assert resp.status_code == 200
        data = resp.json()
        arxiv_items = [d for d in data["detected"] if d["type"] == "arxiv"]
        assert arxiv_items
        assert arxiv_items[0]["normalized"] == "1706.03762"

    async def test_detects_doi_url(self, client: AsyncClient):
        resp = await client.post(
            "/references/detect",
            json={"text": "Available at https://doi.org/10.1145/3386569.3392408"},
        )
        assert resp.status_code == 200
        data = resp.json()
        doi_items = [d for d in data["detected"] if d["type"] == "doi"]
        assert doi_items

    async def test_no_identifiers(self, client: AsyncClient):
        resp = await client.post(
            "/references/detect",
            json={"text": "No identifiers here, just plain text."},
        )
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
