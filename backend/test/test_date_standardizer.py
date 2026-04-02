"""Tests for Feature 57: Smart Date Formatting Standardizer."""
import pytest
from httpx import AsyncClient

# ── Endpoint integration tests ─────────────────────────────────────────────

@pytest.mark.asyncio
class TestDateStandardizerEndpoint:

    async def test_full_month_to_abbr(self, client: AsyncClient):
        """'January 2020' with MMM YYYY → 'Jan 2020'."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={
                "latex_content": r"\textbf{January 2020 -- March 2021}",
                "target_format": "MMM YYYY",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "Jan 2020" in data["standardized_latex"]
        assert "Mar 2021" in data["standardized_latex"]
        assert len(data["occurrences"]) >= 2
        # Original listed in occurrences
        originals = [o["original"] for o in data["occurrences"]]
        assert "January 2020" in originals

    async def test_abbr_to_full_month(self, client: AsyncClient):
        """'Jan 2020' with MMMM YYYY → 'January 2020'."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={
                "latex_content": r"Jan 2020",
                "target_format": "MMMM YYYY",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "January 2020" in data["standardized_latex"]

    async def test_slash_format_to_abbr(self, client: AsyncClient):
        """'01/2020' with MMM YYYY → 'Jan 2020'."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={
                "latex_content": r"01/2020",
                "target_format": "MMM YYYY",
            },
        )
        assert resp.status_code == 200
        assert "Jan 2020" in resp.json()["standardized_latex"]

    async def test_iso_to_full_month(self, client: AsyncClient):
        """'2020-01' with MMMM YYYY → 'January 2020'."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={
                "latex_content": r"2020-01",
                "target_format": "MMMM YYYY",
            },
        )
        assert resp.status_code == 200
        assert "January 2020" in resp.json()["standardized_latex"]

    async def test_no_dates_returns_empty_occurrences(self, client: AsyncClient):
        """Content with no dates → occurrences=[], standardized_latex unchanged."""
        content = r"\textbf{No dates here, just plain text.}"
        resp = await client.post(
            "/ai/standardize-dates",
            json={"latex_content": content, "target_format": "MMM YYYY"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["occurrences"] == []
        assert data["standardized_latex"] == content

    async def test_already_target_format_no_change(self, client: AsyncClient):
        """Dates already in target format → not listed as occurrences."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={
                "latex_content": r"Jan 2020",
                "target_format": "MMM YYYY",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Jan 2020 is already in MMM YYYY — no change
        assert data["occurrences"] == []

    async def test_invalid_target_format_returns_422(self, client: AsyncClient):
        """Unrecognised target_format → 422 validation error."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={
                "latex_content": r"January 2020",
                "target_format": "INVALID",
            },
        )
        assert resp.status_code == 422

    async def test_occurrence_line_numbers(self, client: AsyncClient):
        """Line numbers in occurrences match the line where the date appears."""
        content = "line one\nJanuary 2020 on line two\nline three"
        resp = await client.post(
            "/ai/standardize-dates",
            json={"latex_content": content, "target_format": "MMM YYYY"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["occurrences"][0]["line"] == 2
