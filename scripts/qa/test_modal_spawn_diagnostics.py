"""Synthetic tests for private Modal spawn diagnostics; no Modal calls are made."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from modal_spawn_acceptance import (
    HarnessFailure,
    _acceptance_exit_code,
    _cleanup_private_service,
    _deploy_dispatch_app,
    _finalize_cleanup_status,
    _private_service_lifetime,
    _public_summary,
    _stop_dispatch_app,
    connectivity_report,
    function_runtime_environment,
    main,
    require_compatible_placement,
    require_preflight,
    require_worker_placement,
    run_latex_task,
    runtime_identity,
    terminal_failure_report,
)


class _ActiveScope:
    def __init__(self):
        self.active = False

    def __enter__(self):
        self.active = True
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.active = False


class _FakeStopQueue(_ActiveScope):
    def __init__(self, *, fail_put=False):
        super().__init__()
        self.fail_put = fail_put
        self.values = []

    def put(self, value):
        if not self.active:
            raise AssertionError("queue is closed")
        if self.fail_put:
            raise RuntimeError("private queue unavailable")
        self.values.append(value)


class _FakeServiceCall:
    def __init__(self, queue, service_scope, *, fail_get=False):
        self.queue = queue
        self.service_scope = service_scope
        self.fail_get = fail_get
        self.timeouts = []

    def get(self, *, timeout):
        if not self.queue.active or not self.service_scope.active:
            raise AssertionError("service resources are out of scope")
        self.timeouts.append(timeout)
        if self.fail_get:
            raise RuntimeError("service failed to stop")
        return None


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


class ModalRuntimeEnvironmentTests(unittest.TestCase):
    def test_modal_environment_is_not_overridden_in_function_env(self):
        runtime_env = function_runtime_environment(
            "fd00::1", "im-TestRenderer123", "a" * 64,
        )
        self.assertNotIn("MODAL_ENVIRONMENT", runtime_env)
        self.assertEqual(runtime_env["DEPLOY_TARGET"], "modal")


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

    def test_actual_worker_matching_expected_provider_and_region_is_accepted(self):
        require_worker_placement(
            {"role": "worker", "provider": "CLOUD_PROVIDER_AZURE", "region": "us-east"},
            {"provider": "CLOUD_PROVIDER_AZURE", "region": "us-east"},
        )

    def test_actual_worker_provider_mismatch_stops_before_compile(self):
        compile_submitted = []
        with self.assertRaises(HarnessFailure) as raised:
            require_worker_placement(
                {"role": "worker", "provider": "CLOUD_PROVIDER_GCP", "region": "us-east"},
                {"provider": "CLOUD_PROVIDER_AZURE", "region": "us-east"},
            )
            compile_submitted.append(True)
        self.assertEqual(raised.exception.stage, "worker_placement")
        self.assertEqual(raised.exception.failure_code, "worker_provider_mismatch")
        self.assertEqual(compile_submitted, [])

    def test_actual_worker_region_mismatch_stops_before_compile(self):
        with self.assertRaises(HarnessFailure) as raised:
            require_worker_placement(
                {"role": "worker", "provider": "CLOUD_PROVIDER_AZURE", "region": "us-west"},
                {"provider": "CLOUD_PROVIDER_AZURE", "region": "us-east"},
            )
        self.assertEqual(raised.exception.failure_code, "worker_region_mismatch")

    def test_actual_worker_requires_a_known_expected_placement(self):
        for expected in (None, {"provider": "unknown", "region": "us-east"}, {}):
            with self.subTest(expected=expected), self.assertRaises(HarnessFailure) as raised:
                require_worker_placement(
                    {"role": "worker", "provider": "CLOUD_PROVIDER_AZURE", "region": "us-east"},
                    expected,
                )
            self.assertEqual(raised.exception.failure_code, "expected_placement_missing")

    def test_actual_worker_wrapper_records_mismatch_before_compile_imports(self):
        worker_report = {
            "status": "passed",
            "identity": {"role": "worker", "provider": "CLOUD_PROVIDER_GCP", "region": "us-east"},
            "checks": {"redis": "reachable", "s3": "reachable"},
            "failure_code": None,
        }
        with (
            patch.dict(os.environ, {"HARNESS_RUN_ID": "synthetic-run"}, clear=False),
            patch("modal_spawn_acceptance._runtime_preflight", return_value=worker_report),
            patch("modal_spawn_acceptance._store_worker_identity"),
            patch("modal_spawn_acceptance._read_expected_placement", return_value={
                "provider": "CLOUD_PROVIDER_AZURE", "region": "us-east",
            }),
            patch("modal_spawn_acceptance._record_worker_failure") as record_failure,
        ):
            with self.assertRaises(HarnessFailure) as raised:
                run_latex_task({})

        self.assertEqual(raised.exception.failure_code, "worker_provider_mismatch")
        record_failure.assert_called_once_with(
            "synthetic-run", "worker_placement", "worker_provider_mismatch",
        )

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


class CleanupTests(unittest.TestCase):
    def test_private_services_are_cleaned_up_on_success_and_body_error_in_scope(self):
        for fail_body in (False, True):
            with self.subTest(fail_body=fail_body):
                queue = _FakeStopQueue()
                service_scope = _ActiveScope()
                call = _FakeServiceCall(queue, service_scope)
                report = {"status": "passed"}

                if fail_body:
                    with self.assertRaises(RuntimeError):
                        with queue:
                            with service_scope:
                                with _private_service_lifetime(queue, call, report):
                                    raise RuntimeError("synthetic body error")
                else:
                    with queue:
                        with service_scope:
                            with _private_service_lifetime(queue, call, report):
                                self.assertTrue(queue.active)
                                self.assertTrue(service_scope.active)

                self.assertEqual(queue.values, ["stop"])
                self.assertEqual(call.timeouts, [45])
                self.assertFalse(queue.active)
                self.assertFalse(service_scope.active)
                self.assertTrue(report["service_stop_signal_sent"])
                self.assertTrue(report["private_services_stopped"])

    def test_stop_signal_failure_does_not_skip_join_and_fails_public_result(self):
        queue = _FakeStopQueue(fail_put=True)
        service_scope = _ActiveScope()
        call = _FakeServiceCall(queue, service_scope)
        report = {"status": "passed", "dispatch_app_stopped": True}
        with queue:
            with service_scope:
                _cleanup_private_service(queue, call, report)
        self.assertEqual(call.timeouts, [45])
        self.assertFalse(report["service_stop_signal_sent"])
        self.assertTrue(report["private_services_stopped"])
        self._assert_cleanup_failure(report, "service_stop_signal_failed")

    def test_private_service_join_failure_fails_public_result(self):
        queue = _FakeStopQueue()
        service_scope = _ActiveScope()
        call = _FakeServiceCall(queue, service_scope, fail_get=True)
        report = {"status": "passed", "dispatch_app_stopped": True}
        with queue:
            with service_scope:
                _cleanup_private_service(queue, call, report)
        self.assertTrue(report["service_stop_signal_sent"])
        self.assertFalse(report["private_services_stopped"])
        self._assert_cleanup_failure(report, "private_services_stop_failed")

    def test_dispatch_stop_timeout_fails_public_result(self):
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

        stopped = _stop_dispatch_app(
            "latexy-harness-test", "latexy-harness-env", attempted=True,
            modal_cli="modal", runner=timeout,
        )
        report = {
            "status": "passed", "service_stop_signal_sent": True,
            "private_services_stopped": True, "dispatch_app_stopped": stopped,
        }
        self._assert_cleanup_failure(report, "dispatch_app_stop_failed")

    def test_dispatch_stop_nonzero_result_fails_public_result(self):
        def runner(*args, **kwargs):
            return type("Completed", (), {"returncode": 1})()

        stopped = _stop_dispatch_app(
            "latexy-harness-test", "latexy-harness-env", attempted=True,
            modal_cli="modal", runner=runner,
        )
        report = {
            "status": "passed", "service_stop_signal_sent": True,
            "private_services_stopped": True, "dispatch_app_stopped": stopped,
        }
        self._assert_cleanup_failure(report, "dispatch_app_stop_failed")

    def test_dispatch_app_stop_is_skipped_before_deployment_attempt(self):
        def unexpected_runner(*args, **kwargs):
            raise AssertionError("stop must not run")

        self.assertIsNone(_stop_dispatch_app(
            "latexy-harness-test", "latexy-harness-env", attempted=False,
            modal_cli="modal", runner=unexpected_runner,
        ))

    def test_partial_deployment_still_attempts_app_stop(self):
        class PartialDeployApp:
            def deploy(self, *, environment_name):
                raise RuntimeError("synthetic partial deploy")

        state = {"attempted": False}
        with self.assertRaises(RuntimeError):
            _deploy_dispatch_app(PartialDeployApp(), "latexy-harness-env", state)
        self.assertTrue(state["attempted"])
        stopped_commands = []

        def runner(command, **kwargs):
            stopped_commands.append(command)
            return type("Completed", (), {"returncode": 0})()

        stopped = _stop_dispatch_app(
            "latexy-harness-test", "latexy-harness-env", attempted=state["attempted"],
            modal_cli="modal", runner=runner,
        )
        self.assertTrue(stopped)
        self.assertEqual(len(stopped_commands), 1)
        self.assertIn("latexy-harness-test", stopped_commands[0])

    def _assert_cleanup_failure(self, report, expected_code):
        _finalize_cleanup_status(report)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["stage"], "cleanup")
        self.assertEqual(report["failure_code"], expected_code)
        public = _public_summary(report)
        self.assertEqual(public, {"status": "failed", "failure_code": expected_code})
        self.assertEqual(_acceptance_exit_code(report), 1)


if __name__ == "__main__":
    unittest.main()
