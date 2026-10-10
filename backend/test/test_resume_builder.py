import json
import re
import uuid

import pytest
from httpx import AsyncClient

from app.database.models import ResumeTemplate
from app.services.resume_builder_service import BuilderExperienceEntry, resume_builder_service

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
        "education": [
            {"institution": "State University", "studyType": "B.S.", "area": "Computer Science", "endDate": "2020"}
        ],
        "skills": [{"name": "Languages", "keywords": ["Python", "TypeScript", "SQL"]}],
        "projects": [{"name": "Internal Platform", "description": "Developer experience overhaul"}],
    }
)


def test_builder_bullet_ids_are_bounded_safe_unique_and_deterministic() -> None:
    entry = BuilderExperienceEntry(
        id="hostile entry/\u0000" + "x" * 240,
        bullets=["one", "two", "three", "four"],
        bullet_ids=["ok-id", "bad id", "ok-id", "\u0000"],
    )
    assert len(entry.bullet_ids) == 4
    assert len(set(entry.bullet_ids)) == 4
    assert all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,95}", value) for value in entry.bullet_ids)
    again = BuilderExperienceEntry(
        id=entry.id,
        bullets=entry.bullets,
        bullet_ids=["ok-id", "bad id", "ok-id", "\u0000"],
    )
    assert again.bullet_ids == entry.bullet_ids


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
        (r"\input{/etc/passwd}", r"\textbackslash{}input\{/etc/passwd\}"),
    ],
)
def test_builder_renderer_escapes_original_characters_once(text: str, expected: str) -> None:
    assert resume_builder_service._escape(text) == expected


@pytest.mark.parametrize("category", ["ats_safe", "minimal", "executive", "software_engineering", "graduate"])
def test_builder_renderer_headline_keeps_special_characters(category: str) -> None:
    rendered = resume_builder_service.render(
        {"basics": {"name": "Taylor", "label": r"R&D / C# / 100% / C:\tools"}}, category
    )
    assert r"R\&D / C\# / 100\% / C:\textbackslash{}tools" in rendered.latex_content
    assert r"\textbackslash\{\}" not in rendered.latex_content


@pytest.mark.parametrize("bullets", [[], ["Reduced failures by 25%"]])
def test_builder_renderer_keeps_experience_technologies_with_or_without_bullets(bullets: list[str]) -> None:
    content = {
        "experience": [{
            "id": "work-1", "title": "Engineer", "company": "Acme", "location": "Remote",
            "start_date": "2024", "current": True, "summary": "Platform ownership",
            "bullets": bullets, "technologies": ["Python", "C#"],
        }],
    }
    latex = resume_builder_service.render(content, "minimal").latex_content
    preview = resume_builder_service.build_preview(content, "minimal")
    experience = next(section for section in preview["sections"] if section["key"] == "experience")
    assert r"\textit{Technologies:} Python, C\#\\" in latex
    assert "Platform ownership" in latex
    assert experience["items"][0]["meta"] == "Remote | 2024 - Present | Technologies: Python, C#"
    assert experience["items"][0]["bullets"] == ["Platform ownership", *bullets]
    if bullets:
        assert r"\item Reduced failures by 25\%" in latex


def test_builder_renderer_keeps_certification_url_in_preview_and_document() -> None:
    content = {
        "certifications": [{
            "id": "cert-1", "name": "Cloud Certification", "issuer": "Example Academy", "date": "2026-10-08",
            "url": "https://example.com/cert?name=Taylor&track=cloud",
        }],
    }
    latex = resume_builder_service.render(content, "minimal").latex_content
    preview = resume_builder_service.build_preview(content, "minimal")
    certification = next(section for section in preview["sections"] if section["key"] == "certifications")
    assert r"https://example.com/cert?name=Taylor\&track=cloud" in latex
    assert certification["items"][0]["meta"] == (
        "Example Academy | 2026-10-08 | https://example.com/cert?name=Taylor&track=cloud"
    )


def test_builder_renderer_education_preview_includes_field_and_gpa() -> None:
    content = {
        "education": [{
            "id": "edu-1", "institution": "State University", "degree": "B.S.", "field": "Computer Science",
            "location": "Mumbai", "end_date": "2024", "gpa": "3.8/4.0", "highlights": ["Honours"],
        }],
    }
    latex = resume_builder_service.render(content, "minimal").latex_content
    preview = resume_builder_service.build_preview(content, "minimal")
    education = next(section for section in preview["sections"] if section["key"] == "education")
    assert "Computer Science" in latex and "GPA 3.8/4.0" in latex
    assert education["items"][0]["title"] == "B.S. | Computer Science — State University"
    assert education["items"][0]["meta"] == "Mumbai | 2024 | GPA 3.8/4.0"
    assert education["items"][0]["bullets"] == ["Honours"]


def test_builder_metrics_empty_entries_do_not_improve_health_or_inflate_pages() -> None:
    content = {
        "basics": {"name": "  ", "email": "\t", "summary": "\n"},
        "experience": [{"id": f"work-{index}", "bullets": [" "]} for index in range(30)],
        "education": [{"id": f"edu-{index}", "highlights": [" "]} for index in range(30)],
        "projects": [{"id": f"project-{index}", "technologies": [" "]} for index in range(30)],
        "skills": [{"id": "skill-1", "name": "Empty group", "keywords": [" "]}],
    }
    rendered = resume_builder_service.render(content, "minimal")
    metrics = rendered.metrics
    assert metrics.completeness_score == 0
    assert metrics.page_estimate == 1
    assert set(metrics.missing_sections) == {"name", "email", "summary", "experience", "education", "skills"}
    assert r"\section*" not in rendered.latex_content
    assert resume_builder_service.build_preview(content, "minimal")["sections"] == []


def test_builder_metrics_hidden_content_does_not_add_points_pages_or_density_warnings() -> None:
    content = {
        "basics": {"name": "Taylor", "email": "taylor@example.com", "label": "Engineer", "summary": "Summary\n" * 50},
        "experience": [{"id": "work-1", "company": "Acme", "bullets": ["A detailed accomplishment"] * 50}],
        "education": [{"id": "edu-1", "institution": "State University"}],
        "projects": [{"id": "project-1", "name": "Portfolio"}],
        "skills": [{"id": "skill-1", "keywords": ["Python"]}],
        "hidden_sections": ["summary", "experience", "education", "projects", "skills"],
    }
    metrics = resume_builder_service.render(content, "minimal").metrics
    assert metrics.completeness_score == 25
    assert metrics.page_estimate == 1
    assert metrics.missing_sections == []
    assert metrics.warnings == []


def test_builder_metrics_meaningful_visible_content_retains_existing_weights() -> None:
    content = {
        "basics": {"name": "Taylor", "email": "taylor@example.com", "label": "Engineer", "summary": "Engineer focused on reliable systems"},
        "experience": [{"id": "work-1", "company": "Acme", "bullets": ["Built reliable APIs"]}],
        "education": [{"id": "edu-1", "institution": "State University"}],
        "projects": [{"id": "project-1", "name": "Portfolio"}],
        "skills": [{"id": "skill-1", "keywords": ["Python"]}],
    }
    metrics = resume_builder_service.render(content, "minimal").metrics
    assert metrics.completeness_score == 100
    assert metrics.missing_sections == []
    assert metrics.page_estimate == 1


def test_builder_metrics_include_only_visible_optional_section_content_in_page_estimate() -> None:
    content = {
        "certifications": [{"id": f"cert-{index}", "name": "Professional certification"} for index in range(40)],
        "awards": [{"id": f"award-{index}", "name": "Professional award"} for index in range(40)],
    }
    visible = resume_builder_service.render(content, "minimal").metrics
    hidden = resume_builder_service.render({**content, "hidden_sections": ["certifications", "awards"]}, "minimal").metrics
    assert visible.page_estimate > 1
    assert hidden.page_estimate == 1
    assert visible.completeness_score == hidden.completeness_score == 0


def test_builder_renderer_does_not_emit_an_empty_education_itemize() -> None:
    content = {"education": [{"id": "edu-1", "institution": "State University", "highlights": [" ", "\n"]}]}
    latex = resume_builder_service.render(content, "minimal").latex_content
    assert "State University" in latex
    assert r"\begin{itemize}" not in latex


def test_builder_renderer_project_preview_keeps_dates_and_technologies() -> None:
    content = {"projects": [{
        "id": "project-1", "name": "Portfolio", "role": "Developer", "url": "https://example.com",
        "start_date": "2024", "end_date": "2025", "technologies": ["Python", " ", "C#"],
    }]}
    latex = resume_builder_service.render(content, "minimal").latex_content
    preview = resume_builder_service.build_preview(content, "minimal")
    project = next(section for section in preview["sections"] if section["key"] == "projects")
    assert project["items"][0]["meta"] == "Developer | https://example.com | 2024 - 2025 | Technologies: Python, C#"
    assert r"\textit{Technologies:} Python, C\#\\" in latex


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
                    "education": [
                        {"id": "edu-1", "institution": "State University", "degree": "B.S. Computer Science"}
                    ],
                    "skills": [{"id": "skill-1", "name": "Languages", "keywords": ["Python", "Go"]}],
                },
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["resume"]["builder_status"] == "active"
        assert data["resume"]["content_source"] == "builder"
        assert data["resume"]["selected_template_id"] == template.id
        assert data["resume"]["metadata"]["compiler"] == "lualatex"
        assert data["metrics"]["completeness_score"] > 0
        assert "Taylor Builder" in data["resume"]["latex_content"]
        assert data["ats_profile"]["identity"] == {
            "given_name": "Taylor",
            "family_name": "Builder",
        }
        assert data["ats_profile"]["work"][0]["employer"] == "Acme"
        assert data["ats_profile"]["work"][0]["start_date"] == {
            "value": "2022",
            "is_current": False,
            "found_year": True,
            "found_month": False,
            "found_day": False,
        }
        assert data["ats_profile"]["work"][0]["end_date"]["is_current"] is True
        assert data["ats_profile"]["skills"] == ["Python", "Go"]

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
        assert updated["resume"]["structured_version"] == 2
        assert updated["resume"]["content_revision"] >= 2
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
            json={
                "latex_content": r"\documentclass{article}\begin{document}Manual\end{document}",
                "expected_latex_content": create_resp.json()["resume"]["latex_content"],
            },
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
            json={
                "structured_content": {"basics": {"name": "Reattached"}},
                "force_reattach": True,
                "expected_latex_content": detach_resp.json()["latex_content"],
            },
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
        assert data["format"] == "json_resume_v1"
        assert data["structured_content"]["basics"]["name"] == "Taylor Builder"
        assert data["structured_content"]["experience"][0]["summary"] == "Platform engineering"
        assert data["structured_content"]["projects"][0]["description"] == "Developer experience overhaul"
        assert data["metrics"]["completeness_score"] > 0

    async def test_seed_upload_pinpoints_semantic_json_error_source(self, client: AsyncClient, auth_headers: dict):
        invalid = """{
  "$schema": "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json",
  "basics": {"name": "Taylor"},
  "work": [
    {
      "name": "Acme",
      "startDate": "April 2024"
    }
  ]
}
"""
        response = await client.post(
            "/resumes/builder/seed-upload",
            headers=auth_headers,
            files={"file": ("invalid.json", invalid.encode(), "application/json")},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "resume_validation_error"
        issue = response.json()["error"]["details"]["issues"][0]
        assert issue["path"] == "work[0].startDate"
        assert issue["line"] == 7
        assert issue["column"] == 7

    async def test_seed_upload_pinpoints_json_syntax_error(self, client: AsyncClient, auth_headers: dict):
        invalid = '{\n  "basics": {\n    "name": "Taylor",\n  }\n}'
        response = await client.post(
            "/resumes/builder/seed-upload",
            headers=auth_headers,
            files={"file": ("invalid.json", invalid.encode(), "application/json")},
        )

        assert response.status_code == 422
        issue = response.json()["error"]["details"]["issues"][0]
        assert issue["path"] == "$"
        assert issue["line"] == 4
        assert issue["column"] == 3

    async def test_builder_create_rejects_unknown_structured_field_with_path(
        self, client: AsyncClient, auth_headers: dict, db_session
    ):
        template = await _insert_builder_template(db_session, category="minimal")
        response = await client.post(
            "/resumes/builder",
            headers=auth_headers,
            json={
                "title": "Strict Builder",
                "template_id": template.id,
                "structured_content": {"basics": {"nickname": "Taylor"}},
            },
        )

        assert response.status_code == 422
        issue = response.json()["error"]["details"]["issues"][0]
        assert issue["path"] == "structured_content.basics.nickname"

    async def test_builder_json_export_uses_structured_content(
        self, client: AsyncClient, auth_headers: dict, db_session
    ):
        template = await _insert_builder_template(db_session, category="minimal")
        create_resp = await client.post(
            "/resumes/builder",
            headers=auth_headers,
            json={
                "title": "Interchange Resume",
                "template_id": template.id,
                "structured_content": {
                    "basics": {"name": "Taylor Builder", "email": "taylor@example.com"},
                    "experience": [
                        {
                            "id": "work-1",
                            "title": "Engineer",
                            "company": "Acme",
                            "start_date": "2022-01",
                            "current": True,
                            "summary": "Platform ownership",
                            "bullets": ["Reduced p95 latency by 40%"],
                            "technologies": ["Python"],
                        }
                    ],
                },
            },
        )
        resume_id = create_resp.json()["resume"]["id"]

        exported = await client.get(f"/export/{resume_id}/json", headers=auth_headers)

        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith("application/json")
        assert "attachment" in exported.headers["content-disposition"]
        payload = exported.json()
        assert payload["meta"]["version"] == "v1.0.0"
        assert payload["work"][0]["name"] == "Acme"
        assert payload["work"][0]["keywords"] == ["Python"]
        assert "endDate" not in payload["work"][0]

    async def test_builder_fork_links_master_content_with_per_variant_visibility(
        self, client: AsyncClient, auth_headers: dict, db_session
    ):
        template = await _insert_builder_template(db_session, category="minimal")
        source = {
            "basics": {"name": "Taylor", "summary": "Platform engineer"},
            "experience": [
                {
                    "id": "role-1",
                    "title": "Engineer",
                    "company": "Acme",
                    "bullets": ["Built APIs", "Reduced latency"],
                },
                {
                    "id": "role-2",
                    "title": "Intern",
                    "company": "Beta",
                    "bullets": ["Shipped tests"],
                },
            ],
        }
        parent = await client.post(
            "/resumes/builder",
            headers=auth_headers,
            json={"title": "Master", "template_id": template.id, "structured_content": source},
        )
        assert parent.status_code == 201, parent.text
        parent_id = parent.json()["resume"]["id"]
        forked = await client.post(
            f"/resumes/{parent_id}/fork",
            headers=auth_headers,
            json={"title": "Backend Variant"},
        )
        assert forked.status_code == 201, forked.text
        variant = forked.json()
        assert variant["content_source"] == "builder_variant"
        assert variant["structured_content"] is None

        updated = await client.patch(
            f"/resumes/{variant['id']}/variant-visibility",
            headers=auth_headers,
            json={
                "title": "Backend Role Variant",
                "visibility": {
                    "hidden_entries": {"experience": ["role-2"]},
                    "hidden_list_items": {"experience": {"role-1": [{"index": 1, "value": "Reduced latency"}]}},
                },
            },
        )
        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["resume"]["title"] == "Backend Role Variant"
        assert [entry["id"] for entry in body["effective_content"]["experience"]] == ["role-1"]
        assert body["effective_content"]["experience"][0]["bullets"] == ["Built APIs"]
        assert "Reduced latency" not in body["resume"]["latex_content"]

        source["experience"][0]["bullets"] = ["Built APIs", "Cut latency by 40%"]
        source["experience"].append(
            {
                "id": "role-3",
                "title": "Lead",
                "company": "Gamma",
                "bullets": ["Led delivery"],
            }
        )
        master_update = await client.patch(
            f"/resumes/{parent_id}/builder",
            headers=auth_headers,
            json={"structured_content": source},
        )
        assert master_update.status_code == 200, master_update.text
        refreshed = await client.get(f"/resumes/{variant['id']}/variant-visibility", headers=auth_headers)
        assert refreshed.status_code == 200, refreshed.text
        refreshed_body = refreshed.json()
        assert "Cut latency by 40\\%" in refreshed_body["resume"]["latex_content"]
        assert refreshed_body["effective_content"]["experience"][0]["bullets"][1] == "Cut latency by 40%"
        assert "Led delivery" in refreshed_body["resume"]["latex_content"]
        assert refreshed_body["visibility"]["hidden_list_items"] == {}
        assert refreshed_body["source_content"]["experience"][0]["bullets"][1] == "Cut latency by 40%"

    async def test_manual_edit_detaches_linked_variant_from_future_master_sync(
        self, client: AsyncClient, auth_headers: dict, db_session
    ):
        template = await _insert_builder_template(db_session, category="minimal")
        parent = await client.post(
            "/resumes/builder",
            headers=auth_headers,
            json={
                "title": "Master Detach",
                "template_id": template.id,
                "structured_content": {"basics": {"name": "Original"}},
            },
        )
        parent_id = parent.json()["resume"]["id"]
        forked = await client.post(f"/resumes/{parent_id}/fork", headers=auth_headers, json={})
        variant_id = forked.json()["id"]
        manual = r"\documentclass{article}\begin{document}Independent\end{document}"
        detached = await client.put(
            f"/resumes/{variant_id}",
            headers=auth_headers,
            json={"latex_content": manual, "expected_latex_content": forked.json()["latex_content"]},
        )
        assert detached.status_code == 200
        assert detached.json()["content_source"] == "manual_latex"
        assert detached.json()["variant_visibility"] is None

        assert (
            await client.patch(
                f"/resumes/{parent_id}/builder",
                headers=auth_headers,
                json={"structured_content": {"basics": {"name": "Changed Master"}}},
            )
        ).status_code == 200
        reloaded = await client.get(f"/resumes/{variant_id}", headers=auth_headers)
        assert reloaded.json()["latex_content"] == manual

    async def test_builder_json_export_reports_non_schema_dates(
        self, client: AsyncClient, auth_headers: dict, db_session
    ):
        template = await _insert_builder_template(db_session, category="minimal")
        created = await client.post(
            "/resumes/builder",
            headers=auth_headers,
            json={
                "title": "Invalid interchange date",
                "template_id": template.id,
                "structured_content": {
                    "experience": [
                        {
                            "id": "work-1",
                            "title": "Engineer",
                            "company": "Acme",
                            "start_date": "Spring 2024",
                        }
                    ]
                },
            },
        )

        exported = await client.get(f"/export/{created.json()['resume']['id']}/json", headers=auth_headers)

        assert exported.status_code == 422
        assert "must use YYYY" in exported.json()["detail"]


@pytest.mark.parametrize("category", ["ats_safe", "minimal", "executive"])
def test_builder_custom_headings_preserve_content_filtering_and_certification_url(category):
    content = {
        "section_titles": {"experience": "Career History", "education": "Training",
                           "skills": "Expertise", "projects": "Selected Work", "certifications": "Credentials"},
        "experience": [{"id": "empty-work"}, {"id": "work", "company": "Example", "title": "Engineer"}],
        "education": [{"id": "empty-school"}],
        "skills": [{"id": "empty-skills", "keywords": [" "]}],
        "projects": [{"id": "empty-project"}],
        "certifications": [{"id": "certificate", "name": "Example Certificate", "url": "https://example.test/cert"}],
    }
    latex = resume_builder_service.render(content, category).latex_content
    sections = resume_builder_service.build_preview(content, category)["sections"]
    assert "Career History" in latex and "Credentials" in latex
    assert "https://example.test/cert" in latex
    for heading in ("Training", "Expertise", "Selected Work"):
        assert heading not in latex
    assert [section["title"] for section in sections] == ["Career History", "Credentials"]
