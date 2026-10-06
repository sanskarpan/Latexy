"""Validate untrusted provider output before presenting a scored assessment."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictStr

Score = Annotated[float, Field(strict=True, ge=0, le=100, allow_inf_nan=False)]
Text = Annotated[StrictStr, Field(max_length=8000)]
Signal = Annotated[StrictStr, Field(max_length=2000)]
Signals = Annotated[list[Signal], Field(max_length=50)]


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class DeepATSSection(_ResponseModel):
    name: Annotated[StrictStr, Field(min_length=1, max_length=160)]
    score: Score
    strengths: Signals
    improvements: Signals
    rewrite_suggestion: Text | None = None


class DeepATSCompatibility(_ResponseModel):
    score: Score
    issues: Signals
    keyword_gaps: Signals


class DeepATSJobMatch(_ResponseModel):
    score: Score
    matched_requirements: Signals
    missing_requirements: Signals
    recommendation: Text


class DeepATSResponse(_ResponseModel):
    overall_score: Score
    overall_feedback: Text
    sections: Annotated[list[DeepATSSection], Field(max_length=30)]
    ats_compatibility: DeepATSCompatibility
    job_match: DeepATSJobMatch | None = None
