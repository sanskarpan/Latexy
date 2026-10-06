import pytest
from pydantic import ValidationError

from app.api.resume_routes import MergeRequest

FIRST_ID = "00000000-0000-0000-0000-000000000001"
SECOND_ID = "00000000-0000-0000-0000-000000000002"


def test_merge_requires_valid_distinct_resume_ids():
    with pytest.raises(ValidationError):
        MergeRequest(resume_ids=[FIRST_ID, "not-a-uuid"])
    with pytest.raises(ValidationError):
        MergeRequest(resume_ids=[FIRST_ID, FIRST_ID])


def test_merge_rejects_section_source_outside_selected_resumes():
    with pytest.raises(ValidationError):
        MergeRequest(
            resume_ids=[FIRST_ID, SECOND_ID],
            section_choices={"Experience": "00000000-0000-0000-0000-000000000003"},
        )


def test_merge_accepts_selected_section_source():
    request = MergeRequest(
        resume_ids=[FIRST_ID, SECOND_ID],
        section_choices={"Experience": SECOND_ID},
    )
    assert request.section_choices["Experience"] == SECOND_ID

