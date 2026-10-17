"""Read-only Modal Environment identity/binding inventory for renderer acceptance.

This command never creates, updates, deletes, deploys, or attaches Modal resources.
It reports the selected Environment ID, counts, and a safe inventory fingerprint;
it never prints Secret names or values. An empty inventory is evidence for review,
not an authorization to run the acceptance harness.
"""

from __future__ import annotations

import argparse
import json
import sys

from modal_spawn_acceptance import (
    HarnessFailure,
    read_functional_environment_inventory,
    validate_nonproduction_environment_name,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment-name", required=True)
    args = parser.parse_args(argv)
    try:
        validate_nonproduction_environment_name(args.environment_name)
    except HarnessFailure as failure:
        print(json.dumps({"status": "blocked", "failure_code": failure.failure_code}, sort_keys=True))
        return 2

    try:
        import modal
    except Exception:
        print(json.dumps({"status": "blocked", "failure_code": "modal_sdk_unavailable"}, sort_keys=True))
        return 2

    try:
        inventory = read_functional_environment_inventory(modal, args.environment_name)
    except HarnessFailure as failure:
        print(json.dumps({"status": "blocked", "failure_code": failure.failure_code}, sort_keys=True))
        return 2

    empty = not (inventory.secret_count or inventory.volume_count or inventory.active_app_count)
    print(json.dumps({
        "status": "empty_candidate_for_review" if empty else "blocked_nonempty",
        "environment_name": args.environment_name,
        "environment_object_id": inventory.environment_object_id,
        "secret_count": inventory.secret_count,
        "volume_count": inventory.volume_count,
        "active_app_count": inventory.active_app_count,
        "binding_manifest_sha256": inventory.binding_manifest_sha256,
        "approval_added": False,
    }, sort_keys=True))
    return 0 if empty else 2


if __name__ == "__main__":
    sys.exit(main())
