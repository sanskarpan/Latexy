"""
Unit tests for cleanup_worker:
  - cleanup_temp_files_task   (temp file deletion + space accounting)
  - cleanup_expired_jobs_task (Redis job record expiry)
  - health_check_task         (system health metrics)

All Redis / async I/O is mocked — no running Redis required.
Filesystem tests use pytest's tmp_path for isolation.
Tasks are invoked via Celery's task.apply() which runs synchronously.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.celery_app import celery_app
from app.workers.cleanup_worker import (
    cleanup_expired_jobs_task,
    cleanup_temp_files_task,
    health_check_task,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def eager_celery():
    """Run Celery tasks synchronously in the current process."""
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False


@pytest.fixture
def mock_jsm():
    """Patch job_status_manager with async no-ops."""
    with patch("app.workers.cleanup_worker.job_status_manager") as m:
        m.set_job_status = AsyncMock(return_value=True)
        m.set_job_progress = AsyncMock(return_value=True)
        m.set_job_result = AsyncMock(return_value=True)
        m.get_active_jobs = AsyncMock(return_value=[])
        m.get_job_status = AsyncMock(return_value=None)
        m.delete_job_data = AsyncMock(return_value=True)
        yield m


@pytest.fixture
def mock_rm():
    """Patch redis_manager with a healthy health_check stub."""
    with patch("app.workers.cleanup_worker.redis_manager") as m:
        m.health_check = AsyncMock(return_value={"redis": True, "cache": True})
        yield m


# ── File helpers ──────────────────────────────────────────────────────────────


def _old_file(path: Path, age_hours: float = 48) -> Path:
    """Create a file and backdate its mtime so it falls before the cutoff."""
    path.write_text("test content")
    old_ts = time.time() - age_hours * 3600
    os.utime(path, (old_ts, old_ts))
    return path


def _new_file(path: Path) -> Path:
    """Create a file with current mtime (never qualifies for deletion)."""
    path.write_text("fresh content")
    return path


def _disk_usage(free_gb: float, total_gb: float = 100.0) -> MagicMock:
    """Return a shutil.disk_usage-compatible namedtuple mock."""
    du = MagicMock()
    du.free = int(free_gb * 1024 ** 3)
    du.total = int(total_gb * 1024 ** 3)
    return du


# ── cleanup_temp_files_task ───────────────────────────────────────────────────


class TestCleanupTempFilesTask:

    def _run(self, mock_jsm, tmp_path, max_age_hours: int = 24, **kwargs):
        return cleanup_temp_files_task.apply(
            kwargs={
                "max_age_hours": max_age_hours,
                "target_directory": str(tmp_path),
                **kwargs,
            }
        ).result

    # ── return value shape ────────────────────────────────────────────────────

    def test_result_has_required_keys(self, mock_jsm, tmp_path):
        result = self._run(mock_jsm, tmp_path)
        required = {
            "success", "task_id", "job_id", "message",
            "files_deleted", "directories_deleted", "space_freed",
            "space_freed_mb", "max_age_hours", "target_directory",
            "errors", "error_count", "completed_at",
        }
        assert required <= result.keys()

    def test_task_id_is_non_empty_string(self, mock_jsm, tmp_path):
        result = self._run(mock_jsm, tmp_path)
        assert isinstance(result["task_id"], str) and result["task_id"]

    def test_job_id_prefixed_with_cleanup(self, mock_jsm, tmp_path):
        result = self._run(mock_jsm, tmp_path)
        assert result["job_id"].startswith("cleanup_")

    def test_error_count_matches_errors_list(self, mock_jsm, tmp_path):
        result = self._run(mock_jsm, tmp_path)
        assert result["error_count"] == len(result["errors"])

    # ── nonexistent / empty directories ──────────────────────────────────────

    def test_nonexistent_directory_returns_success_zero_deleted(self, mock_jsm, tmp_path):
        missing = str(tmp_path / "does_not_exist")
        result = cleanup_temp_files_task.apply(
            kwargs={"max_age_hours": 24, "target_directory": missing}
        ).result
        assert result["success"] is True
        assert result["files_deleted"] == 0
        assert result["space_freed"] == 0

    def test_empty_directory_returns_zero_deleted(self, mock_jsm, tmp_path):
        result = self._run(mock_jsm, tmp_path)
        assert result["success"] is True
        assert result["files_deleted"] == 0
        assert result["space_freed"] == 0

    # ── file age filtering ────────────────────────────────────────────────────

    def test_old_files_are_deleted(self, mock_jsm, tmp_path):
        _old_file(tmp_path / "old1.tex", age_hours=48)
        _old_file(tmp_path / "old2.pdf", age_hours=48)
        result = self._run(mock_jsm, tmp_path)
        assert result["files_deleted"] == 2
        assert not (tmp_path / "old1.tex").exists()
        assert not (tmp_path / "old2.pdf").exists()

    def test_new_files_are_preserved(self, mock_jsm, tmp_path):
        _new_file(tmp_path / "fresh.tex")
        result = self._run(mock_jsm, tmp_path)
        assert result["files_deleted"] == 0
        assert (tmp_path / "fresh.tex").exists()

    def test_mixed_ages_deletes_only_old(self, mock_jsm, tmp_path):
        _old_file(tmp_path / "old.tex", age_hours=48)
        _new_file(tmp_path / "new.tex")
        result = self._run(mock_jsm, tmp_path)
        assert result["files_deleted"] == 1
        assert not (tmp_path / "old.tex").exists()
        assert (tmp_path / "new.tex").exists()

    def test_custom_max_age_respected(self, mock_jsm, tmp_path):
        """File 2 hours old with max_age=1h → deleted."""
        _old_file(tmp_path / "slightly_old.tex", age_hours=2)
        result = self._run(mock_jsm, tmp_path, max_age_hours=1)
        assert result["files_deleted"] == 1

    def test_files_within_max_age_preserved(self, mock_jsm, tmp_path):
        """File 1 hour old with max_age=2h → preserved."""
        _old_file(tmp_path / "recent.tex", age_hours=1)
        result = self._run(mock_jsm, tmp_path, max_age_hours=2)
        assert result["files_deleted"] == 0
        assert (tmp_path / "recent.tex").exists()

    # ── space accounting ──────────────────────────────────────────────────────

    def test_space_freed_matches_file_size(self, mock_jsm, tmp_path):
        content = b"x" * 1024  # exactly 1 KB
        f = tmp_path / "old.bin"
        f.write_bytes(content)
        os.utime(f, (time.time() - 48 * 3600,) * 2)
        result = self._run(mock_jsm, tmp_path)
        assert result["space_freed"] == 1024

    def test_space_freed_mb_is_consistent(self, mock_jsm, tmp_path):
        f = tmp_path / "big.bin"
        f.write_bytes(b"y" * (2 * 1024 * 1024))  # 2 MB
        os.utime(f, (time.time() - 48 * 3600,) * 2)
        result = self._run(mock_jsm, tmp_path)
        expected = round(result["space_freed"] / (1024 * 1024), 2)
        assert result["space_freed_mb"] == expected

    # ── directory handling ────────────────────────────────────────────────────

    def test_old_empty_directory_is_removed(self, mock_jsm, tmp_path):
        subdir = tmp_path / "old_empty"
        subdir.mkdir()
        os.utime(subdir, (time.time() - 48 * 3600,) * 2)
        result = self._run(mock_jsm, tmp_path)
        assert result["directories_deleted"] >= 1
        assert not subdir.exists()

    def test_directory_with_new_files_not_removed(self, mock_jsm, tmp_path):
        subdir = tmp_path / "active_job"
        subdir.mkdir()
        _new_file(subdir / "resume.tex")
        self._run(mock_jsm, tmp_path)
        assert subdir.exists()

    def test_nested_old_files_deleted(self, mock_jsm, tmp_path):
        subdir = tmp_path / "job_xyz"
        subdir.mkdir()
        _old_file(subdir / "resume.pdf", age_hours=48)
        result = self._run(mock_jsm, tmp_path)
        assert result["files_deleted"] >= 1

    # ── Redis interaction ─────────────────────────────────────────────────────

    def test_set_job_status_called_at_least_twice(self, mock_jsm, tmp_path):
        """Initial 'processing' + final 'completed' status writes."""
        self._run(mock_jsm, tmp_path)
        assert mock_jsm.set_job_status.call_count >= 2

    def test_set_job_result_called_once(self, mock_jsm, tmp_path):
        self._run(mock_jsm, tmp_path)
        mock_jsm.set_job_result.assert_called_once()

    # ── failure path ──────────────────────────────────────────────────────────

    def test_redis_failure_returns_error_dict(self, tmp_path):
        """If the initial Redis status write fails, task catches it and returns error dict."""
        # Only the FIRST set_job_status call raises; the error-handler's call succeeds.
        call_count = {"n": 0}

        async def _side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Redis down")
            return True

        with patch("app.workers.cleanup_worker.job_status_manager") as m:
            m.set_job_status = AsyncMock(side_effect=_side_effect)
            m.set_job_progress = AsyncMock(return_value=True)
            m.set_job_result = AsyncMock(return_value=True)
            result = cleanup_temp_files_task.apply(
                kwargs={"max_age_hours": 24, "target_directory": str(tmp_path)}
            ).result
        assert result["success"] is False
        assert "error" in result


# ── cleanup_expired_jobs_task ─────────────────────────────────────────────────


class TestCleanupExpiredJobsTask:

    _OLD = time.time() - 48 * 3600   # 48 h ago — past any reasonable TTL
    _RECENT = time.time() - 1 * 3600  # 1 h ago  — within TTL

    def _run(self, mock_jsm, **kwargs):
        return cleanup_expired_jobs_task.apply(
            kwargs={"max_age_hours": 24, **kwargs}
        ).result

    # ── return value shape ────────────────────────────────────────────────────

    def test_result_has_required_keys(self, mock_jsm):
        result = self._run(mock_jsm)
        required = {
            "success", "task_id", "job_id", "message",
            "jobs_cleaned", "total_jobs_scanned",
            "max_age_hours", "batch_size", "errors", "error_count", "completed_at",
        }
        assert required <= result.keys()

    def test_job_id_prefixed_with_job_cleanup(self, mock_jsm):
        result = self._run(mock_jsm)
        assert result["job_id"].startswith("job_cleanup_")

    def test_error_count_matches_errors_list(self, mock_jsm):
        result = self._run(mock_jsm)
        assert result["error_count"] == len(result["errors"])

    # ── empty queue ───────────────────────────────────────────────────────────

    def test_no_active_jobs_returns_zero(self, mock_jsm):
        mock_jsm.get_active_jobs = AsyncMock(return_value=[])
        result = self._run(mock_jsm)
        assert result["success"] is True
        assert result["jobs_cleaned"] == 0
        assert result["total_jobs_scanned"] == 0

    # ── terminal state + expired → cleaned ───────────────────────────────────

    def test_completed_expired_job_deleted(self, mock_jsm):
        mock_jsm.get_active_jobs = AsyncMock(return_value=["job-done"])
        mock_jsm.get_job_status = AsyncMock(
            return_value={"status": "completed", "updated_at": self._OLD}
        )
        result = self._run(mock_jsm)
        assert result["jobs_cleaned"] == 1
        mock_jsm.delete_job_data.assert_called_once_with("job-done")

    def test_failed_expired_job_deleted(self, mock_jsm):
        mock_jsm.get_active_jobs = AsyncMock(return_value=["job-fail"])
        mock_jsm.get_job_status = AsyncMock(
            return_value={"status": "failed", "updated_at": self._OLD}
        )
        result = self._run(mock_jsm)
        assert result["jobs_cleaned"] == 1

    def test_cancelled_expired_job_deleted(self, mock_jsm):
        mock_jsm.get_active_jobs = AsyncMock(return_value=["job-cancel"])
        mock_jsm.get_job_status = AsyncMock(
            return_value={"status": "cancelled", "updated_at": self._OLD}
        )
        result = self._run(mock_jsm)
        assert result["jobs_cleaned"] == 1

    # ── non-terminal states never cleaned ────────────────────────────────────

    def test_processing_job_never_cleaned(self, mock_jsm):
        mock_jsm.get_active_jobs = AsyncMock(return_value=["job-proc"])
        mock_jsm.get_job_status = AsyncMock(
            return_value={"status": "processing", "updated_at": self._OLD}
        )
        result = self._run(mock_jsm)
        assert result["jobs_cleaned"] == 0
        mock_jsm.delete_job_data.assert_not_called()

    def test_queued_job_never_cleaned(self, mock_jsm):
        mock_jsm.get_active_jobs = AsyncMock(return_value=["job-q"])
        mock_jsm.get_job_status = AsyncMock(
            return_value={"status": "queued", "updated_at": self._OLD}
        )
        result = self._run(mock_jsm)
        assert result["jobs_cleaned"] == 0

    # ── recent terminal jobs preserved ────────────────────────────────────────

    def test_recent_completed_job_not_cleaned(self, mock_jsm):
        mock_jsm.get_active_jobs = AsyncMock(return_value=["job-fresh"])
        mock_jsm.get_job_status = AsyncMock(
            return_value={"status": "completed", "updated_at": self._RECENT}
        )
        result = self._run(mock_jsm)
        assert result["jobs_cleaned"] == 0
        mock_jsm.delete_job_data.assert_not_called()

    # ── edge: no status data ──────────────────────────────────────────────────

    def test_job_with_no_status_skipped_gracefully(self, mock_jsm):
        mock_jsm.get_active_jobs = AsyncMock(return_value=["ghost"])
        mock_jsm.get_job_status = AsyncMock(return_value=None)
        result = self._run(mock_jsm)
        assert result["success"] is True
        assert result["jobs_cleaned"] == 0

    # ── mixed states ─────────────────────────────────────────────────────────

    def test_mixed_states_cleans_only_expired_terminal(self, mock_jsm):
        status_map = {
            "j-old-done":  {"status": "completed",  "updated_at": self._OLD},
            "j-old-fail":  {"status": "failed",     "updated_at": self._OLD},
            "j-new-done":  {"status": "completed",  "updated_at": self._RECENT},
            "j-running":   {"status": "processing", "updated_at": self._OLD},
        }
        mock_jsm.get_active_jobs = AsyncMock(return_value=list(status_map))
        mock_jsm.get_job_status = AsyncMock(side_effect=lambda jid: status_map[jid])
        result = self._run(mock_jsm)
        assert result["jobs_cleaned"] == 2
        assert result["total_jobs_scanned"] == 4

    # ── batch processing ──────────────────────────────────────────────────────

    def test_all_jobs_scanned_with_small_batch_size(self, mock_jsm):
        jobs = [f"job-{i}" for i in range(15)]
        mock_jsm.get_active_jobs = AsyncMock(return_value=jobs)
        mock_jsm.get_job_status = AsyncMock(
            return_value={"status": "completed", "updated_at": self._OLD}
        )
        result = self._run(mock_jsm, batch_size=5)
        assert result["total_jobs_scanned"] == 15
        assert result["jobs_cleaned"] == 15

    # ── error handling ────────────────────────────────────────────────────────

    def test_get_job_status_error_captured_not_propagated(self, mock_jsm):
        mock_jsm.get_active_jobs = AsyncMock(return_value=["bad-job"])
        mock_jsm.get_job_status = AsyncMock(side_effect=RuntimeError("timeout"))
        result = self._run(mock_jsm)
        assert result["success"] is True          # task-level success despite error
        assert result["error_count"] >= 1
        assert any("bad-job" in e for e in result["errors"])

    def test_partial_errors_dont_abort_remaining_jobs(self, mock_jsm):
        """An error on one job should not prevent other jobs from being processed."""
        mock_jsm.get_active_jobs = AsyncMock(return_value=["bad", "good"])

        def _status(jid):
            if jid == "bad":
                raise RuntimeError("Redis timeout")
            return {"status": "completed", "updated_at": self._OLD}

        mock_jsm.get_job_status = AsyncMock(side_effect=_status)
        result = self._run(mock_jsm)
        assert result["jobs_cleaned"] == 1   # "good" was still cleaned
        assert result["error_count"] == 1    # "bad" produced one error


# ── health_check_task ─────────────────────────────────────────────────────────


class TestHealthCheckTask:

    def _run(self, mock_jsm, mock_rm, *, free_gb=10.0, total_gb=100.0, active_jobs=None):
        du = _disk_usage(free_gb, total_gb)
        mock_jsm.get_active_jobs = AsyncMock(return_value=active_jobs or [])
        with patch("shutil.disk_usage", return_value=du):
            return health_check_task.apply(kwargs={}).result

    # ── return value shape ────────────────────────────────────────────────────

    def test_result_has_required_keys(self, mock_jsm, mock_rm):
        result = self._run(mock_jsm, mock_rm)
        required = {
            "success", "task_id", "job_id", "message",
            "overall_health", "health_issues", "redis_health",
            "disk_usage", "active_jobs_count", "temp_directory", "completed_at",
        }
        assert required <= result.keys()

    def test_job_id_prefixed_with_health_check(self, mock_jsm, mock_rm):
        result = self._run(mock_jsm, mock_rm)
        assert result["job_id"].startswith("health_check_")

    def test_disk_usage_subkeys_present(self, mock_jsm, mock_rm):
        result = self._run(mock_jsm, mock_rm)
        du = result["disk_usage"]
        assert {"free_gb", "total_gb", "used_percent"} <= du.keys()

    def test_disk_used_percent_in_range(self, mock_jsm, mock_rm):
        result = self._run(mock_jsm, mock_rm, free_gb=30.0, total_gb=100.0)
        assert 0 <= result["disk_usage"]["used_percent"] <= 100

    # ── healthy system ────────────────────────────────────────────────────────

    def test_healthy_system_returns_healthy(self, mock_jsm, mock_rm):
        result = self._run(mock_jsm, mock_rm, free_gb=10.0)
        assert result["success"] is True
        assert result["overall_health"] == "healthy"
        assert result["health_issues"] == []

    # ── Redis failure → degraded ──────────────────────────────────────────────

    def test_redis_failure_causes_degraded(self, mock_jsm, mock_rm):
        mock_rm.health_check = AsyncMock(return_value={"redis": False, "cache": True})
        result = self._run(mock_jsm, mock_rm, free_gb=10.0)
        assert result["overall_health"] == "degraded"
        assert any("redis" in issue.lower() for issue in result["health_issues"])

    def test_all_redis_down_causes_degraded(self, mock_jsm, mock_rm):
        mock_rm.health_check = AsyncMock(return_value={"redis": False, "cache": False})
        result = self._run(mock_jsm, mock_rm, free_gb=10.0)
        assert result["overall_health"] == "degraded"

    # ── low disk → degraded ───────────────────────────────────────────────────

    def test_low_disk_causes_degraded(self, mock_jsm, mock_rm):
        result = self._run(mock_jsm, mock_rm, free_gb=0.5)   # 500 MB
        assert result["overall_health"] == "degraded"
        assert any("disk" in issue.lower() for issue in result["health_issues"])

    def test_exactly_1gb_free_not_degraded(self, mock_jsm, mock_rm):
        """Boundary: exactly 1.0 GB uses strict < threshold."""
        result = self._run(mock_jsm, mock_rm, free_gb=1.0)
        disk_issues = [i for i in result["health_issues"] if "disk" in i.lower()]
        assert len(disk_issues) == 0

    # ── high job count → degraded ─────────────────────────────────────────────

    def test_high_job_count_causes_degraded(self, mock_jsm, mock_rm):
        result = self._run(mock_jsm, mock_rm, active_jobs=["j"] * 1001)
        assert result["overall_health"] == "degraded"
        assert any("job" in issue.lower() for issue in result["health_issues"])

    def test_exactly_1000_jobs_not_degraded(self, mock_jsm, mock_rm):
        """Boundary: exactly 1000 uses strict > threshold."""
        result = self._run(mock_jsm, mock_rm, active_jobs=["j"] * 1000)
        job_issues = [i for i in result["health_issues"] if "job" in i.lower()]
        assert len(job_issues) == 0

    # ── multiple issues ───────────────────────────────────────────────────────

    def test_multiple_issues_all_reported(self, mock_jsm, mock_rm):
        mock_rm.health_check = AsyncMock(return_value={"redis": False, "cache": False})
        result = self._run(mock_jsm, mock_rm, free_gb=0.1, active_jobs=["j"] * 1001)
        assert result["overall_health"] == "degraded"
        assert len(result["health_issues"]) >= 2

    # ── active jobs count ─────────────────────────────────────────────────────

    def test_active_jobs_count_matches(self, mock_jsm, mock_rm):
        result = self._run(mock_jsm, mock_rm, active_jobs=["j1", "j2", "j3"])
        assert result["active_jobs_count"] == 3

    # ── Redis interaction ─────────────────────────────────────────────────────

    def test_redis_health_check_called_once(self, mock_jsm, mock_rm):
        self._run(mock_jsm, mock_rm)
        mock_rm.health_check.assert_called_once()

    def test_set_job_status_called_at_least_twice(self, mock_jsm, mock_rm):
        self._run(mock_jsm, mock_rm)
        assert mock_jsm.set_job_status.call_count >= 2

    def test_set_job_result_called_once(self, mock_jsm, mock_rm):
        self._run(mock_jsm, mock_rm)
        mock_jsm.set_job_result.assert_called_once()
