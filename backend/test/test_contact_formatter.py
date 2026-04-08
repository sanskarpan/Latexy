"""Tests for Feature 64: Contact Info Formatter."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestContactFormatterEndpoint:

    async def test_linkedin_url_normalized(self, client: AsyncClient):
        """https://www.linkedin.com/in/john-doe/ → linkedin.com/in/john-doe."""
        resp = await client.post(
            "/ai/format-contacts",
            json={"latex_content": r"Visit https://www.linkedin.com/in/john-doe/ for profile."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "linkedin.com/in/john-doe" in data["formatted_latex"]
        linkedin_change = next((c for c in data["changes"] if c["type"] == "linkedin"), None)
        assert linkedin_change is not None
        assert linkedin_change["normalized"] == "linkedin.com/in/john-doe"

    async def test_email_lowercased(self, client: AsyncClient):
        """john@EXAMPLE.COM → john@example.com."""
        resp = await client.post(
            "/ai/format-contacts",
            json={"latex_content": r"Contact: john@EXAMPLE.COM"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "john@example.com" in data["formatted_latex"]
        assert any(c["type"] == "email" for c in data["changes"])

    async def test_github_url_normalized(self, client: AsyncClient):
        """https://github.com/johndoe → github.com/johndoe."""
        resp = await client.post(
            "/ai/format-contacts",
            json={"latex_content": r"Code at https://github.com/johndoe"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "github.com/johndoe" in data["formatted_latex"]
        assert any(c["type"] == "github" for c in data["changes"])

    async def test_no_changes_returns_empty(self, client: AsyncClient):
        """Content with no contact info produces no changes."""
        resp = await client.post(
            "/ai/format-contacts",
            json={"latex_content": r"\textbf{No contact info here.}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["changes"] == []

    async def test_already_normalized_linkedin_no_change(self, client: AsyncClient):
        """Already-normalized linkedin URL produces no change."""
        resp = await client.post(
            "/ai/format-contacts",
            json={"latex_content": r"linkedin.com/in/john-doe"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["changes"] == []

    async def test_already_lowercase_email_no_change(self, client: AsyncClient):
        """Lowercase email produces no change."""
        resp = await client.post(
            "/ai/format-contacts",
            json={"latex_content": r"john@example.com"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert not any(c["type"] == "email" for c in data["changes"])

    async def test_change_includes_line_number(self, client: AsyncClient):
        """Each change includes the correct 1-based line number."""
        content = "line one\njohn@UPPER.COM\nline three"
        resp = await client.post(
            "/ai/format-contacts",
            json={"latex_content": content},
        )
        assert resp.status_code == 200
        email_change = next(
            (c for c in resp.json()["changes"] if c["type"] == "email"), None
        )
        assert email_change is not None
        assert email_change["line"] == 2
