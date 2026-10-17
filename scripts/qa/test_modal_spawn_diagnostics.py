"""Synthetic tests for private Modal spawn diagnostics; no Modal calls are made."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from uuid import uuid4

from modal_spawn_acceptance import (
    HarnessFailure,
    connectivity_report,
    main,
    require_compatible_placement,
    require_preflight,
    runtime_identity,
    terminal_failure_report,
)


class RuntimeIdentityTests(unittest.TestCase):
    def test_records_provider_and_region_for_each_runtime_role(self):
        for role in ("service", "caller", "worker"):
            with self.subTest(role=role):
                self.assertEqual(
                    runtime_identity(role, {
                        "MODAL_CLOUD_PROVIDER": "CLOUD_PROVIDER_AZURE",
                        "MODAL_REGION": "us-east",
                        "MODAL_ENVIRONMENT": "private-synthetic-environment",
                    }),
                    {"role": role, "provider": "CLOUD_PROVIDER_AZURE", "region": "us-east"},
                )

    def test_missing_or_malformed_identity_is_explicit_and_safe(self):
        identity = runtime_identity("worker", {
            "MODAL_CLOUD_PROVIDER": "CLOUD_PROVIDER_AWS\nprivate detail",
            "MODAL_REGION": "",
            "REDIS_URL": "redis://user:synthetic-password@private-host/0",
        })
        self.assertEqual(identity, {"role": "worker", "provider": "unknown", "region": "unknown"})
        self.assertNotIn("private", json.dumps(identity))


class ConnectivityReportTests(unittest.TestCase):
    def test_runner_requires_both_explicit_approvals_before_modal_import(self):
        private_report = str(Path(tempfile.gettempdir()) / f"latexy-harness-test-{uuid4().hex}.json")
        output = io.StringIO()
        with redirect_stdout(output):
            result = main([
                "--image-id", "im-TestImage123",
                "--services-image-id", "im-TestServices123",
                "--renderer-image-id", "im-TestRenderer123",
                "--renderer-assets-fingerprint", "a" * 64,
                "--private-report", private_report,
            ])
        self.assertEqual(result, 2)
        self.assertIn("isolated_modal_run_confirmation_required", output.getvalue())
        self.assertFalse(Path(private_report).exists())

    def test_renderer_gate_confirmation_is_separate(self):
        private_report = str(Path(tempfile.gettempdir()) / f"latexy-harness-test-{uuid4().hex}.json")
        output = io.StringIO()
        with redirect_stdout(output):
            result = main([
                "--image-id", "im-TestImage123",
                "--services-image-id", "im-TestServices123",
                "--renderer-image-id", "im-TestRenderer123",
                "--renderer-assets-fingerprint", "a" * 64,
                "--private-report", private_report,
                "--confirm-isolated-modal-run",
            ])
        self.assertEqual(result, 2)
        self.assertIn("nonproduction_renderer_binding_confirmation_required", output.getvalue())
        self.assertFalse(Path(private_report).exists())

    def test_default_egress_confirmation_is_separate(self):
        private_report = str(Path(tempfile.gettempdir()) / f"latexy-harness-test-{uuid4().hex}.json")
        output = io.StringIO()
        with redirect_stdout(output):
            result = main([
                "--image-id", "im-TestImage123",
                "--services-image-id", "im-TestServices123",
                "--renderer-image-id", "im-TestRenderer123",
                "--renderer-assets-fingerprint", "a" * 64,
                "--private-report", private_report,
                "--confirm-isolated-modal-run",
                "--confirm-nonproduction-renderer-binding",
            ])
        self.assertEqual(result, 2)
        self.assertIn("default_function_egress_confirmation_required", output.getvalue())
        self.assertFalse(Path(private_report).exists())

    def test_renderer_boundary_probe_confirmation_is_separate(self):
        private_report = str(Path(tempfile.gettempdir()) / f"latexy-harness-test-{uuid4().hex}.json")
        output = io.StringIO()
        with redirect_stdout(output):
            result = main([
                "--image-id", "im-TestImage123",
                "--services-image-id", "im-TestServices123",
                "--renderer-image-id", "im-TestRenderer123",
                "--renderer-assets-fingerprint", "a" * 64,
                "--private-report", private_report,
                "--confirm-isolated-modal-run",
                "--confirm-nonproduction-renderer-binding",
                "--confirm-default-egress",
            ])
        self.assertEqual(result, 2)
        self.assertIn("renderer_boundary_probe_confirmation_required", output.getvalue())
        self.assertFalse(Path(private_report).exists())

    def test_same_provider_and_region_is_accepted_before_compile(self):
        reports = [
            {"identity": {"role": role, "provider": "CLOUD_PROVIDER_AZURE", "region": "us-east"}}
            for role in ("service", "caller", "worker")
        ]
        compile_submitted = []
        require_compatible_placement(reports, expected_region="us-east")
        compile_submitted.append(True)
        self.assertEqual(compile_submitted, [True])

    def test_cross_provider_placement_stops_before_compile(self):
        reports = [
            {"identity": {"role": "service", "provider": "CLOUD_PROVIDER_AZURE", "region": "us-east"}},
            {"identity": {"role": "caller", "provider": "CLOUD_PROVIDER_GCP", "region": "us-east"}},
            {"identity": {"role": "worker", "provider": "CLOUD_PROVIDER_AZURE", "region": "us-east"}},
        ]
        compile_submitted = []
        with self.assertRaises(HarnessFailure) as raised:
            require_compatible_placement(reports, expected_region="us-east")
            compile_submitted.append(True)
        self.assertEqual(raised.exception.failure_code, "runtime_provider_mismatch")
        self.assertEqual(compile_submitted, [])

    def test_region_mismatch_stops_before_compile(self):
        reports = [
            {"identity": {"role": "service", "provider": "CLOUD_PROVIDER_AZURE", "region": "us-east"}},
            {"identity": {"role": "caller", "provider": "CLOUD_PROVIDER_AZURE", "region": "us-east"}},
            {"identity": {"role": "worker", "provider": "CLOUD_PROVIDER_AZURE", "region": "us-west"}},
        ]
        with self.assertRaises(HarnessFailure) as raised:
            require_compatible_placement(reports, expected_region="us-east")
        self.assertEqual(raised.exception.failure_code, "runtime_region_mismatch")

    def test_successful_synthetic_probes_are_recorded_without_endpoint_values(self):
        report = connectivity_report(
            "caller",
            environ={"MODAL_CLOUD_PROVIDER": "CLOUD_PROVIDER_GCP", "MODAL_REGION": "us-east"},
            redis_probe=lambda: True,
            s3_probe=lambda: True,
        )
        self.assertEqual(report, {
            "status": "passed",
            "identity": {"role": "caller", "provider": "CLOUD_PROVIDER_GCP", "region": "us-east"},
            "checks": {"redis": "reachable", "s3": "reachable"},
            "failure_code": None,
        })

    def test_probe_exception_fails_closed_without_exception_text(self):
        def fail_with_private_endpoint():
            raise TimeoutError("redis://user:synthetic-password@private-host:6380/0 timed out")

        report = connectivity_report(
            "worker",
            environ={"MODAL_CLOUD_PROVIDER": "CLOUD_PROVIDER_AZURE", "MODAL_REGION": "us-east"},
            redis_probe=fail_with_private_endpoint,
            s3_probe=lambda: True,
        )
        serialized = json.dumps(report)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checks"], {"redis": "unreachable", "s3": "reachable"})
        self.assertEqual(report["failure_code"], "worker_redis_unreachable")
        self.assertNotIn("synthetic-password", serialized)
        self.assertNotIn("private-host", serialized)

    def test_preflight_failure_is_terminal_before_compile_submission(self):
        preflight = connectivity_report(
            "worker",
            environ={"MODAL_CLOUD_PROVIDER": "CLOUD_PROVIDER_AZURE", "MODAL_REGION": "us-east"},
            redis_probe=lambda: False,
            s3_probe=lambda: True,
        )
        with self.assertRaises(HarnessFailure) as raised:
            require_preflight(preflight)

        self.assertEqual(raised.exception.stage, "connectivity_preflight")
        self.assertEqual(raised.exception.failure_code, "worker_redis_unreachable")
        terminal = terminal_failure_report(
            raised.exception.stage,
            raised.exception.failure_code,
            identity=preflight["identity"],
        )
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["stage"], "connectivity_preflight")
        self.assertEqual(terminal["failure_code"], "worker_redis_unreachable")

    def test_nonterminal_worker_timeout_has_a_bounded_terminal_report(self):
        report = terminal_failure_report(
            "await_worker_finalization",
            "job_not_terminal_before_deadline",
            identity={"role": "caller", "provider": "CLOUD_PROVIDER_GCP", "region": "us-east"},
        )
        self.assertEqual(report, {
            "status": "failed",
            "stage": "await_worker_finalization",
            "failure_code": "job_not_terminal_before_deadline",
            "identity": {"role": "caller", "provider": "CLOUD_PROVIDER_GCP", "region": "us-east"},
        })


if __name__ == "__main__":
    unittest.main()
