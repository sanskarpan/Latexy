"""Tests for Feature 55: Resume Age Analysis."""
import datetime

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestAgeAnalysisEndpoint:

    async def test_old_entry_flagged(self, client: AsyncClient):
        """Entry from 2010 should be is_old=True (current year > 2020)."""
        resp = await client.post(
            "/ai/age-analysis",
            json={"latex_content": r"\textbf{Acme Corp} \hfill 2010 -- 2015"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_old_entries"] is True
        old = next((e for e in data["entries"] if e["start_year"] == 2010), None)
        assert old is not None
        assert old["is_old"] is True

    async def test_recent_entry_not_flagged(self, client: AsyncClient):
        """Entry from last year should not be is_old."""
        last_year = datetime.date.today().year - 1
        resp = await client.post(
            "/ai/age-analysis",
            json={"latex_content": rf"\textbf{{Recent Co}} \hfill {last_year} -- Present"},
        )
        assert resp.status_code == 200
        data = resp.json()
        recent = next((e for e in data["entries"] if e["start_year"] == last_year), None)
        assert recent is not None
        assert recent["is_old"] is False

    async def test_prestigious_institution_exempt(self, client: AsyncClient):
        """Harvard 2008–2012 → is_prestigious=True, is_old=False."""
        resp = await client.post(
            "/ai/age-analysis",
            json={"latex_content": r"\textbf{Harvard University} \hfill 2008 -- 2012"},
        )
        assert resp.status_code == 200
        data = resp.json()
        entry = next((e for e in data["entries"] if e["start_year"] == 2008), None)
        assert entry is not None
        assert entry["is_prestigious"] is True
        assert entry["is_old"] is False

    async def test_no_years_returns_empty(self, client: AsyncClient):
        """Content with no years returns empty entries."""
        resp = await client.post(
            "/ai/age-analysis",
            json={"latex_content": r"\textbf{No dates here, just plain text.}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["entries"] == []
        assert data["has_old_entries"] is False

    async def test_faang_company_exempt(self, client: AsyncClient):
        """Google 2005–2010 → prestigious, not flagged as old."""
        resp = await client.post(
            "/ai/age-analysis",
            json={"latex_content": r"\textbf{Google LLC} \hfill 2005 -- 2010"},
        )
        assert resp.status_code == 200
        data = resp.json()
        entry = next((e for e in data["entries"] if e["start_year"] == 2005), None)
        assert entry is not None
        assert entry["is_prestigious"] is True
        assert entry["is_old"] is False

    async def test_entries_sorted_newest_first(self, client: AsyncClient):
        """Entries should be sorted newest start_year first."""
        content = (
            r"\textbf{Old Corp} \hfill 2005 -- 2010" + "\n"
            r"\textbf{New Corp} \hfill 2020 -- Present"
        )
        resp = await client.post("/ai/age-analysis", json={"latex_content": content})
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        years = [e["start_year"] for e in entries]
        assert years == sorted(years, reverse=True)

    async def test_years_ago_computed_correctly(self, client: AsyncClient):
        """years_ago matches current_year - start_year."""
        current_year = datetime.date.today().year
        start = 2010
        expected_years_ago = current_year - start
        resp = await client.post(
            "/ai/age-analysis",
            json={"latex_content": rf"\textbf{{Corp}} \hfill {start} -- 2015"},
        )
        assert resp.status_code == 200
        entry = next(
            (e for e in resp.json()["entries"] if e["start_year"] == start), None
        )
        assert entry is not None
        assert entry["years_ago"] == expected_years_ago
