"""Tests for Feature 53: Smart Date Formatting Standardizer."""
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

    async def test_year_first_slash_format(self, client: AsyncClient):
        """'2020/01' (YYYY/MM) with MMM YYYY → 'Jan 2020'."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={
                "latex_content": r"2020/01",
                "target_format": "MMM YYYY",
            },
        )
        assert resp.status_code == 200
        assert "Jan 2020" in resp.json()["standardized_latex"]

    async def test_year_first_slash_to_iso(self, client: AsyncClient):
        """'2020/06' with YYYY-MM → '2020-06'."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={
                "latex_content": r"Started 2020/06 at TechCorp",
                "target_format": "YYYY-MM",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "2020-06" in data["standardized_latex"]
        assert len(data["occurrences"]) == 1
        assert data["occurrences"][0]["original"] == "2020/06"

    async def test_may_abbreviation_detected(self, client: AsyncClient):
        """'May 2020' (May is its own abbreviation) → correctly standardized."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={
                "latex_content": r"May 2020 -- Jun 2021",
                "target_format": "MMMM YYYY",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "May 2020" in data["standardized_latex"]
        assert "June 2021" in data["standardized_latex"]
        # May is already in full-month form so it should NOT appear as an occurrence
        originals = [o["original"] for o in data["occurrences"]]
        assert "May 2020" not in originals
        assert "Jun 2021" in originals

    async def test_dotted_abbreviation(self, client: AsyncClient):
        """'Jan. 2020' (dotted abbreviation) → correctly parsed."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={
                "latex_content": r"Jan. 2020",
                "target_format": "MMMM YYYY",
            },
        )
        assert resp.status_code == 200
        assert "January 2020" in resp.json()["standardized_latex"]

    async def test_present_and_current_preserved(self, client: AsyncClient):
        """'Present', 'Current', 'Now' are not dates and must not be modified."""
        content = r"Jan 2020 -- Present \\ Jan 2019 -- Current"
        resp = await client.post(
            "/ai/standardize-dates",
            json={"latex_content": content, "target_format": "MMMM YYYY"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "Present" in data["standardized_latex"]
        assert "Current" in data["standardized_latex"]

    async def test_range_in_textbf(self, client: AsyncClient):
        """Date range inside \\textbf{} is standardized."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={
                "latex_content": r"\textbf{Jan 2018} -- \textbf{Mar 2020}",
                "target_format": "MMMM YYYY",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "January 2018" in data["standardized_latex"]
        assert "March 2020" in data["standardized_latex"]

    async def test_year_only_not_matched(self, client: AsyncClient):
        """Bare years like '2020' must not be detected as dates."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={
                "latex_content": r"Graduated in 2020 from MIT",
                "target_format": "MMM YYYY",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["occurrences"] == []
        assert "2020" in data["standardized_latex"]

    async def test_multiple_formats_in_same_doc(self, client: AsyncClient):
        """Mixed formats in one document all standardized to target."""
        content = (
            "January 2018 -- 2020-03\n"
            "01/2019 to June 2021\n"
            "2020/12 and Sep. 2022"
        )
        resp = await client.post(
            "/ai/standardize-dates",
            json={"latex_content": content, "target_format": "MMM YYYY"},
        )
        assert resp.status_code == 200
        data = resp.json()
        latex = data["standardized_latex"]
        assert "Jan 2018" in latex
        assert "Mar 2020" in latex
        assert "Jan 2019" in latex
        assert "Jun 2021" in latex
        assert "Dec 2020" in latex
        assert "Sep 2022" in latex

    async def test_mm_yyyy_output_format(self, client: AsyncClient):
        """MM/YYYY target_format produces numeric slash-separated output."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={
                "latex_content": r"March 2021",
                "target_format": "MM/YYYY",
            },
        )
        assert resp.status_code == 200
        assert "03/2021" in resp.json()["standardized_latex"]

    async def test_deduplication_same_date_same_line(self, client: AsyncClient):
        """If the same date appears twice on the same line, occurrences are deduplicated."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={
                "latex_content": r"Jan 2020 and Jan 2020",
                "target_format": "MMMM YYYY",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Both occurrences are replaced in the output
        assert data["standardized_latex"] == "January 2020 and January 2020"
        # But the occurrence list deduplicates by (line, original)
        assert len(data["occurrences"]) == 1

    async def test_invalid_month_number_ignored(self, client: AsyncClient):
        """'2020-13' has month=13, which is invalid — must be left unchanged."""
        content = r"2020-13"
        resp = await client.post(
            "/ai/standardize-dates",
            json={"latex_content": content, "target_format": "MMM YYYY"},
        )
        assert resp.status_code == 200
        # invalid month → _parse_month_year returns None → left unchanged
        assert resp.json()["standardized_latex"] == content
        assert resp.json()["occurrences"] == []

    async def test_content_too_long_returns_422(self, client: AsyncClient):
        """latex_content exceeding max_length=200_000 must return 422."""
        resp = await client.post(
            "/ai/standardize-dates",
            json={"latex_content": "x" * 200_001, "target_format": "MMM YYYY"},
        )
        assert resp.status_code == 422
