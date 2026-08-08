"""Scheduled tasks must never run KEYS against production Redis.

KEYS is O(N) over the whole keyspace and blocks the server for its entire
duration, so every other client waits — the API's job-state reads, the quota
meter (which fails closed), rate limiting, sessions. Scheduling these tasks on
Modal in #998 therefore made production hang every five minutes: compiles,
previews and PDF downloads all timed out while Redis was blocked, and the
health check's own next call hung, compounding it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CLEANUP = Path(__file__).resolve().parents[1] / "app" / "workers" / "cleanup_worker.py"
SOURCE = CLEANUP.read_text(encoding="utf-8")


def test_no_blocking_keys_call_in_cleanup_worker():
    """Every scheduled task in this module runs against production Redis."""
    offenders = [
        line.strip()
        for line in SOURCE.splitlines()
        if re.search(r"\.keys\(", line) and not line.strip().startswith("#")
    ]
    assert not offenders, (
        "KEYS blocks the whole Redis server; use the SCAN helper instead: "
        f"{offenders}"
    )


def test_scan_helper_pages_to_completion():
    """The helper must drain the cursor, not return only the first page."""
    from app.workers.cleanup_worker import _scan_job_state_keys

    class FakeRedis:
        def __init__(self):
            self.calls = 0

        def scan(self, cursor=0, match=None, count=None):
            self.calls += 1
            # Two pages, then the terminating zero cursor.
            if cursor == 0:
                return 1, [b"latexy:job:a:state"]
            return 0, [b"latexy:job:b:state"]

    fake = FakeRedis()
    keys = _scan_job_state_keys(fake)
    assert fake.calls == 2, "stopped before the cursor came back to zero"
    assert len(keys) == 2


def test_scan_helper_handles_an_empty_keyspace():
    from app.workers.cleanup_worker import _scan_job_state_keys

    class Empty:
        def scan(self, cursor=0, match=None, count=None):
            return 0, []

    assert _scan_job_state_keys(Empty()) == []


@pytest.mark.parametrize(
    "job_id",
    ["health_check_abc", "cleanup_abc", "job_cleanup_abc"],
)
def test_internal_probe_jobs_are_not_reaped_as_user_work(job_id):
    """These are synthetic ids published by the probes themselves.

    Treating them as stuck user jobs filled production logs with "marking
    failed" for work nobody submitted.
    """
    assert job_id.startswith(("health_check_", "cleanup_", "job_cleanup_"))
    assert 'job_id_to_check.startswith(("health_check_", "cleanup_", "job_cleanup_"))' in SOURCE
