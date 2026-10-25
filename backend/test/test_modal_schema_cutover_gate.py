"""Executable, dependency-free rejection tests for the pre-migration gate."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_modal_schema_cutover.py"
BACKEND = SCRIPT.parents[1]
RECOVERY_SOURCE = (BACKEND / "app" / "services" / "job_result_recovery.py").read_text(encoding="utf-8")
PUBLIC_API_SOURCE = (BACKEND / "app" / "api" / "public_api_routes.py").read_text(encoding="utf-8")
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
            if args[2].endswith("resume_routes.py"):
                kind, output = "routes", gate.ACCEPTED_FILTER * 2
            elif args[2].endswith("payment_service.py"):
                kind, output = "billing", "Dodo-only service"
            elif args[2].endswith("job_result_recovery.py"):
                kind, output = "recovery", RECOVERY_SOURCE
            else:
                kind, output = "public_api", PUBLIC_API_SOURCE
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
    def test_approvals_only_accepts_inputs_without_runner_subprocess_or_network_calls(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (patch.dict(gate.os.environ, ENV, clear=True),
              patch.object(gate, "validate") as full_gate,
              patch.object(gate, "_run") as runner,
              patch.object(gate.subprocess, "run") as subprocess_run,
              patch.object(gate.subprocess, "Popen") as subprocess_popen,
              patch("socket.socket") as socket,
              patch("socket.create_connection") as connect,
              redirect_stdout(stdout), redirect_stderr(stderr)):
            self.assertEqual(gate.main(["--approvals-only"]), 0)
        for forbidden in (full_gate, runner, subprocess_run, subprocess_popen, socket, connect):
            forbidden.assert_not_called()
        self.assertEqual(stdout.getvalue(), "Approval inputs accepted; recovery and drain remain unverified\n")
        self.assertEqual(stderr.getvalue(), "")

    def test_approvals_only_rejects_invalid_inputs_without_io_or_echoing_values(self):
        invalid_inputs = (
            ("DEPLOY_SHA", None), ("DEPLOY_SHA", "synthetic-private-invalid-candidate"),
            ("MODAL_SCHEMA_CUTOVER_APPROVED_SHA", None),
            ("MODAL_SCHEMA_CUTOVER_APPROVED_SHA", RECOVERY),
            ("MODAL_FORWARD_ROLLBACK_SHA", None),
            ("MODAL_FORWARD_ROLLBACK_SHA", "synthetic-private-invalid-recovery"),
            ("MODAL_FORWARD_ROLLBACK_SHA", "B" * 40),
            ("MODAL_FORWARD_ROLLBACK_SHA", DEPLOY),
            ("MODAL_RECOVERY_VERIFIED_FOR_SHA", None),
            ("MODAL_RECOVERY_VERIFIED_FOR_SHA", RECOVERY),
            ("GITHUB_REPOSITORY", None),
            ("GITHUB_REPOSITORY", "synthetic-private-invalid-repository"),
        )
        for key, value in invalid_inputs:
            with self.subTest(key=key, value=value):
                env = ENV.copy()
                if value is None:
                    del env[key]
                else:
                    env[key] = value
                stdout, stderr = io.StringIO(), io.StringIO()
                with (patch.dict(gate.os.environ, env, clear=True),
                      patch.object(gate, "validate") as full_gate,
                      patch.object(gate, "_run") as runner,
                      patch.object(gate.subprocess, "run") as subprocess_run,
                      patch.object(gate.subprocess, "Popen") as subprocess_popen,
                      patch("socket.socket") as socket,
                      patch("socket.create_connection") as connect,
                      redirect_stdout(stdout), redirect_stderr(stderr)):
                    self.assertEqual(gate.main(["--approvals-only"]), 1)
                for forbidden in (full_gate, runner, subprocess_run, subprocess_popen, socket, connect):
                    forbidden.assert_not_called()
                self.assertEqual(stdout.getvalue(), "")
                self.assertTrue(stderr.getvalue().startswith("Modal schema cutover blocked: "))
                for supplied in (*env.values(), "synthetic-private"):
                    self.assertNotIn(supplied, stdout.getvalue() + stderr.getvalue())

    def test_default_cli_retains_all_source_and_ci_checks(self):
        runner = FakeRunner()
        stdout = io.StringIO()
        with (patch.dict(gate.os.environ, ENV, clear=True),
              patch.object(gate, "_run", runner), redirect_stdout(stdout)):
            self.assertEqual(gate.main([]), 0)
        self.assertEqual(len(runner.calls), 6)
        self.assertEqual(runner.calls[-1][0:2], ["gh", "api"])
        self.assertEqual(stdout.getvalue(),
                         "Modal schema cutover source and CI checks passed; operator attestations supplied\n")

    def test_valid_distinct_ancestor_with_ci_and_attestation_passes(self):
        runner = FakeRunner()
        gate.validate(ENV, runner)
        self.assertEqual(len(runner.calls), 6)
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
        for kind, count in (("routes", 2), ("billing", 3), ("recovery", 4), ("public_api", 5)):
            with self.subTest(kind=kind):
                runner = FakeRunner(**{kind: response(128)})
                with self.assertRaisesRegex(gate.CutoverBlocked, "source is unavailable"):
                    gate.validate(ENV, runner)
                self.assertEqual(len(runner.calls), count)

    def test_unsafe_source_is_rejected_before_ci_lookup(self):
        for kind, source in (("routes", "completed-only reader"),
                             ("billing", "razorpay_payment_id"),
                             ("recovery", "completed pointer without acceptance"),
                             ("public_api", "unfenced Redis fallback")):
            with self.subTest(kind=kind):
                runner = FakeRunner(**{kind: response(output=source)})
                with self.assertRaisesRegex(gate.CutoverBlocked, "minimum compatibility"):
                    gate.validate(ENV, runner)
                self.assertEqual(len(runner.calls), 5)

    def test_pre_1903_public_readers_are_rejected_before_ci_lookup(self):
        # #1901 has the terminal acceptance guard but falls back to live Redis
        # for pending/committing or expired durable rows. Keep that shape red.
        pre_1903 = (PUBLIC_API_SOURCE
                    .replace(gate.PUBLIC_STATUS_DURABLE_GUARD, "")
                    .replace(gate.PUBLIC_PDF_DURABLE_GUARD, "if False:"))
        self.assertNotEqual(pre_1903, PUBLIC_API_SOURCE)
        runner = FakeRunner(public_api=response(output=pre_1903))
        with self.assertRaisesRegex(gate.CutoverBlocked, "minimum compatibility"):
            gate.validate(ENV, runner)
        self.assertEqual(len(runner.calls), 5)

    def test_each_durable_authority_guard_is_required(self):
        variants = (
            ("recovery", RECOVERY_SOURCE, gate.PUBLIC_DURABLE_ROW_QUERY,
             'select(JobFinalization.id).where(JobFinalization.job_id == job_id, JobFinalization.state == "completed").limit(1)'),
            ("public_api", PUBLIC_API_SOURCE, gate.PUBLIC_DURABLE_HELPER_GUARD, "return True"),
            ("public_api", PUBLIC_API_SOURCE, gate.PUBLIC_STATUS_DURABLE_GUARD, ""),
            ("public_api", PUBLIC_API_SOURCE, gate.PUBLIC_PDF_DURABLE_GUARD, "if False:"),
            ("public_api", PUBLIC_API_SOURCE, 'raise HTTPException(status_code=503',
             'raise HTTPException(status_code=500'),
        )
        for kind, source, guard, replacement in variants:
            with self.subTest(kind=kind, guard=guard):
                self.assertIn(guard, source)
                runner = FakeRunner(**{kind: response(output=source.replace(guard, replacement))})
                with self.assertRaisesRegex(gate.CutoverBlocked, "minimum compatibility"):
                    gate.validate(ENV, runner)
                self.assertEqual(len(runner.calls), 5)

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
                self.assertEqual(len(runner.calls), 6)

    def test_command_timeout_is_rejected(self):
        runner = FakeRunner(ci=subprocess.TimeoutExpired(["gh", "api"], 20))
        with self.assertRaisesRegex(gate.CutoverBlocked, "lookup failed"):
            gate.validate(ENV, runner)


if __name__ == "__main__":
    unittest.main()
