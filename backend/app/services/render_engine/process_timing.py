"""Observe child exit independently of log/event drainage."""
from __future__ import annotations

import threading
import time
from typing import Any

from ...core.engine_observability import record_phase


class ProcessTiming:
    """Times observed Popen exit (Docker CLI exit in sandbox deployments).

    An independent wait observes exit while the caller drains stdout and flushes
    buffered events. This measures scheduler-observed exit, not kernel timestamps
    or browser time-to-visible-PDF. No request data enters metric labels.
    """
    def __init__(self, process: Any):
        self.process = process
        self.started = time.monotonic()
        self.exited = None
        self.thread = threading.Thread(target=self._wait, daemon=True, name="render-exit-timing")
        self.thread.start()

    def _wait(self):
        try:
            self.process.wait()
            engine_exit = getattr(self.process, "engine_exit_at", None)
            # Modal wait also copies bounded outputs. Attribute that transport
            # time to drainage, using the SDK-observed engine exit separately.
            self.exited = engine_exit if type(engine_exit) in (int, float) else time.monotonic()
        except Exception:
            # Instrumentation cannot change a render's outcome.
            return

    def finish(self):
        drained = time.monotonic()
        self.thread.join(timeout=0.05)
        if self.exited is not None:
            outcome = "success" if self.process.returncode == 0 else "error"
            record_phase("tex_process", max(0.0, self.exited - self.started), outcome)
            record_phase("output_drain", max(0.0, drained - self.exited), outcome)
