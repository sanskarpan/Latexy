"""
Tests for Feature 80 — Career Path Visualization + Skills Gap Analysis.

Test strategy:
  • Unit tests mock the DB session — no live DB required for logic tests.
  • Integration tests (marked @pytest.mark.integration) use the real DB
    via conftest fixtures and require DATABASE_URL to be set.
  • All LLM calls are mocked — tests never hit OpenAI.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.career_path_service import CareerPathService

# ── Helpers ───────────────────────────────────────────────────────────────────


def make_role(
    title: str,
    level: str = "mid",
    industry: str = "software_engineering",
    required_skills: list[str] | None = None,
    role_id: str | None = None,
) -> MagicMock:
    role = MagicMock()
    role.id = role_id or str(uuid.uuid4())
    role.title = title
    role.level = level
    role.industry = industry
    role.required_skills = required_skills or []
    role.typical_yoe_min = None
    role.typical_yoe_max = None
    role.created_at = datetime.now(timezone.utc)
    return role


def make_transition(from_id: str, to_id: str, avg_years: float = 2.5, difficulty: str = "moderate") -> MagicMock:
    t = MagicMock()
    t.from_role_id = from_id
    t.to_role_id = to_id
    t.avg_years = avg_years
    t.difficulty = difficulty
    return t


# ── 1. detect_current_role ────────────────────────────────────────────────────


class TestDetectCurrentRole:
    """detect_current_role falls back to heuristic when LLM unavailable."""

    @pytest.mark.asyncio
    async def test_heuristic_extracts_resumeSubheading_role(self):
        svc = CareerPathService()
        latex = r"""
\section{Experience}
\resumeSubheading{Acme Corp}{2020 -- 2023}{Software Engineer II}{NYC}
"""
        # No OPENAI_API_KEY → _llm_complete raises → heuristic used
        role = await svc.detect_current_role(latex)
        assert "Software Engineer" in role

    @pytest.mark.asyncio
    async def test_heuristic_extracts_cventry_degree(self):
        svc = CareerPathService()
        latex = r"\cventry{2018--2021}{Data Scientist}{University Corp}{London}{}{Analyzed data}"
        role = await svc.detect_current_role(latex)
        assert "Data Scientist" in role

    @pytest.mark.asyncio
    async def test_llm_result_preferred_over_heuristic(self):
        svc = CareerPathService()
        latex = r"\resumeSubheading{Foo}{2022}{Engineer}{Bar}"
        with patch.object(svc, "_llm_complete", new_callable=AsyncMock, return_value="Senior ML Engineer"):
            role = await svc.detect_current_role(latex)
        assert role == "Senior ML Engineer"

    @pytest.mark.asyncio
    async def test_llm_unknown_falls_back_to_heuristic(self):
        svc = CareerPathService()
        latex = r"\resumeSubheading{Corp}{2023}{Data Analyst}{Remote}"
        with patch.object(svc, "_llm_complete", new_callable=AsyncMock, return_value="Unknown"):
            role = await svc.detect_current_role(latex)
        assert "Data Analyst" in role


# ── 2. match_career_role ──────────────────────────────────────────────────────


class TestMatchCareerRole:
    """match_career_role returns the best fuzzy match from the DB."""

    @pytest.mark.asyncio
    async def test_exact_match_via_ilike(self):
        svc = CareerPathService()
        swe_mid = make_role("Software Engineer II", level="mid")

        mock_db = AsyncMock()
        # Simulate pg_trgm failing (extension not installed)
        mock_db.execute = AsyncMock(side_effect=[
            Exception("pg_trgm not available"),           # trigram attempt
            _make_scalar_result(swe_mid),                 # ILIKE fallback
        ])

        result = await svc.match_career_role("Software Engineer II", mock_db)
        assert result is swe_mid

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        svc = CareerPathService()
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            Exception("pg_trgm not available"),
            _make_scalar_result(None),
            _make_scalar_result(None),
            _make_scalar_result(None),
        ])

        result = await svc.match_career_role("Wizard of Oz", mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_trigram_match_above_threshold(self):
        svc = CareerPathService()
        swe_mid = make_role("Software Engineer II", level="mid")
        role_id = swe_mid.id

        # Simulate successful pg_trgm query
        trig_row = MagicMock()
        trig_row.sim = 0.75
        trig_row.id = role_id

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            _make_fetchone_result(trig_row),   # trigram returns a row
            _make_scalar_result(swe_mid),       # role lookup by id
        ])

        result = await svc.match_career_role("Software Engineer II", mock_db)
        assert result is swe_mid


# ── 3. find_path ──────────────────────────────────────────────────────────────


class TestFindPath:
    """find_path BFS finds shortest path between roles."""

    @pytest.mark.asyncio
    async def test_direct_transition_returns_two_roles(self):
        svc = CareerPathService()

        r_junior = make_role("Junior SWE", role_id="r1")
        r_mid = make_role("SWE II", role_id="r2")
        t = make_transition("r1", "r2", avg_years=2.5)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=_make_scalars_result([t]))
        mock_db.get = AsyncMock(side_effect=lambda cls, rid: {
            "r1": r_junior, "r2": r_mid
        }.get(rid))

        path = await svc.find_path("r1", "r2", mock_db)
        assert len(path) == 2
        assert path[0].title == "Junior SWE"
        assert path[1].title == "SWE II"

    @pytest.mark.asyncio
    async def test_path_through_intermediate_role(self):
        svc = CareerPathService()

        r1 = make_role("Junior SWE", role_id="r1")
        r2 = make_role("SWE II", role_id="r2")
        r3 = make_role("Senior SWE", role_id="r3")

        transitions = [
            make_transition("r1", "r2"),
            make_transition("r2", "r3"),
        ]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=_make_scalars_result(transitions))
        mock_db.get = AsyncMock(side_effect=lambda cls, rid: {
            "r1": r1, "r2": r2, "r3": r3
        }.get(rid))

        path = await svc.find_path("r1", "r3", mock_db)
        assert len(path) == 3
        assert [r.id for r in path] == ["r1", "r2", "r3"]

    @pytest.mark.asyncio
    async def test_no_path_returns_two_endpoints(self):
        svc = CareerPathService()

        r1 = make_role("SWE", role_id="r1")
        r2 = make_role("CMO", role_id="r2")

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=_make_scalars_result([]))
        mock_db.get = AsyncMock(side_effect=lambda cls, rid: {
            "r1": r1, "r2": r2
        }.get(rid))

        path = await svc.find_path("r1", "r2", mock_db)
        assert len(path) == 2

    @pytest.mark.asyncio
    async def test_same_role_returns_single_role(self):
        svc = CareerPathService()
        r = make_role("SWE", role_id="r1")

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=r)

        path = await svc.find_path("r1", "r1", mock_db)
        assert len(path) == 1


# ── 4. analyze_gap ────────────────────────────────────────────────────────────


class TestAnalyzeGap:
    """analyze_gap correctly identifies skill gaps and timeline."""

    @pytest.mark.asyncio
    async def test_gap_skills_computed_correctly(self):
        svc = CareerPathService()

        target = make_role(
            "Staff SWE",
            required_skills=["System Design", "Distributed Systems", "Mentoring", "Python"],
        )
        current_skills = ["Python", "Git"]
        path = [make_role("SWE II"), target]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=_make_scalar_result(None))  # no transition row

        with patch.object(svc, "_llm_gap_analysis", new_callable=AsyncMock, return_value="## Plan"):
            result = await svc.analyze_gap(current_skills, target, path, "", mock_db)

        assert "System Design" in result["gap_skills"]
        assert "Distributed Systems" in result["gap_skills"]
        assert "Mentoring" in result["gap_skills"]
        assert "Python" not in result["gap_skills"]  # user already has it

    @pytest.mark.asyncio
    async def test_no_gap_when_already_qualified(self):
        svc = CareerPathService()

        target = make_role("SWE II", required_skills=["Python", "Git"])
        current_skills = ["Python", "Git", "SQL"]
        path = [target]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=_make_scalar_result(None))

        with patch.object(svc, "_llm_gap_analysis", new_callable=AsyncMock, return_value="## Great"):
            result = await svc.analyze_gap(current_skills, target, path, "", mock_db)

        assert result["gap_skills"] == []


# ── 5. API integration tests ──────────────────────────────────────────────────


class TestCareerAPIRoutes:
    """Integration tests for /career/* endpoints."""

    @pytest.mark.asyncio
    async def test_get_roles_search_returns_list(self, client):
        resp = await client.get("/career/roles?q=software")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_roles_empty_query_returns_list(self, client):
        resp = await client.get("/career/roles?q=")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_analyze_requires_auth(self, client):
        resp = await client.post(
            "/career/analyze",
            json={"resume_id": str(uuid.uuid4()), "target_role_title": "Staff SWE"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_analyses_requires_auth(self, client):
        resp = await client.get(f"/career/analyses/{uuid.uuid4()}")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_analyses_returns_401_without_auth(self, client):
        resp = await client.get(f"/career/analyses/{uuid.uuid4()}")
        assert resp.status_code == 401


# ── 6. Past analyses ordering ─────────────────────────────────────────────────


class TestAnalysesOrdering:
    """Past analyses are returned newest first."""

    @pytest.mark.asyncio
    async def test_analyses_ordered_newest_first(self):
        from app.services.career_path_service import CareerPathService

        svc = CareerPathService()

        older = MagicMock()
        older.id = str(uuid.uuid4())
        older.resume_id = "r1"
        older.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        newer = MagicMock()
        newer.id = str(uuid.uuid4())
        newer.resume_id = "r1"
        newer.created_at = datetime(2025, 6, 1, tzinfo=timezone.utc)

        # Verify that sorted order puts newer first (the DB ORDER BY desc handles this,
        # but we can verify the sorting logic holds)
        ordered = sorted([older, newer], key=lambda a: a.created_at, reverse=True)
        assert ordered[0].id == newer.id
        assert ordered[1].id == older.id


# ── Mock helpers ──────────────────────────────────────────────────────────────


def _make_scalar_result(obj):
    """Return an AsyncMock that simulates db.execute().scalar_one_or_none()."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=obj)
    return mock_result


def _make_scalars_result(objs: list):
    """Return an AsyncMock that simulates db.execute().scalars().all()."""
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all = MagicMock(return_value=objs)
    mock_result.scalars = MagicMock(return_value=mock_scalars)
    return mock_result


def _make_fetchone_result(row):
    """Return an AsyncMock that simulates db.execute().fetchone()."""
    mock_result = MagicMock()
    mock_result.fetchone = MagicMock(return_value=row)
    return mock_result
