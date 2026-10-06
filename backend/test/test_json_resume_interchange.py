import pytest

from app.services.json_resume_interchange_service import (
    JSON_RESUME_SCHEMA_URL,
    json_resume_interchange_service,
)

JSON_RESUME = {
    "$schema": JSON_RESUME_SCHEMA_URL,
    "basics": {
        "name": "Taylor Builder",
        "label": "Platform Engineer",
        "email": "taylor@example.com",
        "phone": "+1 555 0102",
        "url": "https://taylor.example",
        "summary": "Builds reliable systems.",
        "location": {"city": "Pune", "region": "MH", "countryCode": "IN"},
        "profiles": [
            {"network": "LinkedIn", "url": "https://linkedin.com/in/taylor"},
            {"network": "GitHub", "url": "https://github.com/taylor"},
            {"network": "Mastodon", "url": "https://example.social/@taylor"},
        ],
    },
    "work": [
        {
            "id": "work-acme",
            "name": "Acme",
            "position": "Staff Engineer",
            "location": "Remote",
            "startDate": "2022-04",
            "summary": "Led the platform group.",
            "highlights": ["Reduced p95 latency by 40%"],
            "keywords": ["Python", "Kubernetes"],
        }
    ],
    "education": [
        {
            "institution": "State University",
            "studyType": "BSc",
            "area": "Computer Science",
            "startDate": "2016",
            "endDate": "2020-05",
            "score": "3.8/4.0",
            "courses": ["Distributed Systems"],
        }
    ],
    "projects": [
        {
            "name": "Release Platform",
            "description": "Safe progressive delivery.",
            "highlights": ["Adopted by 20 teams"],
            "keywords": ["Go"],
            "roles": ["Lead"],
            "startDate": "2023",
            "url": "https://github.com/taylor/release-platform",
        }
    ],
    "skills": [{"name": "Cloud", "keywords": ["AWS", "Terraform"]}],
    "certificates": [
        {
            "name": "Cloud Professional",
            "issuer": "Example Cloud",
            "date": "2024-02-10",
            "url": "https://certs.example/taylor",
        }
    ],
    "awards": [{"title": "Engineering Award", "date": "2024", "awarder": "Acme", "summary": "Reliability work"}],
    "languages": [{"language": "English", "fluency": "Native"}],
    "interests": [{"name": "Climbing", "keywords": ["Bouldering", "Outdoors"]}],
    "volunteer": [{"organization": "Code Club", "position": "Mentor"}],
    "publications": [],
    "references": [],
    "meta": {
        "version": "v1.0.0",
        "latexy": {
            "sectionOrder": ["summary", "skills", "experience"],
            "hiddenSections": ["interests"],
        },
    },
}


def test_import_maps_supported_json_resume_fields_without_flattening():
    structured, warnings = json_resume_interchange_service.from_json_resume(JSON_RESUME)

    assert structured["basics"]["location"] == "Pune, MH, IN"
    assert structured["basics"]["linkedin"] == "https://linkedin.com/in/taylor"
    assert structured["experience"][0] == {
        "id": "work-acme",
        "title": "Staff Engineer",
        "company": "Acme",
        "location": "Remote",
        "start_date": "2022-04",
        "end_date": "",
        "current": True,
        "summary": "Led the platform group.",
        "bullets": ["Reduced p95 latency by 40%"],
        "bullet_ids": ["work-acme-bullet-0"],
        "technologies": ["Python", "Kubernetes"],
    }
    # Legacy JSON Resume imports receive stable element IDs so later edits can
    # retain bullet history without changing the imported content.
    assert structured["experience"][0]["bullet_ids"] == ["work-acme-bullet-0"]
    assert structured["education"][0]["field"] == "Computer Science"
    assert structured["projects"][0]["role"] == "Lead"
    assert structured["certifications"][0]["date"] == "2024-02-10"
    assert structured["languages"][0]["detail"] == "Native"
    assert structured["interests"][0]["detail"] == "Bouldering, Outdoors"
    assert structured["section_order"][:3] == ["summary", "skills", "experience"]
    assert structured["hidden_sections"] == ["interests"]
    assert any("profile" in warning for warning in warnings)
    assert any("volunteer" in warning for warning in warnings)


def test_export_is_versioned_and_round_trips_the_builder_common_subset():
    structured, _ = json_resume_interchange_service.from_json_resume(JSON_RESUME)
    exported = json_resume_interchange_service.to_json_resume(structured)
    round_tripped, warnings = json_resume_interchange_service.from_json_resume(exported)

    assert exported["$schema"] == JSON_RESUME_SCHEMA_URL
    assert exported["meta"]["version"] == "v1.0.0"
    assert "endDate" not in exported["work"][0]
    assert exported["projects"][0]["keywords"] == ["Go"]
    assert exported["certificates"][0]["date"] == "2024-02-10"
    assert round_tripped["experience"] == structured["experience"]
    assert round_tripped["education"] == structured["education"]
    assert round_tripped["projects"] == structured["projects"]
    assert round_tripped["skills"] == structured["skills"]
    assert round_tripped["certifications"] == structured["certifications"]
    assert round_tripped["languages"] == structured["languages"]
    assert warnings == []


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"work": {}}, "must be an array"),
        ({"work": [{"startDate": "April 2024"}]}, "must use YYYY"),
        ({"certificates": [{"date": "2024-02"}]}, "must use YYYY-MM-DD"),
        ({"privateExtension": {}}, "Unsupported top-level"),
        ({"basics": {"emali": "taylor@example.com"}}, "basics.emali"),
        ({"work": [{"positon": "Engineer"}]}, r"work\[0\].positon"),
        ({"skills": [{"keywords": [42]}]}, "must be a string"),
    ],
)
def test_import_rejects_malformed_or_non_v1_shapes(payload, message):
    with pytest.raises(ValueError, match=message):
        json_resume_interchange_service.from_json_resume(payload)


def test_export_rejects_builder_dates_that_cannot_satisfy_the_schema():
    with pytest.raises(ValueError, match="must use YYYY"):
        json_resume_interchange_service.to_json_resume(
            {
                "experience": [
                    {
                        "id": "work-1",
                        "title": "Engineer",
                        "company": "Acme",
                        "start_date": "Spring 2024",
                    }
                ]
            }
        )
