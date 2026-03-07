"""
Pydantic event models for the Latexy event-driven architecture.

All events published by Celery workers and forwarded by the EventBusManager
to WebSocket clients conform to these schemas.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


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
    job_type: str                               # "combined" | "latex_compilation" | ...
    user_id: Optional[str] = None
    estimated_seconds: int = 60


class JobStartedEvent(BaseEvent):
    type: Literal["job.started"] = "job.started"
    worker_id: str
    stage: str                                  # "llm_optimization" | "latex_compilation" | "ats_scoring"


class JobProgressEvent(BaseEvent):
    type: Literal["job.progress"] = "job.progress"
    percent: int                                # 0 – 100
    stage: str
    message: str


class JobCompletedEvent(BaseEvent):
    type: Literal["job.completed"] = "job.completed"
    pdf_job_id: str                             # same as job_id — use for /download/{pdf_job_id}
    ats_score: float
    ats_details: Dict[str, Any]
    changes_made: List[Dict[str, Any]]
    compilation_time: float
    optimization_time: float
    tokens_used: int


class JobFailedEvent(BaseEvent):
    type: Literal["job.failed"] = "job.failed"
    stage: str
    error_code: str                             # "latex_error" | "llm_error" | "timeout" | "internal"
    error_message: str
    retryable: bool


class JobCancelledEvent(BaseEvent):
    type: Literal["job.cancelled"] = "job.cancelled"


# ------------------------------------------------------------------ #
#  Streaming events                                                   #
# ------------------------------------------------------------------ #

class LLMTokenEvent(BaseEvent):
    type: Literal["llm.token"] = "llm.token"
    token: str                                  # single token delta from OpenAI streaming


class LLMStreamCompleteEvent(BaseEvent):
    type: Literal["llm.complete"] = "llm.complete"
    full_content: str                           # complete assembled LaTeX
    tokens_total: int


class LogLineEvent(BaseEvent):
    type: Literal["log.line"] = "log.line"
    source: str                                 # "pdflatex" | "lualatex"
    line: str
    is_error: bool


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
    LLMTokenEvent,
    LLMStreamCompleteEvent,
    LogLineEvent,
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
}


def status_from_event_type(event_type: str) -> str:
    return _STATUS_MAP.get(event_type, "processing")
