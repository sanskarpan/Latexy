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

import modal_spawn_acceptance as acceptance
import run_modal_spawn_diagnostics as diagnostics_runner
from app.services.render_engine import functional_acceptance_policy
from modal_functional_environment_inventory import main as functional_inventory_main
from modal_spawn_acceptance import (
    HarnessFailure,
    _acceptance_exit_code,
    _acceptance_report,
    _cleanup_private_service,
    _deploy_dispatch_app,
    _ephemeral_queue,
    _finalize_cleanup_status,
    _private_service_lifetime,
    _public_summary,
    _set_renderer_report_scope,
    _stop_dispatch_app,
    _stop_disposable_services,
    connectivity_report,
    function_runtime_environment,
    main,
    read_functional_environment_inventory,
    require_compatible_placement,
    require_preflight,
    require_worker_placement,
    run_latex_task,
    runtime_identity,
    terminal_failure_report,
    validate_existing_nonproduction_environment,
    validate_functional_acceptance_environment_name,
    validate_nonproduction_environment_name,
)


def _reviewed_test_environment(name="reviewed-test-environment", object_id="en-review-test"):
    digest = functional_acceptance_policy.functional_environment_inventory_sha256(name, object_id)
    return functional_acceptance_policy.FunctionalAcceptanceEnvironmentApproval(
        name=name,
        environment_object_id=object_id,
        binding_manifest_sha256=digest,
        evidence_ref="docs/acceptance/environment-inventory.md#sha256=" + "a" * 64,
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
        approval = _reviewed_test_environment()
        original = functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS
        try:
            functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = (approval,)
            runtime_env = function_runtime_environment(
                "fd00::1", "im-TestRenderer123", "a" * 64,
                functional_environment_approval=approval,
            )
        finally:
            functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = original
        self.assertNotIn("MODAL_ENVIRONMENT", runtime_env)
        self.assertEqual(runtime_env["DEPLOY_TARGET"], "modal")
        self.assertEqual(runtime_env["MODAL_DEPLOYMENT_TRAFFIC_HOLD"], "false")

    def test_boundary_traffic_hold_override_requires_reviewed_nonproduction_identity(self):
        with self.assertRaises(HarnessFailure) as raised:
            function_runtime_environment(
                "fd00::1", "im-TestRenderer123", "a" * 64,
                renderer_mode="boundary",
            )
        self.assertEqual(raised.exception.failure_code, "functional_environment_approval_required")

        approval = _reviewed_test_environment()
        with self.assertRaises(HarnessFailure) as raised:
            function_runtime_environment(
                "fd00::1", "im-TestRenderer123", "a" * 64,
                renderer_mode="boundary", functional_environment_approval=approval,
            )
        self.assertEqual(raised.exception.failure_code, "functional_environment_approval_required")

    def test_boundary_traffic_hold_override_rejects_allowlisted_production_aliases(self):
        original = functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS
        try:
            for name in (
                "main", "prod", "production", "prod-west", "production-blue", "live",
                "latexy-acceptance-prod",
            ):
                approval = _reviewed_test_environment(name=name)
                functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = (approval,)
                with self.subTest(name=name), self.assertRaises(HarnessFailure) as raised:
                    function_runtime_environment(
                        "fd00::1", "im-TestRenderer123", "a" * 64,
                        renderer_mode="boundary", functional_environment_approval=approval,
                    )
                self.assertEqual(raised.exception.failure_code, "functional_environment_approval_required")
        finally:
            functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = original

    def test_functional_only_runtime_binding_requires_and_passes_reviewed_identity(self):
        approval = _reviewed_test_environment()
        original = functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS
        try:
            functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = (approval,)
            runtime_env = function_runtime_environment(
                "fd00::1", "im-TestRenderer123", "a" * 64, renderer_mode="functional-only",
                functional_environment_approval=approval,
            )
            self.assertEqual(runtime_env["MODAL_ENGINE_VM_CERTIFIED"], "")
            self.assertEqual(runtime_env["MODAL_ENGINE_VM_FUNCTIONAL_ONLY_ACCEPTANCE"], "true")
            self.assertEqual(
                runtime_env["MODAL_ENGINE_VM_FUNCTIONAL_ONLY_ENVIRONMENT_ID"],
                approval.environment_object_id,
            )
            self.assertEqual(
                runtime_env["MODAL_ENGINE_VM_FUNCTIONAL_ONLY_BINDING_MANIFEST_SHA256"],
                approval.binding_manifest_sha256,
            )
            self.assertEqual(runtime_env["ENVIRONMENT"], "test")
        finally:
            functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = original

    def test_functional_only_runtime_binding_rejects_unreviewed_identity(self):
        with self.assertRaises(HarnessFailure) as raised:
            function_runtime_environment(
                "fd00::1", "im-TestRenderer123", "a" * 64, renderer_mode="functional-only",
                functional_environment_approval=_reviewed_test_environment(),
            )
        self.assertEqual(raised.exception.failure_code, "functional_environment_approval_required")

    def test_unknown_renderer_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            function_runtime_environment("fd00::1", "im-TestRenderer123", "a" * 64,
                                         renderer_mode="skip-everything")


class ModalEnvironmentValidationTests(unittest.TestCase):
    def test_functional_acceptance_is_fail_closed_for_known_and_unverified_names(self):
        self.assertEqual(diagnostics_runner._MINIMUM_EXPECTED_TESTS, 53)
        self.assertEqual(functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS, ())
        for alias in (
            "prod-west", "production-blue", "main", "prod", "production", "live",
            "billing-acceptance-20261014-prod",
        ):
            with self.subTest(name=alias), self.assertRaises(HarnessFailure) as raised:
                validate_nonproduction_environment_name(alias)
            self.assertEqual(raised.exception.failure_code, "nonproduction_environment_required")
        for name in (
            "unknownenv", "Billing-acceptance-20261014",
            "billing-acceptance-20261014", "latexy-synthetic-20261016-4182705d",
        ):
            with self.subTest(name=name), self.assertRaises(HarnessFailure) as raised:
                validate_functional_acceptance_environment_name(name)
            self.assertEqual(raised.exception.failure_code, "functional_environment_not_allowlisted")

    def test_policy_entry_needs_complete_provenance_and_unambiguous_name(self):
        approval = _reviewed_test_environment()
        original = functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS
        try:
            functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = (
                functional_acceptance_policy.FunctionalAcceptanceEnvironmentApproval(
                    approval.name, approval.environment_object_id,
                    approval.binding_manifest_sha256, "",
                ),
            )
            self.assertIsNone(
                functional_acceptance_policy.get_functional_acceptance_environment_approval(
                    approval.name,
                ),
            )
            functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = (
                approval,
                functional_acceptance_policy.FunctionalAcceptanceEnvironmentApproval(
                    approval.name, "en-other-object", approval.binding_manifest_sha256,
                    approval.evidence_ref,
                ),
            )
            self.assertIsNone(
                functional_acceptance_policy.get_functional_acceptance_environment_approval(
                    approval.name,
                ),
            )
        finally:
            functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = original

    def test_reviewed_environment_requires_exact_object_id_and_empty_inventory(self):
        approval = _reviewed_test_environment()
        original = functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS

        class Environment:
            name = approval.name
            object_id = approval.environment_object_id
            apps = type("Apps", (), {"list": lambda self: []})()

        class Manager:
            def __init__(self, items):
                self.items = items
                self.calls = []

            def list(self, **kwargs):
                self.calls.append(kwargs)
                return self.items

        secret_manager, volume_manager = Manager([]), Manager([])
        sdk = type("ModalSDK", (), {
            "Environment": type("EnvironmentAPI", (), {
                "objects": type("EnvironmentManager", (), {"list": lambda self: [Environment()]})(),
            }),
            "Secret": type("SecretAPI", (), {"objects": secret_manager}),
            "Volume": type("VolumeAPI", (), {"objects": volume_manager}),
        })
        try:
            functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = (approval,)
            verified = validate_existing_nonproduction_environment(
                sdk, approval.name, functional_only=True,
            )
            self.assertEqual(verified, approval)
            self.assertEqual(secret_manager.calls, [{"environment_name": approval.name}])
            self.assertEqual(volume_manager.calls, [{"environment_name": approval.name}])
        finally:
            functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = original

    def test_functional_environment_inventory_blocks_existing_named_secret_without_exposing_it(self):
        approval = _reviewed_test_environment()
        original = functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS

        class Resource:
            name = "latexy-backend-secrets"
            object_id = "sc-secret-object-id"

        class Environment:
            name = approval.name
            object_id = approval.environment_object_id
            apps = type("Apps", (), {"list": lambda self: []})()

        class Manager:
            def __init__(self, items):
                self.items = items

            def list(self, **kwargs):
                return self.items

        sdk = type("ModalSDK", (), {
            "Environment": type("EnvironmentAPI", (), {
                "objects": type("EnvironmentManager", (), {"list": lambda self: [Environment()]})(),
            }),
            "Secret": type("SecretAPI", (), {"objects": Manager([Resource()])}),
            "Volume": type("VolumeAPI", (), {"objects": Manager([])}),
        })
        try:
            functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = (approval,)
            with self.assertRaises(HarnessFailure) as raised:
                validate_existing_nonproduction_environment(sdk, approval.name, functional_only=True)
            self.assertEqual(raised.exception.failure_code, "functional_environment_not_empty")
            self.assertNotIn(Resource.name, str(raised.exception))
        finally:
            functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = original

    def test_read_only_inventory_cli_reports_counts_without_secret_names_or_values(self):
        secret_name = "private-secret-name-must-not-print"

        class SecretHandle:
            name = secret_name
            object_id = "sc-test-secret"

            @property
            def values(self):
                raise AssertionError("Secret contents must never be inspected")

        class Environment:
            name = "inventory-cli-test"
            object_id = "en-inventory-cli-test"
            apps = type("Apps", (), {"list": lambda self: []})()

        class Manager:
            def __init__(self, items):
                self.items = items

            def list(self, **kwargs):
                return self.items

        sdk = type("ModalSDK", (), {
            "Environment": type("EnvironmentAPI", (), {
                "objects": type("EnvironmentManager", (), {"list": lambda self: [Environment()]})(),
            }),
            "Secret": type("SecretAPI", (), {"objects": Manager([SecretHandle()])}),
            "Volume": type("VolumeAPI", (), {"objects": Manager([])}),
        })
        output = io.StringIO()
        with patch.dict("sys.modules", {"modal": sdk}), redirect_stdout(output):
            result = functional_inventory_main(["--environment-name", Environment.name])
        self.assertEqual(result, 2)
        self.assertIn('"secret_count": 1', output.getvalue())
        self.assertNotIn(secret_name, output.getvalue())
        self.assertNotIn("values", output.getvalue())

    def test_read_only_inventory_reports_stage_and_error_class_without_exception_text(self):
        private_detail = "private-secret-name-and-value-must-not-print"

        class Environment:
            name = "inventory-error-test"
            object_id = "en-inventory-error-test"

        class SecretManager:
            def list(self, **kwargs):
                raise PermissionError(private_detail)

        sdk = type("ModalSDK", (), {
            "Environment": type("EnvironmentAPI", (), {
                "objects": type("EnvironmentManager", (), {"list": lambda self: [Environment()]})(),
            }),
            "Secret": type("SecretAPI", (), {"objects": SecretManager()}),
        })
        output = io.StringIO()
        with patch.dict("sys.modules", {"modal": sdk}), redirect_stdout(output):
            result = functional_inventory_main(["--environment-name", Environment.name])
        self.assertEqual(result, 2)
        self.assertIn('"stage": "secret_list"', output.getvalue())
        self.assertIn('"error_class": "PermissionError"', output.getvalue())
        self.assertNotIn(private_detail, output.getvalue())

    def test_inventory_uses_modal_15_cli_for_live_apps(self):
        class Environment:
            name = "inventory-legacy-sdk-test"
            object_id = "en-inventory-legacy-sdk-test"

        class Manager:
            def __init__(self, items):
                self.items = items

            def list(self, **kwargs):
                return self.items

        sdk = type("ModalSDK", (), {
            "Environment": type("EnvironmentAPI", (), {
                "objects": type("EnvironmentManager", (), {"list": lambda self: [Environment()]})(),
            }),
            "Secret": type("SecretAPI", (), {"objects": Manager([])}),
            "Volume": type("VolumeAPI", (), {"objects": Manager([])}),
        })
        cli_result = subprocess.CompletedProcess(
            args=["python", "-m", "modal"],
            returncode=0,
            stdout=json.dumps([
                {"app_id": "ap-live", "description": "live-app", "state": "ephemeral"},
                {"app_id": "ap-stopped", "description": "old-app", "state": "stopped"},
            ]),
            stderr="",
        )
        with patch.object(acceptance.subprocess, "run", return_value=cli_result) as run_cli:
            inventory = read_functional_environment_inventory(sdk, Environment.name)

        self.assertEqual(inventory.active_app_count, 1)
        run_cli.assert_called_once_with(
            [
                acceptance.sys.executable, "-m", "modal", "app", "list",
                "--env", Environment.name, "--json",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )

    def test_inventory_sanitizes_modal_cli_access_denial_stage(self):
        private_detail = "Permission denied: private-app-and-secret-metadata"

        class Environment:
            name = "inventory-access-denial-test"
            object_id = "en-inventory-access-denial-test"

        class Manager:
            def list(self, **kwargs):
                return []

        sdk = type("ModalSDK", (), {
            "Environment": type("EnvironmentAPI", (), {
                "objects": type("EnvironmentManager", (), {"list": lambda self: [Environment()]})(),
            }),
            "Secret": type("SecretAPI", (), {"objects": Manager()}),
            "Volume": type("VolumeAPI", (), {"objects": Manager()}),
        })
        cli_result = subprocess.CompletedProcess(
            args=["python", "-m", "modal"],
            returncode=1,
            stdout="",
            stderr=private_detail,
        )
        output = io.StringIO()
        with (
            patch.dict("sys.modules", {"modal": sdk}),
            patch.object(acceptance.subprocess, "run", return_value=cli_result),
            redirect_stdout(output),
        ):
            result = functional_inventory_main(["--environment-name", Environment.name])
        self.assertEqual(result, 2)
        self.assertIn('"stage": "active_app_list"', output.getvalue())
        self.assertIn('"error_class": "PermissionDeniedError"', output.getvalue())
        self.assertNotIn(private_detail, output.getvalue())

    def test_existing_nonproduction_environment_is_found_by_read_only_list(self):
        class EnvironmentManager:
            list_calls = 0

            def list(self):
                self.list_calls += 1
                return [type("Environment", (), {"name": "test-sandbox"})()]

        manager = EnvironmentManager()
        sdk = type("ModalSDK", (), {
            "Environment": type("EnvironmentAPI", (), {"objects": manager}),
        })
        self.assertEqual(validate_existing_nonproduction_environment(sdk, "test-sandbox"), "test-sandbox")
        self.assertEqual(manager.list_calls, 1)
        self.assertFalse(hasattr(manager, "create"))

    def test_ephemeral_queues_are_scoped_to_the_selected_environment(self):
        class QueueAPI:
            calls = []

            @classmethod
            def ephemeral(cls, **kwargs):
                cls.calls.append(kwargs)
                return _ActiveScope()

        modal_sdk = type("ModalSDK", (), {"Queue": QueueAPI})
        for _ in range(2):
            with _ephemeral_queue(modal_sdk, "test-sandbox"):
                pass
        self.assertEqual(QueueAPI.calls, [
            {"environment_name": "test-sandbox"},
            {"environment_name": "test-sandbox"},
        ])

    def test_missing_existing_environment_fails_without_creation(self):
        class EnvironmentManager:
            def list(self):
                return [type("Environment", (), {"name": "dev"})()]

        sdk = type("ModalSDK", (), {
            "Environment": type("EnvironmentAPI", (), {"objects": EnvironmentManager()}),
        })
        with self.assertRaises(HarnessFailure) as raised:
            validate_existing_nonproduction_environment(sdk, "test-sandbox")
        self.assertEqual(raised.exception.failure_code, "environment_not_found")

    def test_default_and_obvious_production_environment_names_are_rejected(self):
        for name in ("main", "MAIN", "prod", "production", ""):
            with self.subTest(name=name), self.assertRaises(HarnessFailure) as raised:
                validate_nonproduction_environment_name(name)
            self.assertEqual(raised.exception.failure_code, "nonproduction_environment_required")

    def test_environment_lookup_failure_is_sanitized(self):
        class EnvironmentManager:
            def list(self):
                raise TimeoutError("private workspace detail")

        sdk = type("ModalSDK", (), {
            "Environment": type("EnvironmentAPI", (), {"objects": EnvironmentManager()}),
        })
        with self.assertRaises(HarnessFailure) as raised:
            validate_existing_nonproduction_environment(sdk, "test-sandbox")
        self.assertEqual(raised.exception.failure_code, "environment_lookup_failed")
        self.assertNotIn("private workspace detail", str(raised.exception))

    def test_main_validates_environment_before_constructing_modal_resources(self):
        class EnvironmentManager:
            def list(self):
                return []

        def unexpected_resource_creation(*args, **kwargs):
            raise AssertionError("resource construction happened before environment validation")

        environment_api = type("EnvironmentAPI", (), {"objects": EnvironmentManager()})
        sdk = type("ModalSDK", (), {
            "Environment": environment_api,
            "Image": type("ImageAPI", (), {"from_id": unexpected_resource_creation}),
            "App": unexpected_resource_creation,
            "Queue": type("QueueAPI", (), {"ephemeral": unexpected_resource_creation}),
        })
        private_report = str(Path(tempfile.gettempdir()) / f"latexy-harness-test-{uuid4().hex}.json")
        output = io.StringIO()
        approval = _reviewed_test_environment(name="test-sandbox")
        with (
            patch.object(functional_acceptance_policy, "TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS", (approval,)),
            patch.dict("sys.modules", {"modal": sdk}),
            redirect_stdout(output),
        ):
            result = main([
                "--image-id", "im-TestImage123",
                "--services-image-id", "im-TestServices123",
                "--renderer-image-id", "im-TestRenderer123",
                "--renderer-assets-fingerprint", "a" * 64,
                "--environment-name", "test-sandbox",
                "--private-report", private_report,
                "--confirm-isolated-modal-run",
                "--confirm-nonproduction-environment",
                "--confirm-nonproduction-renderer-binding",
                "--confirm-default-egress",
                "--confirm-renderer-boundary-probe",
            ])
        self.assertEqual(result, 2)
        self.assertIn("environment_not_found", output.getvalue())
        self.assertFalse(Path(private_report).exists())


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
                "--environment-name", "test-sandbox",
                "--private-report", private_report,
                "--confirm-nonproduction-environment",
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
                "--environment-name", "test-sandbox",
                "--private-report", private_report,
                "--confirm-isolated-modal-run",
                "--confirm-nonproduction-environment",
            ])
        self.assertEqual(result, 2)
        self.assertIn("nonproduction_renderer_binding_confirmation_required", output.getvalue())
        self.assertFalse(Path(private_report).exists())

    def test_existing_nonproduction_environment_confirmation_is_separate(self):
        private_report = str(Path(tempfile.gettempdir()) / f"latexy-harness-test-{uuid4().hex}.json")
        output = io.StringIO()
        with redirect_stdout(output):
            result = main([
                "--image-id", "im-TestImage123",
                "--services-image-id", "im-TestServices123",
                "--renderer-image-id", "im-TestRenderer123",
                "--renderer-assets-fingerprint", "a" * 64,
                "--environment-name", "test-sandbox",
                "--private-report", private_report,
                "--confirm-isolated-modal-run",
            ])
        self.assertEqual(result, 2)
        self.assertIn("nonproduction_environment_confirmation_required", output.getvalue())
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
                "--environment-name", "test-sandbox",
                "--private-report", private_report,
                "--confirm-isolated-modal-run",
                "--confirm-nonproduction-environment",
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
                "--environment-name", "test-sandbox",
                "--private-report", private_report,
                "--confirm-isolated-modal-run",
                "--confirm-nonproduction-environment",
                "--confirm-nonproduction-renderer-binding",
                "--confirm-default-egress",
            ])
        self.assertEqual(result, 2)
        self.assertIn("renderer_boundary_probe_confirmation_required", output.getvalue())
        self.assertFalse(Path(private_report).exists())

    def test_functional_mode_remains_blocked_even_with_acknowledgements_for_quarantined_names(self):
        for environment_name in (
            "billing-acceptance-20261014", "latexy-synthetic-20261016-4182705d",
        ):
            private_report = str(Path(tempfile.gettempdir()) / f"latexy-harness-test-{uuid4().hex}.json")
            output = io.StringIO()
            with self.subTest(environment_name=environment_name), redirect_stdout(output):
                result = main([
                    "--image-id", "im-TestImage123",
                    "--services-image-id", "im-TestServices123",
                    "--renderer-image-id", "im-TestRenderer123",
                    "--renderer-assets-fingerprint", "a" * 64,
                    "--environment-name", environment_name,
                    "--private-report", private_report,
                    "--renderer-mode", "functional-only",
                    "--confirm-isolated-modal-run",
                    "--confirm-nonproduction-environment",
                    "--confirm-default-egress",
                    "--confirm-functional-renderer-binding",
                ])
            self.assertEqual(result, 2)
            self.assertIn("functional_environment_not_allowlisted", output.getvalue())
            self.assertFalse(Path(private_report).exists())

    def test_functional_mode_rejects_boundary_probe_acknowledgement(self):
        approval = _reviewed_test_environment()
        original = functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS
        private_report = str(Path(tempfile.gettempdir()) / f"latexy-harness-test-{uuid4().hex}.json")
        output = io.StringIO()
        try:
            functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = (approval,)
            with redirect_stdout(output):
                result = main([
                    "--image-id", "im-TestImage123",
                    "--services-image-id", "im-TestServices123",
                    "--renderer-image-id", "im-TestRenderer123",
                    "--renderer-assets-fingerprint", "a" * 64,
                    "--environment-name", approval.name,
                    "--private-report", private_report,
                    "--renderer-mode", "functional-only",
                    "--confirm-isolated-modal-run",
                    "--confirm-nonproduction-environment",
                    "--confirm-default-egress",
                    "--confirm-functional-renderer-binding",
                    "--confirm-renderer-boundary-probe",
                ])
        finally:
            functional_acceptance_policy.TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = original
        self.assertEqual(result, 2)
        self.assertIn("boundary_probe_confirmation_not_allowed_in_functional_mode", output.getvalue())
        self.assertFalse(Path(private_report).exists())

    def test_functional_mode_rejects_production_alias_before_modal_import(self):
        private_report = str(Path(tempfile.gettempdir()) / f"latexy-harness-test-{uuid4().hex}.json")
        output = io.StringIO()
        with redirect_stdout(output):
            result = main([
                "--image-id", "im-TestImage123",
                "--services-image-id", "im-TestServices123",
                "--renderer-image-id", "im-TestRenderer123",
                "--renderer-assets-fingerprint", "a" * 64,
                "--environment-name", "prod-west",
                "--private-report", private_report,
                "--renderer-mode", "functional-only",
                "--confirm-isolated-modal-run",
                "--confirm-nonproduction-environment",
                "--confirm-default-egress",
                "--confirm-functional-renderer-binding",
            ])
        self.assertEqual(result, 2)
        self.assertIn("nonproduction_environment_required", output.getvalue())
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
    def test_functional_only_cleanup_failure_remains_failed_and_uncertified(self):
        report = _acceptance_report("functional-only")
        report["renderer_boundary_probe"] = "executed"
        report["production_certification_claimed"] = True
        _set_renderer_report_scope(report, "functional-only")
        report.update({
            "status": "passed",
            "service_stop_signal_sent": True,
            "private_services_stopped": True,
            "dispatch_app_stopped": False,
        })
        _finalize_cleanup_status(report)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failure_code"], "dispatch_app_stop_failed")
        self.assertEqual(report["renderer_boundary_probe"], "not_run")
        self.assertFalse(report["production_certification_claimed"])
        self.assertEqual(_acceptance_exit_code(report), 1)

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


class ServiceShutdownTests(unittest.TestCase):
    def test_successful_shutdown_checks_both_command_results(self):
        class Moto:
            stopped = False

            def stop(self):
                self.stopped = True

        moto = Moto()
        commands = []

        def runner(command, **kwargs):
            commands.append(command)
            return type("Completed", (), {"returncode": 0})()

        _stop_disposable_services(moto, "synthetic-password", runner=runner)
        self.assertTrue(moto.stopped)
        self.assertEqual([command[0] for command in commands], ["redis-cli", "pg_ctlcluster"])

    def test_redis_nonzero_result_fails_after_postgres_stop_is_attempted(self):
        commands = []
        results = iter((1, 0))

        def runner(command, **kwargs):
            commands.append(command)
            return type("Completed", (), {"returncode": next(results)})()

        with self.assertRaises(HarnessFailure) as raised:
            _stop_disposable_services(None, "synthetic-password", runner=runner)
        self.assertEqual(raised.exception.stage, "service_shutdown")
        self.assertEqual(raised.exception.failure_code, "redis_shutdown_failed")
        self.assertEqual([command[0] for command in commands], ["redis-cli", "pg_ctlcluster"])

    def test_postgres_nonzero_result_fails_after_redis_shutdown(self):
        commands = []
        results = iter((0, 1))

        def runner(command, **kwargs):
            commands.append(command)
            return type("Completed", (), {"returncode": next(results)})()

        with self.assertRaises(HarnessFailure) as raised:
            _stop_disposable_services(None, "synthetic-password", runner=runner)
        self.assertEqual(raised.exception.failure_code, "postgres_stop_failed")
        self.assertEqual([command[0] for command in commands], ["redis-cli", "pg_ctlcluster"])

    def test_moto_and_command_exceptions_do_not_skip_later_cleanup(self):
        class Moto:
            def stop(self):
                raise RuntimeError("private moto stop detail")

        commands = []

        def runner(command, **kwargs):
            commands.append(command)
            if command[0] == "redis-cli":
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            return type("Completed", (), {"returncode": 1})()

        with self.assertRaises(HarnessFailure) as raised:
            _stop_disposable_services(Moto(), "synthetic-password", runner=runner)
        self.assertEqual(raised.exception.failure_code, "moto_stop_failed")
        self.assertEqual([command[0] for command in commands], ["redis-cli", "pg_ctlcluster"])
        self.assertNotIn("private moto stop detail", str(raised.exception))

    def test_service_shutdown_failure_reaches_nonpassing_final_report(self):
        queue = _FakeStopQueue()
        service_scope = _ActiveScope()

        class FailedServiceShutdown:
            def get(self, *, timeout):
                _stop_disposable_services(
                    None, "synthetic-password",
                    runner=lambda command, **kwargs: type("Completed", (), {"returncode": 1})(),
                )

        report = {"status": "passed", "dispatch_app_stopped": True}
        with queue:
            with service_scope:
                _cleanup_private_service(queue, FailedServiceShutdown(), report)
        _finalize_cleanup_status(report)
        self.assertFalse(report["private_services_stopped"])
        self.assertEqual(_public_summary(report), {
            "status": "failed", "failure_code": "private_services_stop_failed",
        })
        self.assertEqual(_acceptance_exit_code(report), 1)


if __name__ == "__main__":
    unittest.main()
