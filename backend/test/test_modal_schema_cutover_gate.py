"""Executable, dependency-free rejection tests for the pre-migration gate."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_modal_schema_cutover.py"
spec = importlib.util.spec_from_file_location("check_modal_schema_cutover", SCRIPT)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

DEPLOY = "a" * 40
RECOVERY = "b" * 40
ENV = {
    "DEPLOY_SHA": DEPLOY,
    "MODAL_SCHEMA_CUTOVER_APPROVED_SHA": DEPLOY,
    "MODAL_FORWARD_ROLLBACK_SHA": RECOVERY,
    "MODAL_RECOVERY_VERIFIED_FOR_SHA": DEPLOY,
    "GITHUB_REPOSITORY": "sanskarpan/Latexy",
}


class FakeRunner:
    def __init__(self, **overrides):
        self.calls = []
        self.overrides = overrides

    def __call__(self, args):
        self.calls.append(list(args))
        if args[:3] == ["git", "merge-base", "--is-ancestor"]:
            kind = "ancestor"
            output = ""
        elif args[:2] == ["git", "show"]:
            kind = "routes" if args[2].endswith("resume_routes.py") else "billing"
            output = gate.ACCEPTED_FILTER * 2 if kind == "routes" else "Dodo-only service"
        else:
            kind = "ci"
            output = json.dumps({"workflow_runs": [{"head_sha": RECOVERY, "head_branch": "main",
                                                    "status": "completed", "conclusion": "success"}]})
        replacement = self.overrides.get(kind)
        if isinstance(replacement, Exception):
            raise replacement
        if replacement is not None:
            return replacement
        return subprocess.CompletedProcess(args, 0, output, "")


def response(code=0, output=""):
    return subprocess.CompletedProcess([], code, output, "")


class SchemaCutoverGateTests(unittest.TestCase):
    def test_valid_distinct_ancestor_with_ci_and_attestation_passes(self):
        runner = FakeRunner()
        gate.validate(ENV, runner)
        self.assertEqual(len(runner.calls), 4)
        self.assertEqual(runner.calls[0], ["git", "merge-base", "--is-ancestor", RECOVERY, DEPLOY])
        self.assertIn(f"head_sha={RECOVERY}&branch=main", runner.calls[-1][2])

    def test_missing_mismatched_and_stale_approval_stop_before_io(self):
        for value in (None, RECOVERY, "c" * 40):
            with self.subTest(value=value):
                env = ENV.copy()
                if value is None:
                    env.pop("MODAL_SCHEMA_CUTOVER_APPROVED_SHA")
                else:
                    env["MODAL_SCHEMA_CUTOVER_APPROVED_SHA"] = value
                runner = FakeRunner()
                with self.assertRaisesRegex(gate.CutoverBlocked, "approval"):
                    gate.validate(env, runner)
                self.assertEqual(runner.calls, [])

    def test_missing_or_stale_recovery_attestation_stops_before_io(self):
        for value in (None, RECOVERY, "c" * 40):
            with self.subTest(value=value):
                env = ENV.copy()
                if value is None:
                    env.pop("MODAL_RECOVERY_VERIFIED_FOR_SHA")
                else:
                    env["MODAL_RECOVERY_VERIFIED_FOR_SHA"] = value
                runner = FakeRunner()
                with self.assertRaisesRegex(gate.CutoverBlocked, "attestation"):
                    gate.validate(env, runner)
                self.assertEqual(runner.calls, [])

    def test_malformed_or_candidate_as_recovery_is_rejected(self):
        for recovery in ("", "not-a-sha", "B" * 40, DEPLOY):
            with self.subTest(recovery=recovery):
                runner = FakeRunner()
                with self.assertRaisesRegex(gate.CutoverBlocked, "Distinct recovery"):
                    gate.validate(ENV | {"MODAL_FORWARD_ROLLBACK_SHA": recovery}, runner)
                self.assertEqual(runner.calls, [])

    def test_non_ancestor_or_git_error_is_rejected(self):
        for result in (response(1), response(128)):
            with self.subTest(code=result.returncode):
                runner = FakeRunner(ancestor=result)
                with self.assertRaisesRegex(gate.CutoverBlocked, "not an ancestor"):
                    gate.validate(ENV, runner)
                self.assertEqual(len(runner.calls), 1)

    def test_missing_recovery_files_are_rejected(self):
        for kind, count in (("routes", 2), ("billing", 3)):
            with self.subTest(kind=kind):
                runner = FakeRunner(**{kind: response(128)})
                with self.assertRaisesRegex(gate.CutoverBlocked, "source is unavailable"):
                    gate.validate(ENV, runner)
                self.assertEqual(len(runner.calls), count)

    def test_unsafe_source_is_rejected_before_ci_lookup(self):
        for kind, source in (("routes", "completed-only reader"),
                             ("billing", "razorpay_payment_id")):
            with self.subTest(kind=kind):
                runner = FakeRunner(**{kind: response(output=source)})
                with self.assertRaisesRegex(gate.CutoverBlocked, "minimum compatibility"):
                    gate.validate(ENV, runner)
                self.assertEqual(len(runner.calls), 3)

    def test_failed_empty_wrong_or_malformed_ci_lookup_is_rejected(self):
        payloads = (
            response(1), response(output=""), response(output="not-json"),
            response(output=json.dumps({"workflow_runs": []})),
            response(output=json.dumps({"workflow_runs": [{"head_sha": RECOVERY,
                                                            "head_branch": "main", "status": "completed",
                                                            "conclusion": "failure"}]})),
            response(output=json.dumps({"workflow_runs": [{"head_sha": "c" * 40,
                                                            "head_branch": "main", "status": "completed",
                                                            "conclusion": "success"}]})),
        )
        for result in payloads:
            with self.subTest(output=result.stdout, code=result.returncode):
                runner = FakeRunner(ci=result)
                with self.assertRaises(gate.CutoverBlocked):
                    gate.validate(ENV, runner)
                self.assertEqual(len(runner.calls), 4)

    def test_command_timeout_is_rejected(self):
        runner = FakeRunner(ci=subprocess.TimeoutExpired(["gh", "api"], 20))
        with self.assertRaisesRegex(gate.CutoverBlocked, "lookup failed"):
            gate.validate(ENV, runner)


if __name__ == "__main__":
    unittest.main()
