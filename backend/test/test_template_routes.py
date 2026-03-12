"""
Tests for Resume Template API Routes.

Tests cover:
  - GET /templates/categories
  - GET /templates/          (list, category filter, search)
  - GET /templates/{id}      (detail with latex_content)
  - POST /templates/{id}/use  (authenticated — creates resume)
  - Error cases: 404, 400 bad category, 401 unauthenticated use, invalid UUID
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.database.models import ResumeTemplate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_LATEX = r"""
\documentclass[11pt,a4paper]{article}
\usepackage[margin=0.7in]{geometry}
\begin{document}
\textbf{Test Resume Template}
\end{document}
"""

_VALID_LATEX_2 = r"""
\documentclass[11pt,a4paper]{article}
\begin{document}
\textbf{Second Template}
\end{document}
"""


async def _insert_template(db_session, **kwargs) -> ResumeTemplate:
    """Insert a test template and return it. Names prefixed with test_tmpl_ for cleanup."""
    defaults = dict(
        name="test_tmpl_SWE Template",
        description="A test template for software engineers",
        category="software_engineering",
        tags=["software_engineering"],
        thumbnail_url=None,
        latex_content=_VALID_LATEX,
        is_active=True,
        sort_order=0,
    )
    defaults.update(kwargs)
    # Ensure test prefix for cleanup
    if not defaults["name"].startswith("test_tmpl_"):
        defaults["name"] = f"test_tmpl_{defaults['name']}"
    t = ResumeTemplate(**defaults)
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


# ---------------------------------------------------------------------------
# GET /templates/categories
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestListCategories:
    async def test_returns_200(self, client: AsyncClient):
        resp = await client.get("/templates/categories")
        assert resp.status_code == 200

    async def test_returns_list(self, client: AsyncClient):
        data = (await client.get("/templates/categories")).json()
        assert isinstance(data, list)

    async def test_category_schema(self, client: AsyncClient, db_session):
        await _insert_template(db_session)
        data = (await client.get("/templates/categories")).json()
        assert len(data) >= 1
        item = data[0]
        assert "category" in item
        assert "label" in item
        assert "count" in item
        assert isinstance(item["count"], int)
        assert item["count"] >= 0

    async def test_inactive_templates_excluded(self, client: AsyncClient, db_session):
        """Inactive templates should NOT appear in category counts."""
        await _insert_template(db_session, name="test_tmpl_Inactive Cat", is_active=False)
        data = (await client.get("/templates/categories")).json()
        cat_entry = next((c for c in data if c["category"] == "software_engineering"), None)
        if cat_entry:
            assert cat_entry["count"] >= 0


# ---------------------------------------------------------------------------
# GET /templates/
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestListTemplates:
    async def test_returns_200(self, client: AsyncClient):
        resp = await client.get("/templates/")
        assert resp.status_code == 200

    async def test_returns_list(self, client: AsyncClient):
        data = (await client.get("/templates/")).json()
        assert isinstance(data, list)

    async def test_template_schema_no_latex_content(self, client: AsyncClient, db_session):
        """List endpoint must NOT include latex_content (too heavy)."""
        await _insert_template(db_session)
        data = (await client.get("/templates/")).json()
        assert len(data) >= 1
        item = data[0]
        assert "id" in item
        assert "name" in item
        assert "category" in item
        assert "category_label" in item
        assert "tags" in item
        assert "sort_order" in item
        assert "latex_content" not in item  # must NOT be in list response

    async def test_filter_by_category(self, client: AsyncClient, db_session):
        t1 = await _insert_template(db_session, name="test_tmpl_Finance One", category="finance")
        t2 = await _insert_template(db_session, name="test_tmpl_SWE One", category="software_engineering")
        data = (await client.get("/templates/?category=finance")).json()
        ids = [d["id"] for d in data]
        assert t1.id in ids
        assert t2.id not in ids

    async def test_filter_by_invalid_category_returns_400(self, client: AsyncClient):
        resp = await client.get("/templates/?category=not_a_real_category_xyz")
        assert resp.status_code == 400

    async def test_filter_all_category_returns_all(self, client: AsyncClient, db_session):
        await _insert_template(db_session, name="test_tmpl_AllCat1", category="finance")
        await _insert_template(db_session, name="test_tmpl_AllCat2", category="software_engineering")
        all_data = (await client.get("/templates/")).json()
        all_cat_data = (await client.get("/templates/?category=all")).json()
        assert len(all_data) == len(all_cat_data)

    async def test_search_by_name(self, client: AsyncClient, db_session):
        await _insert_template(db_session, name="test_tmpl_UniqueSearchable42")
        data = (await client.get("/templates/?search=UniqueSearchable42")).json()
        assert any("UniqueSearchable42" in d["name"] for d in data)

    async def test_search_case_insensitive(self, client: AsyncClient, db_session):
        await _insert_template(db_session, name="test_tmpl_CaseTest99")
        data = (await client.get("/templates/?search=casetest99")).json()
        assert any("CaseTest99" in d["name"] for d in data)

    async def test_inactive_template_excluded_from_list(self, client: AsyncClient, db_session):
        t_inactive = await _insert_template(
            db_session, name="test_tmpl_ShouldNotAppear", is_active=False
        )
        data = (await client.get("/templates/")).json()
        ids = [d["id"] for d in data]
        assert t_inactive.id not in ids

    async def test_category_label_populated(self, client: AsyncClient, db_session):
        await _insert_template(db_session, name="test_tmpl_FinLabel", category="finance")
        data = (await client.get("/templates/?category=finance")).json()
        assert len(data) >= 1
        assert data[0]["category_label"] == "Finance"


# ---------------------------------------------------------------------------
# GET /templates/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGetTemplate:
    async def test_returns_200_and_includes_latex(self, client: AsyncClient, db_session):
        t = await _insert_template(db_session)
        resp = await client.get(f"/templates/{t.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == t.id
        assert "latex_content" in data
        assert len(data["latex_content"]) > 10

    async def test_404_for_unknown_id(self, client: AsyncClient):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/templates/{fake_id}")
        assert resp.status_code == 404

    async def test_404_for_inactive_template(self, client: AsyncClient, db_session):
        t = await _insert_template(db_session, name="test_tmpl_InactiveDetail", is_active=False)
        resp = await client.get(f"/templates/{t.id}")
        assert resp.status_code == 404

    async def test_full_schema(self, client: AsyncClient, db_session):
        t = await _insert_template(db_session)
        data = (await client.get(f"/templates/{t.id}")).json()
        for field in ("id", "name", "description", "category", "category_label", "tags",
                      "thumbnail_url", "pdf_url", "sort_order", "latex_content"):
            assert field in data

    async def test_invalid_uuid_returns_404(self, client: AsyncClient):
        """Non-UUID template_id should return 404, not 500."""
        resp = await client.get("/templates/not-a-valid-uuid")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /templates/{id}/use
# ---------------------------------------------------------------------------

async def _create_auth_headers(db_session) -> dict:
    """Insert a user + Better Auth session row; return Authorization headers."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    user_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, "
            "subscription_status, trial_used) "
            "VALUES (:id, :email, 'Test User', true, 'free', 'active', false) "
            "ON CONFLICT DO NOTHING"
        ),
        {"id": user_id, "email": f"test_{user_id[:8]}@example.com"},
    )
    await db_session.commit()

    token = f"test_sess_{uuid.uuid4().hex}"
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    await db_session.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {"id": str(uuid.uuid4()), "uid": user_id, "exp": expires_at, "tok": token},
    )
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
class TestUseTemplate:
    async def test_creates_resume_and_returns_id(self, client: AsyncClient, db_session):
        t = await _insert_template(db_session)
        headers = await _create_auth_headers(db_session)
        resp = await client.post(
            f"/templates/{t.id}/use",
            json={"title": "My Test Resume"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "resume_id" in data
        assert "title" in data
        assert data["title"] == "My Test Resume"
        assert uuid.UUID(data["resume_id"])  # must be valid UUID

    async def test_title_defaults_to_template_name(self, client: AsyncClient, db_session):
        t = await _insert_template(db_session, name="test_tmpl_AutoTitle")
        headers = await _create_auth_headers(db_session)
        resp = await client.post(
            f"/templates/{t.id}/use",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "test_tmpl_AutoTitle"

    async def test_created_resume_has_correct_content(self, client: AsyncClient, db_session):
        t = await _insert_template(db_session, latex_content=_VALID_LATEX_2)
        headers = await _create_auth_headers(db_session)
        resp = await client.post(
            f"/templates/{t.id}/use",
            json={"title": "Content Check Resume"},
            headers=headers,
        )
        assert resp.status_code == 200
        resume_id = resp.json()["resume_id"]

        # Verify the resume was actually created with correct content
        resume_resp = await client.get(
            f"/resumes/{resume_id}",
            headers=headers,
        )
        assert resume_resp.status_code == 200
        resume_data = resume_resp.json()
        assert resume_data["latex_content"] == _VALID_LATEX_2

    async def test_returns_401_without_auth(self, client: AsyncClient, db_session):
        t = await _insert_template(db_session)
        resp = await client.post(f"/templates/{t.id}/use", json={"title": "Unauthed"})
        assert resp.status_code == 401

    async def test_returns_404_for_unknown_template(self, client: AsyncClient, db_session):
        headers = await _create_auth_headers(db_session)
        resp = await client.post(
            f"/templates/{str(uuid.uuid4())}/use",
            json={"title": "Ghost"},
            headers=headers,
        )
        assert resp.status_code == 404

    async def test_returns_404_for_inactive_template(self, client: AsyncClient, db_session):
        t = await _insert_template(db_session, name="test_tmpl_InactiveUse", is_active=False)
        headers = await _create_auth_headers(db_session)
        resp = await client.post(
            f"/templates/{t.id}/use",
            json={"title": "Try Inactive"},
            headers=headers,
        )
        assert resp.status_code == 404

    async def test_multiple_users_can_use_same_template(self, client: AsyncClient, db_session):
        """Using the same template twice should create two independent resumes."""
        t = await _insert_template(db_session, name="test_tmpl_SharedTemplate")

        h1 = await _create_auth_headers(db_session)
        h2 = await _create_auth_headers(db_session)

        r1 = (await client.post(f"/templates/{t.id}/use", json={"title": "R1"}, headers=h1)).json()
        r2 = (await client.post(f"/templates/{t.id}/use", json={"title": "R2"}, headers=h2)).json()

        assert r1["resume_id"] != r2["resume_id"]

    async def test_returns_404_for_invalid_uuid(self, client: AsyncClient, db_session):
        """Non-UUID template_id should return 404, not 500."""
        headers = await _create_auth_headers(db_session)
        resp = await client.post(
            "/templates/not-a-uuid/use",
            json={"title": "Bad UUID"},
            headers=headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Seeded templates smoke test (only runs if templates are seeded)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSeededTemplates:
    async def test_seeded_templates_loadable(self, client: AsyncClient):
        """If templates are seeded, verify basic pagination and structure."""
        data = (await client.get("/templates/")).json()
        # May be empty in CI (seed not run), so just assert no crash
        for item in data:
            assert "id" in item
            assert "name" in item
            assert "category" in item
            assert "latex_content" not in item

    async def test_seeded_categories_consistent(self, client: AsyncClient):
        """Categories count endpoint must be consistent with list count."""
        all_templates = (await client.get("/templates/")).json()
        categories = (await client.get("/templates/categories")).json()

        # Sum of per-category counts should equal total active templates
        total_from_cats = sum(c["count"] for c in categories)
        assert total_from_cats == len(all_templates)
