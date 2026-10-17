"""Select and validate the two supported Modal deployment phases."""

from __future__ import annotations

import argparse
import json
import re
import sys
from enum import StrEnum
from typing import Sequence


class DeploymentPhase(StrEnum):
    HELD_CUTOVER = "held-cutover"
    HELD_RELEASE = "held-release"


class DeploymentPhaseError(ValueError):
    """The event, input, or release attestations do not authorize a phase."""


_SHA = re.compile(r"^[0-9a-f]{40}$")


def resolve_phase(event_name: str, traffic_mode: str) -> DeploymentPhase:
    """Map supported GitHub events to a single explicit deployment phase."""
    if event_name == "workflow_run" and traffic_mode == "":
        return DeploymentPhase.HELD_CUTOVER
    if event_name == "workflow_dispatch" and traffic_mode == "held":
        return DeploymentPhase.HELD_CUTOVER
    if event_name == "workflow_dispatch" and traffic_mode == "release":
        return DeploymentPhase.HELD_RELEASE
    raise DeploymentPhaseError("unsupported event/traffic-mode combination")


def authorize_release(
    *,
    event_name: str,
    traffic_mode: str,
    candidate_sha: str,
    approved_sha: str,
    observed_sha: str,
    held_health_verified: bool,
) -> dict[str, str]:
    """Require the exact approved candidate to be deployed and healthy-held."""
    phase = resolve_phase(event_name, traffic_mode)
    if phase is not DeploymentPhase.HELD_RELEASE:
        raise DeploymentPhaseError("release authorization requires the manual release phase")
    if not _SHA.fullmatch(candidate_sha):
        raise DeploymentPhaseError("candidate SHA is invalid")
    if approved_sha != candidate_sha:
        raise DeploymentPhaseError("release approval does not match candidate SHA")
    if observed_sha != candidate_sha:
        raise DeploymentPhaseError("deployed held candidate does not match candidate SHA")
    if held_health_verified is not True:
        raise DeploymentPhaseError("fresh held health checks have not passed")
    return {
        "phase": phase.value,
        "candidate_sha": candidate_sha,
        "status": "release_authorized",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser("resolve")
    resolve.add_argument("--event-name", required=True)
    resolve.add_argument("--traffic-mode", default="")

    release = subparsers.add_parser("authorize-release")
    release.add_argument("--event-name", required=True)
    release.add_argument("--traffic-mode", required=True)
    release.add_argument("--candidate-sha", required=True)
    release.add_argument("--approved-sha", required=True)
    release.add_argument("--observed-sha", required=True)
    release.add_argument("--held-health-verified", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "resolve":
            phase = resolve_phase(args.event_name, args.traffic_mode)
            print(f"phase={phase.value}")
            return 0

        report = authorize_release(
            event_name=args.event_name,
            traffic_mode=args.traffic_mode,
            candidate_sha=args.candidate_sha,
            approved_sha=args.approved_sha,
            observed_sha=args.observed_sha,
            held_health_verified=args.held_health_verified,
        )
    except DeploymentPhaseError as exc:
        print(f"Modal deployment phase refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
