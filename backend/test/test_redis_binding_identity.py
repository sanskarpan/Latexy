"""Synthetic selector attestation; never imports Modal or uses real secrets."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app.core.serve_identity import redis_binding_fingerprint

BACKEND = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "serving_binding_test_script", BACKEND / "scripts" / "verify_serving_identity.py",
)
assert SPEC and SPEC.loader
SCRIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCRIPT)
SHA = "a" * 40


class RedisBindingIdentityTests(unittest.TestCase):
    def run_guard(self, body, label="latexy-redis"):
        output = io.StringIO()
        with patch.object(SCRIPT, "_fetch_health", return_value=body) as fetch, redirect_stdout(output):
            result = SCRIPT.main([
                "--url", "https://example.invalid", "--expected-sha", SHA,
                "--expected-redis-secret-name", label, "--attempts", "1",
            ])
        return result, json.loads(output.getvalue()), fetch.call_count

    def test_default_selector_fingerprint_is_explicit_and_stable(self):
        expected = hashlib.sha256(b"latexy-modal-redis-binding:v1\0latexy-redis").hexdigest()
        self.assertEqual(redis_binding_fingerprint({}), expected)
        self.assertEqual(redis_binding_fingerprint({"MODAL_REDIS_SECRET_NAME": ""}), expected)
        self.assertEqual(redis_binding_fingerprint({"MODAL_REDIS_SECRET_NAME": "latexy-redis"}), expected)

    def test_alternate_selector_is_distinct_without_reading_credentials(self):
        selected = {"MODAL_REDIS_SECRET_NAME": "qa-redis-recovery"}
        value = redis_binding_fingerprint(selected)
        self.assertNotEqual(value, redis_binding_fingerprint({}))
        self.assertEqual(len(value), 64)
        self.assertEqual(value, redis_binding_fingerprint({**selected, "REDIS_PASSWORD": "dummy-changed"}))

    def test_invalid_selector_never_appears_in_health_metadata(self):
        for label in ("rediss://dummy@example.invalid", "label\nsecret", "x" * 65, " ", "../name"):
            self.assertIsNone(redis_binding_fingerprint({"MODAL_REDIS_SECRET_NAME": label}))

    def test_guard_accepts_matching_source_and_selector(self):
        for label in ("latexy-redis", "qa-redis-recovery"):
            fingerprint = redis_binding_fingerprint({"MODAL_REDIS_SECRET_NAME": label})
            code, report, calls = self.run_guard({"commit_sha": SHA, "redis_binding_fingerprint": fingerprint}, label)
            self.assertEqual((code, calls), (0, 1))
            self.assertEqual(report["redis_binding_fingerprint"], fingerprint)

    def test_changed_selector_cannot_release_same_source(self):
        code, report, _ = self.run_guard({
            "commit_sha": SHA,
            "redis_binding_fingerprint": redis_binding_fingerprint({"MODAL_REDIS_SECRET_NAME": "qa-redis-recovery"}),
        })
        self.assertEqual(code, 1)
        self.assertEqual(report["reason"], "serving_redis_binding_mismatch")

    def test_missing_or_malformed_binding_never_passes_source_only(self):
        for value in (None, "", "host-secret-value", ["invalid"]):
            code, report, _ = self.run_guard({"commit_sha": SHA, "redis_binding_fingerprint": value})
            self.assertEqual(code, 1)
            self.assertEqual(report["reason"], "serving_redis_binding_mismatch")
            self.assertNotIn("host-secret-value", json.dumps(report))

    def test_invalid_expected_selector_fails_before_network(self):
        code, report, calls = self.run_guard({}, "rediss://dummy@example.invalid")
        self.assertEqual((code, calls), (1, 0))
        self.assertEqual(report["reason"], "invalid_expected_redis_binding")

    def test_workflow_checks_selector_before_provider_operations_and_after_deploy(self):
        import yaml

        source = (BACKEND.parent / ".github" / "workflows" / "deploy-modal.yml").read_text(encoding="utf-8")
        workflow = yaml.safe_load(source)
        deploy = workflow["jobs"]["deploy"]
        self.assertEqual(deploy["env"]["MODAL_REDIS_SECRET_NAME"], "${{ vars.MODAL_REDIS_SECRET_NAME }}")
        steps = deploy["steps"]
        names = [step["name"] for step in steps]
        guard = "Validate held-only Redis binding before provider operations"
        self.assertLess(names.index(guard), names.index("Install pinned Modal CLI"))
        guard_step = steps[names.index(guard)]
        self.assertIn("deployment_traffic_held(source_deployment=True)", guard_step["run"])
        for name in ("Require approved SHA and healthy held candidate before release", "Verify serving backend revision"):
            script = steps[names.index(name)]["run"]
            self.assertIn('"${MODAL_REDIS_SECRET_NAME:-latexy-redis}"', script)
            self.assertIn("--expected-redis-secret-name", script)


if __name__ == "__main__":
    unittest.main()
