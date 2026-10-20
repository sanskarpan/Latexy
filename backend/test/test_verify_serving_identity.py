"""The serving-revision check must reject a stale or unattested backend.

`verify_modal_deployment_identity.py` accepts Modal's deployment pointer, which
cannot distinguish a fully drained fleet from an old one. Production once served
a backend 32 commits behind that pointer. These cases pin the stricter check
that reads the revision the serving process itself reports.
"""

from __future__ import annotations

import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_serving_identity.py"
spec = importlib.util.spec_from_file_location("verify_serving_identity", SCRIPT)
assert spec and spec.loader
serving = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serving)

SHA = "a" * 40
OLD = "b" * 40


def run_script(*, responses: list[object], expected: str = SHA) -> tuple[int, dict[str, object]]:
    """Run main() against a scripted sequence of health documents."""
    queue = list(responses)

    def fake_fetch(url: str, timeout: float) -> dict[str, object]:
        if not queue:
            raise AssertionError("script made more requests than the fixture provided")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    buffer = io.StringIO()
    with mock.patch.object(serving, "_fetch_health", side_effect=fake_fetch), \
            mock.patch.object(serving.time, "sleep"), \
            redirect_stdout(buffer):
        code = serving.main([
            "--url", "https://example.invalid",
            "--expected-sha", expected,
            "--attempts", "3",
            "--delay-seconds", "0",
        ])
    return code, json.loads(buffer.getvalue())


class ServingIdentityTests(unittest.TestCase):
    def test_matching_serving_revision_verifies(self) -> None:
        code, report = run_script(responses=[{"commit_sha": SHA, "status": "healthy"}])
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["serving_sha"], SHA)
        self.assertEqual(report["source_sha"], SHA)

    def test_stale_serving_revision_blocks(self) -> None:
        """The exact production skew: pointer says new, container is old."""
        code, report = run_script(responses=[{"commit_sha": OLD}] * 3)
        self.assertEqual(code, 1)
        self.assertEqual(report["reason"], "serving_revision_mismatch")
        self.assertEqual(report["serving_sha"], OLD)

    def test_unattested_serving_revision_blocks(self) -> None:
        code, report = run_script(responses=[{"version": "1.0.0"}] * 3)
        self.assertEqual(code, 1)
        self.assertEqual(report["reason"], "serving_revision_unattested")

    def test_blank_serving_revision_blocks(self) -> None:
        code, report = run_script(responses=[{"commit_sha": "   "}] * 3)
        self.assertEqual(code, 1)
        self.assertEqual(report["reason"], "serving_revision_unattested")

    def test_malformed_serving_revision_is_not_echoed(self) -> None:
        code, report = run_script(responses=[{"commit_sha": "<script>alert(1)</script>"}] * 3)
        self.assertEqual(code, 1)
        self.assertEqual(report["reason"], "serving_revision_unattested")
        self.assertNotIn("serving_sha", report)

    def test_unreachable_endpoint_blocks(self) -> None:
        code, report = run_script(responses=[OSError("connection refused")] * 3)
        self.assertEqual(code, 1)
        self.assertEqual(report["reason"], "unreachable")

    def test_recovers_when_the_fleet_drains_after_a_retry(self) -> None:
        code, report = run_script(responses=[{"commit_sha": OLD}, {"commit_sha": SHA}])
        self.assertEqual(code, 0)
        self.assertEqual(report["attempt"], 2)

    def test_uppercase_serving_revision_is_normalized(self) -> None:
        code, report = run_script(responses=[{"commit_sha": SHA.upper()}])
        self.assertEqual(code, 0)
        self.assertEqual(report["serving_sha"], SHA)

    def test_invalid_expected_sha_is_rejected_before_any_request(self) -> None:
        code, report = run_script(responses=[], expected="not-a-sha")
        self.assertEqual(code, 1)
        self.assertEqual(report["reason"], "invalid_expected_sha")

    def test_bounded_read_rejects_oversized_document(self) -> None:
        body = json.dumps({"commit_sha": SHA, "padding": "x" * (serving._MAX_BODY_BYTES + 10)}).encode()
        response = mock.MagicMock()
        response.read.return_value = body
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        with mock.patch.object(serving.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(ValueError):
                serving._fetch_health("https://example.invalid/health", 1.0)


if __name__ == "__main__":
    unittest.main()
