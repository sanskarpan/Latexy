import json
import uuid

import pytest
from httpx import AsyncClient

from app.database.models import ResumeTemplate

_SAMPLE_JSON_RESUME = json.dumps(
    {
        "basics": {
            "name": "Taylor Builder",
            "label": "Senior Backend Engineer",
            "email": "taylor@example.com",
            "phone": "+1-555-0102",
            "url": "https://example.com",
            "summary": "Backend engineer focused on distributed systems and observability.",
            "profiles": [
                {"network": "LinkedIn", "url": "https://linkedin.com/in/taylor"},
                {"network": "GitHub", "url": "https://github.com/taylor"},
            ],
        },
        "work": [
            {
                "name": "Acme",
                "position": "Senior Backend Engineer",
                "startDate": "2022-01",
                "endDate": "",
                "summary": "Platform engineering",
                "highlights": ["Reduced p95 latency by 40%", "Owned API platform migration"],
            }
        ],
        "education": [{"institution": "State University", "studyType": "B.S.", "area": "Computer Science", "endDate": "2020"}],
        "skills": [{"name": "Languages", "keywords": ["Python", "TypeScript", "SQL"]}],
        "projects": [{"name": "Internal Platform", "description": "Developer experience overhaul"}],
    }
)


async def _insert_builder_template(db_session, category: str = "minimal") -> ResumeTemplate:
    template = ResumeTemplate(
        id=str(uuid.uuid4()),
        name=f"test_tmpl_builder_{category}_{uuid.uuid4().hex[:6]}",
        description="Builder-compatible test template",
        category=category,
        tags=[category],
        latex_content=r"\documentclass{article}\begin{document}Template\end{document}",
        is_active=True,
        sort_order=0,
        document_type="resume",
    )
    db_session.add(template)
    await db_session.commit()
    await db_session.refresh(template)
    return template


@pytest.mark.asyncio
class TestResumeBuilder:
    async def test_lists_supported_templates(self, client: AsyncClient, db_session):
        template = await _insert_builder_template(db_session, category="minimal")
        data = (await client.get("/resumes/builder/templates")).json()
        assert any(item["id"] == template.id for item in data)

    async def test_create_builder_resume(self, client: AsyncClient, auth_headers: dict, db_session):
        template = await _insert_builder_template(db_session, category="software_engineering")
        resp = await client.post(
            "/resumes/builder",
            headers=auth_headers,
            json={
                "title": "Builder Resume",
                "template_id": template.id,
                "structured_content": {
                    "basics": {"name": "Taylor Builder", "email": "taylor@example.com", "label": "Backend Engineer"},
                    "experience": [
                        {
                            "id": "exp-1",
                            "title": "Backend Engineer",
                            "company": "Acme",
                            "start_date": "2022",
                            "current": True,
                            "bullets": ["Built resilient APIs"],
                        }
                    ],
                    "education": [{"id": "edu-1", "institution": "State University", "degree": "B.S. Computer Science"}],
                    "skills": [{"id": "skill-1", "name": "Languages", "keywords": ["Python", "Go"]}],
                },
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["resume"]["builder_status"] == "active"
        assert data["resume"]["content_source"] == "builder"
        assert data["resume"]["selected_template_id"] == template.id
        assert data["metrics"]["completeness_score"] > 0
        assert "Taylor Builder" in data["resume"]["latex_content"]

    async def test_get_and_update_builder_resume(self, client: AsyncClient, auth_headers: dict, db_session):
        template = await _insert_builder_template(db_session, category="minimal")
        create_resp = await client.post(
            "/resumes/builder",
            headers=auth_headers,
            json={"title": "Editable Builder", "template_id": template.id},
        )
        resume_id = create_resp.json()["resume"]["id"]

        fetched = await client.get(f"/resumes/{resume_id}/builder", headers=auth_headers)
        assert fetched.status_code == 200

        update_resp = await client.patch(
            f"/resumes/{resume_id}/builder",
            headers=auth_headers,
            json={
                "structured_content": {
                    "basics": {"name": "Updated Name", "email": "updated@example.com", "summary": "Updated summary"},
                    "skills": [{"id": "skill-1", "name": "Core", "keywords": ["Python", "React"]}],
                }
            },
        )
        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["resume"]["structured_version"] >= 2
        assert updated["resume"]["structured_content"]["basics"]["name"] == "Updated Name"

    async def test_manual_editor_update_detaches_builder(self, client: AsyncClient, auth_headers: dict, db_session):
        template = await _insert_builder_template(db_session, category="ats_safe")
        create_resp = await client.post(
            "/resumes/builder",
            headers=auth_headers,
            json={"title": "Detach Builder", "template_id": template.id},
        )
        resume_id = create_resp.json()["resume"]["id"]

        detach_resp = await client.put(
            f"/resumes/{resume_id}",
            headers=auth_headers,
            json={"latex_content": r"\documentclass{article}\begin{document}Manual\end{document}"},
        )
        assert detach_resp.status_code == 200
        assert detach_resp.json()["builder_status"] == "detached"

        patch_resp = await client.patch(
            f"/resumes/{resume_id}/builder",
            headers=auth_headers,
            json={"structured_content": {"basics": {"name": "Blocked"}}},
        )
        assert patch_resp.status_code == 409

        reattach = await client.patch(
            f"/resumes/{resume_id}/builder",
            headers=auth_headers,
            json={"structured_content": {"basics": {"name": "Reattached"}}, "force_reattach": True},
        )
        assert reattach.status_code == 200
        assert reattach.json()["resume"]["builder_status"] == "active"

    async def test_seed_upload_returns_structured_content(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/resumes/builder/seed-upload",
            headers=auth_headers,
            files={"file": ("resume.json", _SAMPLE_JSON_RESUME.encode(), "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["structured_content"]["basics"]["name"] == "Taylor Builder"
        assert data["metrics"]["completeness_score"] > 0
