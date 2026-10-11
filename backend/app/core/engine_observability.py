"""Bounded phase metrics: durations overlap and must never be added blindly."""
from __future__ import annotations

import logging
import math
import time
from contextlib import contextmanager

from prometheus_client import Histogram

from .tracing import traced

logger = logging.getLogger(__name__)

PHASES = frozenset({
    "admission", "dispatch_wait", "dispatch_call", "worker_initialization",
    "queue_wait", "source_prepare", "cache_lookup", "tex_process", "output_drain",
    "event_publication", "artifact_storage", "artifact_download", "geometry_inspection", "finalization",
    "model_planning", "model_call", "patch_validation", "quality_review",
})
OUTCOMES = frozenset({"success", "error", "cancelled", "cache_hit", "cache_miss"})
ENGINE_PHASE_SECONDS = Histogram(
    "latexy_engine_phase_seconds",
    "Resume-engine phase durations; overlapping phase observations are not additive.",
    ["phase", "outcome"],
    buckets=(.001, .005, .01, .025, .05, .1, .25, .5, .75, 1, 2, 5, 15, 40, 90, 300),
)


def record_phase(phase: str, seconds: float, outcome: str = "success") -> None:
    """Ignore invalid observations rather than fail the user operation.

    Labels are fixed categories only. Source, user, job, document and provider
    diagnostics are never metric labels. Use existing trace context to correlate.
    """
    if phase not in PHASES or outcome not in OUTCOMES:
        return
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return
    if not math.isfinite(seconds) or seconds < 0:
        return
    ENGINE_PHASE_SECONDS.labels(phase=phase, outcome=outcome).observe(seconds)
    # Modal workers may not have a scraped metrics endpoint. Keep the same
    # bounded diagnostics for direct observations (queue/process/admission) as
    # for spans; callers never supply request data or identifiers here.
    if seconds >= .25:
        logger.info("resume_engine_slow_phase", extra={"phase": phase, "outcome": outcome, "latency_seconds": seconds})


class PhaseTimer:
    """Finish a phase once across stateful worker success/early-return paths."""

    def __init__(self, phase: str):
        self.phase = phase
        self.started = time.perf_counter()
        self.finished = False

    def finish(self, outcome: str = "success") -> None:
        if self.finished:
            return
        self.finished = True
        record_phase(self.phase, time.perf_counter() - self.started, outcome)


@contextmanager
def engine_span(phase: str):
    """Measure monotonic wall duration and attach a privacy-safe OTEL span."""
    start = time.perf_counter()
    outcome = "success"
    try:
        with traced(f"resume_engine.{phase if phase in PHASES else 'unknown'}"):
            yield
    except BaseException as exc:
        outcome = "cancelled" if isinstance(exc, (KeyboardInterrupt, SystemExit)) or type(exc).__name__ == "CancelledError" else "error"
        raise
    finally:
        duration = time.perf_counter() - start
        record_phase(phase, duration, outcome)
