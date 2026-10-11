"""
Pydantic event models for the Latexy event-driven architecture.

All events published by Celery workers and forwarded by the EventBusManager
to WebSocket clients conform to these schemas.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, StrictInt

# ------------------------------------------------------------------ #
#  Base                                                               #
# ------------------------------------------------------------------ #


class BaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    timestamp: float = Field(default_factory=time.time)
    sequence: int = 0


# ------------------------------------------------------------------ #
#  Job lifecycle events                                               #
# ------------------------------------------------------------------ #


class JobQueuedEvent(BaseEvent):
    type: Literal["job.queued"] = "job.queued"
    job_type: str
    user_id: Optional[str] = None
    estimated_seconds: int = 60


class JobStartedEvent(BaseEvent):
    type: Literal["job.started"] = "job.started"
    worker_id: str
    stage: str


class JobProgressEvent(BaseEvent):
    type: Literal["job.progress"] = "job.progress"
    percent: int
    stage: str
    message: str


class JobCompletedEvent(BaseEvent):
    type: Literal["job.completed"] = "job.completed"
    pdf_job_id: str
    # None when the job never ran ATS scoring (e.g. a plain compile with no
    # job description) — the client must show a neutral "no score yet" state,
    # not a fake 0.0/100. See latex_worker.py / llm_worker.py.
    ats_score: Optional[float] = None
    ats_details: Optional[Dict[str, Any]] = None
    changes_made: List[Dict[str, Any]]
    compilation_time: float
    optimization_time: float
    tokens_used: int
    page_count: Optional[int] = None


class JobFailedEvent(BaseEvent):
    type: Literal["job.failed"] = "job.failed"
    stage: str
    error_code: str
    error_message: str
    retryable: bool


class JobCancelledEvent(BaseEvent):
    type: Literal["job.cancelled"] = "job.cancelled"


class ArtifactReadyEvent(BaseEvent):
    """A checked preview artifact, independent of terminal/export acceptance."""

    type: Literal["artifact.ready"] = "artifact.ready"
    artifact_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    render_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    pdf_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    settings_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    pdf_size: StrictInt = Field(gt=0)
    owner_epoch: StrictInt = Field(gt=0)
    content_revision: Optional[StrictInt] = Field(default=None, ge=0)
    document_id: Optional[str] = None
    run_id: Optional[str] = None
    branch: Literal["draft", "candidate"]
    compiler: Literal["pdflatex", "xelatex", "lualatex"]
    page_count: Optional[StrictInt] = Field(default=None, gt=0)
    preview_url: str
    geometry_url: Optional[str] = None


class SemanticEvent(BaseEvent):
    run_id: str
    document_id: str
    content_revision: StrictInt = Field(ge=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    branch: Literal["candidate"] = "candidate"


class ContextReadyEvent(SemanticEvent):
    type: Literal["context.ready"] = "context.ready"
    coverage: List[Dict[str, Any]]
    requirements_cache_hit: bool
    effort: Literal["quick", "standard", "deep"]
    budget_policy: Dict[str, Any]


class SectionReadyEvent(SemanticEvent):
    type: Literal["section.ready"] = "section.ready"
    section: str
    candidate_count: StrictInt = Field(ge=0)


class PatchReadyEvent(SemanticEvent):
    type: Literal["patch.ready"] = "patch.ready"
    patch: Dict[str, Any]
    provisional: bool = False


class ReviewReadyEvent(SemanticEvent):
    type: Literal["review.ready"] = "review.ready"
    patch_count: StrictInt = Field(ge=0)
    warnings: List[str]
    missing_evidence: List[str]
    status: Literal["completed", "partial"]
    final_patch_ids: List[str] = Field(default_factory=list)
    rejected_patch_ids: List[str] = Field(default_factory=list)


# ------------------------------------------------------------------ #
#  Streaming events                                                   #
# ------------------------------------------------------------------ #


class LLMTokenEvent(BaseEvent):
    type: Literal["llm.token"] = "llm.token"
    token: str


class LLMStreamCompleteEvent(BaseEvent):
    type: Literal["llm.complete"] = "llm.complete"
    full_content: str
    tokens_total: int


class LogLineEvent(BaseEvent):
    type: Literal["log.line"] = "log.line"
    source: str
    line: str
    is_error: bool


# ------------------------------------------------------------------ #
#  ATS deep analysis event (Layer 2)                                  #
# ------------------------------------------------------------------ #


class ATSDeepCompleteEvent(BaseEvent):
    type: Literal["ats.deep_complete"] = "ats.deep_complete"
    overall_score: float
    overall_feedback: str
    sections: List[Dict[str, Any]]
    ats_compatibility: Dict[str, Any]
    job_match: Optional[Dict[str, Any]] = None
    tokens_used: int
    analysis_time: float
    multi_dim_scores: Optional[Dict[str, float]] = None


# ------------------------------------------------------------------ #
#  PDF text extraction event (ATS pre-flight)                        #
# ------------------------------------------------------------------ #


class PDFTextExtractedEvent(BaseEvent):
    type: Literal["job.pdf_extracted"] = "job.pdf_extracted"
    text: str
    page_count: int


# ------------------------------------------------------------------ #
#  System events                                                      #
# ------------------------------------------------------------------ #


class HeartbeatEvent(BaseEvent):
    type: Literal["sys.heartbeat"] = "sys.heartbeat"
    server_time: float = Field(default_factory=time.time)


class SystemErrorEvent(BaseEvent):
    type: Literal["sys.error"] = "sys.error"
    message: str


# ------------------------------------------------------------------ #
#  Discriminated union for deserialization                            #
# ------------------------------------------------------------------ #

AnyEvent = Union[
    JobQueuedEvent,
    JobStartedEvent,
    JobProgressEvent,
    JobCompletedEvent,
    JobFailedEvent,
    JobCancelledEvent,
    ArtifactReadyEvent,
    ContextReadyEvent,
    SectionReadyEvent,
    PatchReadyEvent,
    ReviewReadyEvent,
    LLMTokenEvent,
    LLMStreamCompleteEvent,
    LogLineEvent,
    ATSDeepCompleteEvent,
    PDFTextExtractedEvent,
    HeartbeatEvent,
    SystemErrorEvent,
]


# ------------------------------------------------------------------ #
#  Helper: map event type string → status string                     #
# ------------------------------------------------------------------ #

_STATUS_MAP: Dict[str, str] = {
    "job.queued": "queued",
    "job.started": "processing",
    "job.progress": "processing",
    "job.completed": "completed",
    "job.failed": "failed",
    "job.cancelled": "cancelled",
    "ats.deep_complete": "completed",
    "job.pdf_extracted": "processing",
}


def status_from_event_type(event_type: str) -> str:
    return _STATUS_MAP.get(event_type, "processing")
