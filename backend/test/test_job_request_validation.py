import pytest
from pydantic import ValidationError

from app.api.analytics_routes import EventTrackingRequest
from app.api.ats_routes import ATSScoreRequest, DeepAnalyzeRequest
from app.api.job_routes import BatchTailorRequest, JobSubmissionRequest


def _valid_job(**overrides):
    return JobSubmissionRequest(
        job_type="combined",
        latex_content="resume",
        **overrides,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"device_fingerprint": "x" * 256},
        {"job_description": "x" * 20_001},
        {"custom_instructions": "x" * 10_001},
        {"target_sections": ["x"] * 21},
        {"target_sections": ["x" * 201]},
        {"emphasize": [" "]},
        {"metadata": {str(index): index for index in range(21)}},
        {"model": "x" * 201},
    ],
)
def test_job_submission_rejects_oversized_nested_inputs(overrides):
    with pytest.raises(ValidationError):
        _valid_job(**overrides)


def test_job_submission_rejects_unknown_optimization_mode():
    with pytest.raises(ValidationError):
        _valid_job(optimization_level="extreme")


def test_batch_tailor_rejects_malformed_resume_id_before_database():
    with pytest.raises(ValidationError):
        BatchTailorRequest(
            resume_id="not-a-uuid",
            jobs=[
                {
                    "company_name": "Acme",
                    "role_title": "Engineer",
                    "job_description": "Build things",
                }
            ],
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ATSScoreRequest(latex_content="resume", device_fingerprint="x" * 256),
        lambda: DeepAnalyzeRequest(latex_content="x" * 100, device_fingerprint="x" * 256),
        lambda: EventTrackingRequest(event_type="view", device_fingerprint="x" * 256),
    ],
)
def test_database_backed_device_fingerprints_match_column_width(factory):
    with pytest.raises(ValidationError):
        factory()
