"""Tests for URL project import (Feature 1 Phase 2 — external sources to resume).

All network + LLM calls are mocked (injected fake ``client`` / monkeypatched
service functions) — nothing here touches the network or a real LLM provider.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import url_projects_service as url_import
from app.services.job_scraper_service import SSRFError

# ── Fakes ────────────────────────────────────────────────────────────────────


class _FakeResp:
    def __init__(
        self,
        status_code: int,
        body: str | bytes,
        *,
        content_type: str | None = "text/html; charset=utf-8",
        content_length: int | None = None,
        chunks: list[bytes] | None = None,
    ):
        self.status_code = status_code
        self.headers = {}
        if content_type is not None:
            self.headers["content-type"] = content_type
        if content_length is not None:
            self.headers["content-length"] = str(content_length)
        self.charset_encoding = "utf-8"
        self._chunks = chunks or [body.encode() if isinstance(body, str) else body]
        self.iterated_chunks = 0
        self.exited = False

    async def aiter_bytes(self):
        for chunk in self._chunks:
            self.iterated_chunks += 1
            yield chunk


class _FakeStream:
    def __init__(self, resp: _FakeResp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, exc_type, exc, traceback):
        self._resp.exited = True


class _FakeAsyncClient:
    """Minimal stand-in for a streaming httpx client with a canned response."""

    def __init__(self, resp: _FakeResp):
        self._resp = resp
        self.closed = False

    def stream(self, method, url, headers=None):
        return _FakeStream(self._resp)

    async def aclose(self):
        self.closed = True


def _fake_llm(content: str):
    """A fake OpenAI client whose chat completion returns ``content``."""
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: resp)
        )
    )


def _raising_llm(exc: Exception):
    def _create(**kw):
        raise exc

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
    )


# ── fetch_url_text (SSRF + clean text) ───────────────────────────────────────


class TestFetchUrlText:
    async def test_rejects_private_url(self):
        """A loopback/private host is refused before any fetch happens."""
        with pytest.raises(SSRFError):
            await url_import.fetch_url_text("http://localhost/projects")

    async def test_rejects_non_http_scheme(self):
        with pytest.raises(SSRFError):
            await url_import.fetch_url_text("ftp://example.com/x")

    async def test_returns_clean_text(self, monkeypatch):
        """HTML body is converted to structured plain text."""
        # Skip real DNS/SSRF resolution for the public test URL.
        monkeypatch.setattr(url_import, "_assert_public_url", lambda url: None)
        html = "<html><body><h1>My Work</h1><p>I build things.</p></body></html>"
        client = _FakeAsyncClient(_FakeResp(200, html))
        text = await url_import.fetch_url_text("https://example.com", client=client)
        assert "My Work" in text
        assert "I build things." in text
        assert "<h1>" not in text  # tags stripped

    async def test_raises_valueerror_on_non_200(self, monkeypatch):
        monkeypatch.setattr(url_import, "_assert_public_url", lambda url: None)
        client = _FakeAsyncClient(_FakeResp(404, "nope"))
        with pytest.raises(ValueError):
            await url_import.fetch_url_text("https://example.com", client=client)

    async def test_accepts_parameterized_text_content_type(self, monkeypatch):
        monkeypatch.setattr(url_import, "_assert_public_url", lambda url: None)
        resp = _FakeResp(
            200,
            "<h1>Café Projects</h1>",
            content_type="Text/HTML; Charset=UTF-8",
        )
        text = await url_import.fetch_url_text(
            "https://example.com", client=_FakeAsyncClient(resp)
        )
        assert "Café Projects" in text

    @pytest.mark.parametrize(
        "content_type",
        [None, "application/octet-stream", "application/pdf", "image/png"],
    )
    async def test_rejects_missing_or_unsupported_content_type(
        self, monkeypatch, content_type
    ):
        monkeypatch.setattr(url_import, "_assert_public_url", lambda url: None)
        resp = _FakeResp(200, b"binary", content_type=content_type)
        with pytest.raises(ValueError, match="Content-Type"):
            await url_import.fetch_url_text(
                "https://example.com", client=_FakeAsyncClient(resp)
            )
        assert resp.iterated_chunks == 0
        assert resp.exited is True

    async def test_rejects_declared_oversized_response_before_reading(
        self, monkeypatch
    ):
        monkeypatch.setattr(url_import, "_assert_public_url", lambda url: None)
        resp = _FakeResp(
            200,
            "small body",
            content_length=url_import._MAX_RESPONSE_BYTES + 1,
        )
        with pytest.raises(ValueError, match="exceeds"):
            await url_import.fetch_url_text(
                "https://example.com", client=_FakeAsyncClient(resp)
            )
        assert resp.iterated_chunks == 0

    async def test_rejects_stream_that_crosses_response_limit(self, monkeypatch):
        monkeypatch.setattr(url_import, "_assert_public_url", lambda url: None)
        resp = _FakeResp(
            200,
            b"",
            chunks=[b"a" * url_import._MAX_RESPONSE_BYTES, b"b"],
        )
        with pytest.raises(ValueError, match="exceeds"):
            await url_import.fetch_url_text(
                "https://example.com", client=_FakeAsyncClient(resp)
            )
        assert resp.iterated_chunks == 2
        assert resp.exited is True

    async def test_closes_owned_client_but_not_injected_client(
        self, monkeypatch
    ):
        monkeypatch.setattr(url_import, "_assert_public_url", lambda url: None)
        injected_resp = _FakeResp(200, "<p>injected</p>")
        injected = _FakeAsyncClient(injected_resp)
        await url_import.fetch_url_text("https://example.com", client=injected)
        assert injected.closed is False
        assert injected_resp.exited is True

        owned_resp = _FakeResp(200, "<p>owned</p>")
        owned = _FakeAsyncClient(owned_resp)
        monkeypatch.setattr(url_import.httpx, "AsyncClient", lambda **kwargs: owned)
        await url_import.fetch_url_text("https://example.com")
        assert owned.closed is True
        assert owned_resp.exited is True


# ── extract_projects (LLM → ProjectEvidence) ─────────────────────────────────

_MULTI_JSON = """[
  {"title": "Latexy", "description": "A resume compiler.",
   "tech": ["Python", "FastAPI"],
   "suggested_bullets": ["Built a LaTeX compilation pipeline"],
   "url": "https://latexy.dev"},
  {"title": "Orbit", "description": "A scheduling tool.",
   "tech": ["TypeScript"],
   "suggested_bullets": ["Shipped a calendar sync engine"],
   "url": ""}
]"""


class TestExtractProjects:
    def test_parses_multiple_projects(self):
        client = _fake_llm(_MULTI_JSON)
        out = url_import.extract_projects(
            "portfolio page text", "https://me.example.com", "sk-test", client=client
        )
        assert len(out) == 2
        assert out[0]["title"] == "Latexy"
        assert out[0]["url"] == "https://latexy.dev"
        # Empty project url falls back to the source URL.
        assert out[1]["url"] == "https://me.example.com"

    def test_evidence_shape(self):
        client = _fake_llm(_MULTI_JSON)
        ev = url_import.extract_projects(
            "text", "https://me.example.com", "sk-test", client=client
        )[0]
        assert set(ev.keys()) == {
            "source", "title", "description", "tech", "metrics",
            "dates", "url", "suggested_bullets", "raw_excerpt",
        }
        assert ev["source"] == "url"
        assert ev["metrics"] == {"stars": 0, "forks": 0}
        assert ev["dates"] == {"last_active": None}
        assert ev["tech"] == ["Python", "FastAPI"]
        assert ev["raw_excerpt"] == ""

    def test_respects_five_project_cap(self):
        many = "[" + ",".join(
            f'{{"title": "P{i}", "description": "d{i}", "tech": [], '
            f'"suggested_bullets": [], "url": ""}}'
            for i in range(8)
        ) + "]"
        out = url_import.extract_projects(
            "text", "https://me.example.com", "sk-test", client=_fake_llm(many)
        )
        assert len(out) == 5

    def test_degrades_to_metadata_on_llm_error(self):
        """A raising LLM degrades to one metadata-only project from the title."""
        client = _raising_llm(RuntimeError("boom"))
        out = url_import.extract_projects(
            "My Cool Portfolio\nSome intro text.",
            "https://me.example.com",
            "sk-test",
            client=client,
        )
        assert len(out) == 1
        assert out[0]["title"] == "My Cool Portfolio"
        assert out[0]["source"] == "url"
        assert out[0]["url"] == "https://me.example.com"

    def test_degrades_on_unparseable_output(self):
        client = _fake_llm("I could not find any projects, sorry!")
        out = url_import.extract_projects(
            "Jane Doe Portfolio\nbio", "https://me.example.com", "sk-test", client=client
        )
        assert len(out) == 1
        assert out[0]["title"] == "Jane Doe Portfolio"

    def test_platform_key_used_when_byok_missing(self, monkeypatch):
        monkeypatch.setattr(url_import.settings, "OPENAI_API_KEY", "sk-platform")
        client = _fake_llm(_MULTI_JSON)
        with patch("openai.OpenAI", return_value=client) as openai_client:
            out = url_import.extract_projects(
                "portfolio page text", "https://me.example.com", None
            )

        openai_client.assert_called_once_with(api_key="sk-platform")
        assert out[0]["title"] == "Latexy"

    def test_byok_key_takes_precedence_over_platform_key(self, monkeypatch):
        monkeypatch.setattr(url_import.settings, "OPENAI_API_KEY", "sk-platform")
        client = _fake_llm(_MULTI_JSON)
        with patch("openai.OpenAI", return_value=client) as openai_client:
            url_import.extract_projects(
                "portfolio page text", "https://me.example.com", "sk-user"
            )

        openai_client.assert_called_once_with(api_key="sk-user")

    def test_no_key_degrades_to_metadata(self, monkeypatch):
        monkeypatch.setattr(url_import.settings, "OPENAI_API_KEY", "")
        out = url_import.extract_projects(
            "Homepage Title\nwelcome", "https://me.example.com", None
        )
        assert len(out) == 1
        assert out[0]["title"] == "Homepage Title"

    def test_empty_page_returns_empty(self):
        assert url_import.extract_projects("   ", "https://me.example.com", "sk-test") == []


# ── Endpoint smoke tests (live ASGI app) ─────────────────────────────────────


class TestImportUrlEndpoint:
    async def test_requires_auth(self, client):
        resp = await client.post("/sources/import-url", json={"url": "https://example.com"})
        assert resp.status_code in (401, 403)

    async def test_200_with_mocked_service(self, client, auth_headers, monkeypatch):
        projects = [{
            "source": "url", "title": "Latexy", "description": "A compiler.",
            "tech": ["Python"], "metrics": {"stars": 0, "forks": 0},
            "dates": {"last_active": None}, "url": "https://latexy.dev",
            "suggested_bullets": ["Built X"], "raw_excerpt": "",
        }]

        async def _fake_fetch(url, *, client=None):
            return "portfolio page text"

        monkeypatch.setattr(url_import, "fetch_url_text", _fake_fetch)
        monkeypatch.setattr(
            url_import, "extract_projects", lambda *a, **k: projects
        )

        resp = await client.post(
            "/sources/import-url",
            json={"url": "https://me.example.com"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["projects"] == projects

    async def test_400_on_disallowed_url(self, client, auth_headers):
        """A private/internal host is rejected by the SSRF guard → 400."""
        resp = await client.post(
            "/sources/import-url",
            json={"url": "http://localhost/projects"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    async def test_422_on_non_http_url(self, client, auth_headers):
        resp = await client.post(
            "/sources/import-url",
            json={"url": "ftp://example.com/x"},
            headers=auth_headers,
        )
        assert resp.status_code == 422
