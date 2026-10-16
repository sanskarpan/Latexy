"""The post-deploy check must reject a stale or ambiguous Modal pointer."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace as Record

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_modal_deployment_identity.py"
spec = importlib.util.spec_from_file_location("verify_modal_deployment_identity", SCRIPT)
assert spec and spec.loader
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)
SHA = "a" * 40
OLD = "b" * 40
APP_ID = "ap-test"
DEPLOYED = 1


def records(*, production_version: int = 2, lifecycle_version: int = 2,
            tag: str = SHA, commit_sha: str = SHA, dirty: bool = False,
            state: int = DEPLOYED, environment: str = "main") -> tuple[Record, Record]:
    lookup = Record(app_id=APP_ID, environment_name=environment,
                    lifecycle=Record(app_state=state, version=lifecycle_version))
    history = Record(production_app_version=production_version, app_deployment_histories=[
        Record(app_id=APP_ID, version=2, tag=tag,
               commit_info=Record(commit_hash=commit_sha, dirty=dirty)),
        Record(app_id=APP_ID, version=1, tag=OLD,
               commit_info=Record(commit_hash=OLD, dirty=False)),
    ])
    return lookup, history


class ModalDeploymentIdentityTests(unittest.TestCase):
    def check(self, lookup: Record, history: Record) -> dict[str, object]:
        return identity.assess(lookup, history, environment="main", expected_sha=SHA,
                               deployed_state=DEPLOYED)

    def test_matching_production_pointer_and_clean_commit(self) -> None:
        report = self.check(*records())
        self.assertEqual(report["source_sha"], SHA)
        self.assertEqual(report["container_versions"], "unverified")

    def test_successful_no_change_deploy_cannot_certify_old_tag(self) -> None:
        with self.assertRaisesRegex(identity.ProvenanceBlocked, "source_identity_mismatch"):
            self.check(*records(tag=OLD, commit_sha=OLD))

    def test_tag_alone_does_not_certify_source(self) -> None:
        with self.assertRaisesRegex(identity.ProvenanceBlocked, "source_identity_mismatch"):
            self.check(*records(commit_sha=OLD))
        with self.assertRaisesRegex(identity.ProvenanceBlocked, "source_identity_mismatch"):
            self.check(*records(dirty=True))

    def test_rollback_pointer_to_older_history_does_not_use_newest_entry(self) -> None:
        with self.assertRaisesRegex(identity.ProvenanceBlocked, "source_identity_mismatch"):
            self.check(*records(production_version=1, lifecycle_version=1))

    def test_missing_or_conflicting_production_version_blocks(self) -> None:
        with self.assertRaisesRegex(identity.ProvenanceBlocked, "production_version_mismatch"):
            self.check(*records(production_version=0))
        with self.assertRaisesRegex(identity.ProvenanceBlocked, "production_version_mismatch"):
            self.check(*records(lifecycle_version=1))

    def test_wrong_app_or_environment_blocks(self) -> None:
        with self.assertRaisesRegex(identity.ProvenanceBlocked, "app_not_deployed"):
            self.check(*records(state=0))
        with self.assertRaisesRegex(identity.ProvenanceBlocked, "environment_mismatch"):
            self.check(*records(environment="dev"))

    def test_workflow_checks_pointer_before_followup_writes(self) -> None:
        workflow = (SCRIPT.parents[2] / ".github" / "workflows" / "deploy-modal.yml").read_text()
        deploy = workflow.index("- name: Deploy backend with a rolling update")
        verify = workflow.index("- name: Verify Modal production deployment identity")
        templates = workflow.index("- name: Synchronize source-owned production templates")
        self.assertLess(deploy, verify)
        self.assertLess(verify, templates)
        self.assertIn('verify_modal_deployment_identity.py --environment main --expected-sha "$DEPLOY_SHA"',
                      workflow[verify:templates])


if __name__ == "__main__":
    unittest.main()
