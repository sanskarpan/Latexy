from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.resume_builder_service import resume_builder_service
from app.services.resume_validation_service import (
    locate_json_path,
    pydantic_validation_issues,
    value_error_issue,
)

JSON_SOURCE = """{
  "basics": {
    "name": "Taylor"
  },
  "work": [
    {
      "name": "Acme",
      "startDate": "April 2024"
    }
  ]
}
"""


def test_semantic_json_path_has_exact_source_line_and_column():
    assert locate_json_path(JSON_SOURCE, "work[0].startDate") == (8, 7)
    issue = value_error_issue(
        ValueError("JSON Resume field 'work[0].startDate' must use YYYY"),
        JSON_SOURCE,
    )
    assert issue == {
        "path": "work[0].startDate",
        "message": "JSON Resume field 'work[0].startDate' must use YYYY",
        "line": 8,
        "column": 7,
    }


@pytest.mark.parametrize(
    "payload, expected_path",
    [
        ({"basics": {"nickname": "T"}}, "structured_content.basics.nickname"),
        (
            {"experience": [{"id": "work-1", "current": 1}]},
            "structured_content.experience[0].current",
        ),
        ({"skills": [{"id": "skills-1", "keywords": [42]}]}, "structured_content.skills[0].keywords[0]"),
    ],
)
def test_incoming_builder_schema_rejects_unknown_or_coerced_values(payload, expected_path):
    with pytest.raises(ValidationError) as caught:
        resume_builder_service.normalize(payload)

    issues = pydantic_validation_issues(caught.value, prefix=("structured_content",))
    assert issues[0]["path"] == expected_path
