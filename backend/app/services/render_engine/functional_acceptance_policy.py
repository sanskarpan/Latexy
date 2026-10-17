"""Reviewed identity policy for the nonproduction renderer functional harness.

An environment name or CLI acknowledgement is not evidence of isolation. Entries
must bind a Modal Environment object ID to a freshly observed, empty binding
manifest and a reviewable evidence reference. The tuple is intentionally empty
until a read-only inventory has been reviewed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FunctionalAcceptanceEnvironmentApproval:
    """A source-reviewed environment identity and binding-inventory approval."""

    name: str
    environment_object_id: str
    binding_manifest_sha256: str
    evidence_ref: str


# Populate only through a reviewed source change after verifying the exact
# Environment object ID and an empty Secrets/Volumes/live-Apps inventory. Never
# add the quarantined billing environment or the unverified synthetic environment
# by name alone.
TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS: tuple[FunctionalAcceptanceEnvironmentApproval, ...] = ()

_ENVIRONMENT_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_EVIDENCE_REF = re.compile(r"[A-Za-z0-9_.:/#=-]{1,240}\Z")


def functional_environment_inventory_sha256(
    name: str,
    environment_object_id: str,
    *,
    secret_identities: tuple[tuple[str, str], ...] = (),
    volume_identities: tuple[tuple[str, str], ...] = (),
    active_app_identities: tuple[tuple[str, str], ...] = (),
) -> str:
    """Hash safe Modal object identities for a read-only Environment inventory.

    Names and IDs are included in the digest but are never required in a report.
    The inventory reader rejects malformed identity records and callers separately
    require all three resource collections to be empty before functional use.
    """
    material = {
        "schema": "latexy-functional-environment-inventory-v1",
        "environment": {"name": name, "object_id": environment_object_id},
        "secrets": sorted([list(item) for item in secret_identities]),
        "volumes": sorted([list(item) for item in volume_identities]),
        "active_apps": sorted([list(item) for item in active_app_identities]),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _complete_approval(entry: FunctionalAcceptanceEnvironmentApproval) -> bool:
    return (
        isinstance(entry.name, str)
        and bool(_ENVIRONMENT_NAME.fullmatch(entry.name))
        and isinstance(entry.environment_object_id, str)
        and 1 <= len(entry.environment_object_id) <= 128
        and not any(ord(char) < 32 for char in entry.environment_object_id)
        and isinstance(entry.binding_manifest_sha256, str)
        and bool(_SHA256.fullmatch(entry.binding_manifest_sha256))
        and isinstance(entry.evidence_ref, str)
        and bool(_SAFE_EVIDENCE_REF.fullmatch(entry.evidence_ref))
    )


def get_functional_acceptance_environment_approval(
    name: object,
) -> FunctionalAcceptanceEnvironmentApproval | None:
    """Return one complete source-reviewed entry for ``name``; otherwise fail closed."""
    if not isinstance(name, str):
        return None
    matches = [
        entry for entry in TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS
        if isinstance(entry, FunctionalAcceptanceEnvironmentApproval) and entry.name == name
    ]
    if len(matches) != 1 or not _complete_approval(matches[0]):
        return None
    return matches[0]


def is_trusted_functional_acceptance_environment(
    name: object,
    environment_object_id: object,
    binding_manifest_sha256: object,
) -> bool:
    """Require exact reviewed name, Modal object identity, and inventory digest."""
    approval = get_functional_acceptance_environment_approval(name)
    return bool(
        approval
        and environment_object_id == approval.environment_object_id
        and binding_manifest_sha256 == approval.binding_manifest_sha256
    )
