"""Regression tests for silent LaTeX subprocess monitoring."""

from __future__ import annotations

import subprocess
import sys
import threading
import time

from app.utils.process_watchdog import ProcessWatchdog


def _silent_process() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_watchdog_times_out_a_silent_process() -> None:
    process = _silent_process()
    watchdog = ProcessWatchdog(process, timeout=0.05, poll_interval=0.01).start()

    process.wait(timeout=1)
    assert process.stdout is not None
    process.stdout.close()

    assert watchdog.stop() == "timeout"
    assert process.returncode is not None


def test_watchdog_cancels_a_silent_process() -> None:
    process = _silent_process()
    cancelled = threading.Event()
    watchdog = ProcessWatchdog(
        process,
        timeout=10,
        is_cancelled=cancelled.is_set,
        poll_interval=0.01,
    ).start()
    cancelled.set()

    process.wait(timeout=1)
    assert process.stdout is not None
    process.stdout.close()

    assert watchdog.stop() == "cancelled"
    assert process.returncode is not None


def test_stopping_watchdog_leaves_a_running_process_alone() -> None:
    process = _silent_process()
    watchdog = ProcessWatchdog(process, timeout=10, poll_interval=0.01).start()
    try:
        time.sleep(0.03)
        assert watchdog.stop() is None
        assert process.poll() is None
    finally:
        process.kill()
        process.wait(timeout=1)
        assert process.stdout is not None
        process.stdout.close()
