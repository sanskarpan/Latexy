"""Check Modal's production deployment pointer after a release.

This reads app metadata only. A matching pointer does not prove that every old
container has drained, nor does it attest the database revision.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re


class ProvenanceBlocked(Exception):
    """A fixed, safe-to-log reason for refusing a deployment identity."""


def assess(lookup: object, history: object, *, environment: str, expected_sha: str,
           deployed_state: int) -> dict[str, object]:
    """Require the production pointer, tag and clean source commit to agree."""
    if getattr(lookup, "environment_name", None) != environment:
        raise ProvenanceBlocked("environment_mismatch")
    app_id = getattr(lookup, "app_id", "")
    lifecycle = getattr(lookup, "lifecycle", None)
    if not app_id or getattr(lifecycle, "app_state", None) != deployed_state:
        raise ProvenanceBlocked("app_not_deployed")
    version = getattr(history, "production_app_version", 0)
    if not isinstance(version, int) or version <= 0 or getattr(lifecycle, "version", None) != version:
        raise ProvenanceBlocked("production_version_mismatch")
    matches = [entry for entry in getattr(history, "app_deployment_histories", ())
               if getattr(entry, "version", None) == version and getattr(entry, "app_id", None) == app_id]
    if len(matches) != 1:
        raise ProvenanceBlocked("production_history_missing_or_ambiguous")
    entry = matches[0]
    commit = getattr(entry, "commit_info", None)
    if (getattr(entry, "tag", None) != expected_sha
            or getattr(commit, "commit_hash", None) != expected_sha
            or getattr(commit, "dirty", True) is not False):
        raise ProvenanceBlocked("source_identity_mismatch")
    return {
        "status": "verified",
        "environment": environment,
        "app_id": app_id,
        "production_app_version": version,
        "source_sha": expected_sha,
        "container_versions": "unverified",
    }


async def fetch_metadata(app_name: str, environment: str) -> tuple[object, object, int]:
    # These are the read-only API calls used by Modal CLI's app lookup/history.
    from modal.client import _Client
    from modal_proto import api_pb2

    client = await _Client.from_env()
    lookup = await client.stub.AppGetByDeploymentName(
        api_pb2.AppGetByDeploymentNameRequest(name=app_name, environment_name=environment)
    )
    if not lookup.app_id:
        raise ProvenanceBlocked("app_not_deployed")
    history = await client.stub.AppDeploymentHistory(
        api_pb2.AppDeploymentHistoryRequest(app_id=lookup.app_id)
    )
    return lookup, history, api_pb2.APP_STATE_DEPLOYED


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", default="latexy-backend")
    parser.add_argument("--environment", default="main")
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha):
        print(json.dumps({"status": "blocked", "reason": "invalid_expected_sha"}))
        return 1
    try:
        lookup, history, deployed_state = asyncio.run(fetch_metadata(args.app, args.environment))
        report = assess(lookup, history, environment=args.environment,
                        expected_sha=args.expected_sha, deployed_state=deployed_state)
    except ProvenanceBlocked as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}))
        return 1
    except Exception:
        # Never print an exception from the authenticated client: it may include
        # request metadata or a credential-bearing environment value.
        print(json.dumps({"status": "blocked", "reason": "modal_metadata_unavailable"}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
