"""Deadline and cancellation monitoring for streaming child processes."""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable
from typing import Literal, Optional

StopReason = Literal["timeout", "cancelled"]


class ProcessWatchdog:
    """Kill a process when its deadline expires or cancellation is requested.

    Reading ``Popen.stdout`` line by line blocks when a child is alive but silent.
    Consequently, checks placed inside that loop cannot enforce a deadline.  This
    small daemon monitor is independent of child output and makes those streaming
    loops bounded while leaving log handling in the calling thread.
    """

    def __init__(
        self,
        process: subprocess.Popen,
        *,
        timeout: Optional[float],
        is_cancelled: Optional[Callable[[], bool]] = None,
        poll_interval: float = 0.1,
    ) -> None:
        self._process = process
        self._timeout = timeout
        self._is_cancelled = is_cancelled
        self._poll_interval = max(0.01, poll_interval)
        self._started_at = time.monotonic()
        self._stop = threading.Event()
        self._reason: Optional[StopReason] = None
        self._thread = threading.Thread(
            target=self._monitor,
            name=f"process-watchdog:{getattr(process, 'pid', 'unknown')}",
            daemon=True,
        )

    def start(self) -> "ProcessWatchdog":
        self._thread.start()
        return self

    @property
    def reason(self) -> Optional[StopReason]:
        return self._reason

    def stop(self) -> Optional[StopReason]:
        self._stop.set()
        self._thread.join(timeout=self._poll_interval * 2 + 0.1)
        return self._reason

    def _monitor(self) -> None:
        while not self._stop.wait(self._poll_interval):
            if self._is_cancelled is not None and self._is_cancelled():
                self._terminate("cancelled")
                return
            if (
                self._timeout is not None
                and time.monotonic() - self._started_at >= self._timeout
            ):
                self._terminate("timeout")
                return

    def _terminate(self, reason: StopReason) -> None:
        self._reason = reason
        try:
            self._process.kill()
        except (OSError, ProcessLookupError):
            # The child may have exited between the last stdout read and this check.
            return

