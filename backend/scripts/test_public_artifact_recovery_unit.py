"""Standalone artifact-recovery tests that do not load pytest infrastructure.

Run directly with the backend venv Python.  A fake config module is installed
before application imports so Pydantic never reads either workspace .env file.
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


class _FakeSettings:
    def __getattr__(self, name: str):
        if name == "ALLOWED_LATEX_COMPILERS":
            return ["pdflatex"]
        if name == "DEFAULT_LATEX_COMPILER":
            return "pdflatex"
        if name == "TEMP_DIR":
            return Path(tempfile.gettempdir()) / "latexy-public-artifact-unit"
        if name == "API_KEY_ENCRYPTION_KEY":
            return "eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg="
        if name.startswith(("is_", "get_", "resolve_")):
            return lambda *args, **kwargs: False
        if name == "LOG_LEVEL":
            return "INFO"
        if name in {"DATABASE_URL", "MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"}:
            return ""
        if name.endswith(("_ENABLED", "_DEBUG")) or name.startswith("ENABLE_"):
            return False
        if name.endswith(("_ORIGINS", "_COMPILERS", "_KEYS")):
            return []
        if name.endswith(("_LIMIT", "_TIMEOUT", "_SIZE", "_PORT", "_POOL_SIZE", "_OVERFLOW")):
            return 0
        if name.endswith(("_URL", "_KEY", "_SECRET", "_MODEL", "_MODE", "_ENVIRONMENT")):
            return ""
        return None


class _ConfigModule(types.ModuleType):
    def __getattr__(self, name):
        if name == "QUOTA_DIMENSIONS":
            return {}
        if name.startswith(("get_", "resolve_", "is_")):
            return lambda *args, **kwargs: None
        raise AttributeError(name)


fake_config = _ConfigModule("app.core.config")
fake_config.settings = _FakeSettings()
sys.modules["app.core.config"] = fake_config

from sqlalchemy.dialects import postgresql  # noqa: E402

from app.api import public_api_routes  # noqa: E402
from app.database.models import Compilation, JobFinalization  # noqa: E402
from app.services import job_result_recovery  # noqa: E402

USER_ID = "10000000-0000-4000-8000-000000000001"
JOB_ID = "30000000-0000-4000-8000-000000000003"
COMPILATION_ID = "20000000-0000-4000-8000-000000000002"
PDF_PATH = f"compilations/{JOB_ID}/finalization-0123456789abcdef0123456789abcdef.pdf"


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect())).lower()


class _RecoverySession:
    """Small SQL-aware fake: return rows only when the query predicates allow them."""

    def __init__(self, finalization, compilation):
        self.finalization = finalization
        self.compilation = compilation
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        sql = _sql(statement)
        params = statement.compile(dialect=postgresql.dialect()).params
        if "job_finalizations." in sql:
            if self.finalization.job_id not in params.values() or self.finalization.user_id not in params.values():
                return None
            return self.finalization
        if "compilations." in sql:
            if "compilations.artifact_accepted is true" not in sql:
                return None
            if "compilations.job_id" not in sql or "compilations.user_id" not in sql:
                return None
            row = self.compilation
            if row is None:
                return None
            if (row.job_id not in params.values() or row.user_id not in params.values()
                    or row.status != "completed"):
                return None
            if row.artifact_accepted is not True:
                return None
            if self.finalization.compilation_id and row.id != self.finalization.compilation_id:
                return None
            return row
        raise AssertionError("Unexpected query")


class _AdmissionSession:
    def __init__(self):
        self.rows = []
        self.deleted = []

    def add(self, row):
        self.rows.append(row)

    async def flush(self):
        for row in self.rows:
            if isinstance(row, Compilation) and row.id is None:
                row.id = str(uuid.uuid4())
                row.artifact_branch = row.artifact_branch or "draft"
                if row.artifact_accepted is None:
                    row.artifact_accepted = True

    async def commit(self):
        return None

    async def delete(self, row):
        self.deleted.append(row)


def _finalization(**overrides):
    values = dict(
        job_id=JOB_ID,
        user_id=USER_ID,
        state="completed",
        job_type="latex_compilation",
        owner_token="worker-token",
        compilation_id=COMPILATION_ID,
        result_payload={"success": True, "pdf_job_id": JOB_ID},
        pdf_path=PDF_PATH,
        pdf_size=64,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _compilation(**overrides):
    values = dict(
        id=COMPILATION_ID,
        job_id=JOB_ID,
        user_id=USER_ID,
        status="completed",
        artifact_branch="draft",
        artifact_accepted=True,
        pdf_path=PDF_PATH,
        pdf_size=64,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class RecoveryUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_row_is_not_recovered_as_pdf_and_query_is_fenced(self):
        session = _RecoverySession(
            _finalization(),
            _compilation(artifact_branch="candidate", artifact_accepted=False),
        )
        result = await job_result_recovery.recover_terminal_job(
            session, job_id=JOB_ID, user_id=USER_ID
        )
        self.assertIsNone(result["pdf_path"])
        self.assertIsNone(result["pdf_size"])
        query = _sql(session.statements[-1])
        self.assertIn("compilations.artifact_accepted is true", query)
        self.assertIn("compilations.job_id", query)
        self.assertIn("compilations.user_id", query)
        self.assertIn("compilations.id", query)

    async def test_accepted_compilation_must_match_authority_and_pointer(self):
        accepted = _RecoverySession(_finalization(), _compilation())
        result = await job_result_recovery.recover_terminal_job(
            accepted, job_id=JOB_ID, user_id=USER_ID
        )
        self.assertEqual(result["pdf_path"], PDF_PATH)

        wrong_id = _RecoverySession(
            _finalization(compilation_id="30000000-0000-4000-8000-000000000003"),
            _compilation(),
        )
        result = await job_result_recovery.recover_terminal_job(
            wrong_id, job_id=JOB_ID, user_id=USER_ID
        )
        self.assertIsNone(result["pdf_path"])

        mismatched_pointer = _RecoverySession(
            _finalization(pdf_path="compilations/other/finalization-0123456789abcdef0123456789abcdef.pdf"),
            _compilation(),
        )
        result = await job_result_recovery.recover_terminal_job(
            mismatched_pointer, job_id=JOB_ID, user_id=USER_ID
        )
        self.assertIsNone(result["pdf_path"])


class PublicArtifactRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api_key = SimpleNamespace(user_id=USER_ID, scopes=["export"])
        self.db = object()

    async def test_compile_admission_binds_accepted_compilation_for_durable_recovery(self):
        db = _AdmissionSession()
        api_key = SimpleNamespace(user_id=USER_ID, id="developer-key")
        with (
            patch.object(public_api_routes, "_authorize", new=AsyncMock(return_value=("pro", None))),
            patch.object(public_api_routes, "_write_initial_redis_state", new=AsyncMock()),
            patch.object(public_api_routes, "_mark_dispatch_started", new=AsyncMock()),
            patch.object(public_api_routes, "_mark_dispatch_accepted", new=AsyncMock()),
            patch.object(public_api_routes, "submit_async", new=AsyncMock()),
        ):
            queued = await public_api_routes.compile_v1(
                public_api_routes.V1CompileRequest(latex_content="\\documentclass{article}"),
                api_key,
                db,
            )

        compilation = next(row for row in db.rows if isinstance(row, Compilation))
        finalization = next(row for row in db.rows if isinstance(row, JobFinalization))
        self.assertEqual(queued.job_id, compilation.job_id)
        self.assertEqual(queued.job_id, finalization.job_id)
        self.assertEqual(finalization.compilation_id, compilation.id)
        self.assertTrue(compilation.artifact_accepted)

        finalization.state = "completed"
        finalization.pdf_path = PDF_PATH
        finalization.pdf_size = 64
        compilation.status = "completed"
        compilation.pdf_path = PDF_PATH
        compilation.pdf_size = 64
        recovery_session = _RecoverySession(finalization, compilation)
        recovered = await job_result_recovery.recover_terminal_job(
            recovery_session, job_id=queued.job_id, user_id=USER_ID
        )
        self.assertEqual(recovered["pdf_path"], PDF_PATH)

    async def test_candidate_status_does_not_advertise_redis_pdf(self):
        redis = SimpleNamespace(
            get=AsyncMock(side_effect=[json.dumps({"status": "completed"}), json.dumps({"success": True, "pdf_job_id": JOB_ID})]),
            exists=AsyncMock(return_value=True),
        )
        with (
            patch.object(public_api_routes, "_assert_job_owner", new=AsyncMock()),
            patch.object(public_api_routes, "get_redis_client", new=AsyncMock(return_value=redis)),
            patch.object(
                job_result_recovery,
                "recover_terminal_job",
                new=AsyncMock(return_value={"state": "completed", "payload": {"success": True}, "pdf_path": None}),
            ),
        ):
            result = await public_api_routes.get_job_v1(JOB_ID, self.api_key, self.db)
        self.assertIsNone(result.pdf_url)
        redis.exists.assert_not_awaited()

    async def test_candidate_download_never_reads_redis_but_redis_only_legacy_still_serves(self):
        redis = SimpleNamespace(get=AsyncMock(return_value=None))
        with (
            patch.object(public_api_routes, "_assert_job_owner", new=AsyncMock()),
            patch.object(public_api_routes, "get_redis_client", new=AsyncMock(return_value=redis)),
            patch.object(
                job_result_recovery,
                "recover_terminal_job",
                new=AsyncMock(return_value={"state": "completed", "pdf_path": None}),
            ),
        ):
            with self.assertRaises(public_api_routes.HTTPException) as caught:
                await public_api_routes.download_job_pdf_v1(JOB_ID, self.api_key, self.db)
        self.assertEqual(caught.exception.status_code, 404)
        redis.get.assert_not_awaited()

        redis.get = AsyncMock(return_value=__import__("base64").b64encode(b"%PDF-1.7 legacy"))
        with (
            patch.object(public_api_routes, "_assert_job_owner", new=AsyncMock()),
            patch.object(public_api_routes, "get_redis_client", new=AsyncMock(return_value=redis)),
            patch.object(job_result_recovery, "recover_terminal_job", new=AsyncMock(return_value=None)),
        ):
            response = await public_api_routes.download_job_pdf_v1(JOB_ID, self.api_key, self.db)
        self.assertEqual(response.body, b"%PDF-1.7 legacy")


if __name__ == "__main__":
    unittest.main(verbosity=2)
