"""Require the actually-serving backend revision to match the deployed SHA.

``verify_modal_deployment_identity.py`` proves what was *deployed* by reading
Modal's app pointer and tag. It explicitly cannot prove that the containers
answering requests run that revision: production once served a backend 32
commits behind the pointer while the frontend, the pointer and every health
check all reported success.

``/health`` now publishes the validated ``DEPLOY_SHA`` baked into the serving
image. This script polls that field and fails unless the serving process reports
the exact expected commit, so a stale or partially-drained fleet cannot be
recorded as a successful release.

Only a bounded, non-secret health document is read. The report never echoes an
unexpected payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_MAX_BODY_BYTES = 64 * 1024
_SECRET_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _fetch_health(url: str, timeout: float) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-supplied deployment URL
        raw = response.read(_MAX_BODY_BYTES + 1)
    if len(raw) > _MAX_BODY_BYTES:
        raise ValueError("health response exceeded the bounded read")
    parsed = json.loads(raw.decode("utf-8", "replace"))
    if not isinstance(parsed, dict):
        raise ValueError("health response was not an object")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Backend base URL")
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-redis-secret-name", help="Nonsecret selector to attest alongside source")
    parser.add_argument("--attempts", type=int, default=18)
    parser.add_argument("--delay-seconds", type=float, default=10.0)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args(argv)

    expected = args.expected_sha.strip().lower()
    if not _GIT_SHA.fullmatch(expected):
        print(json.dumps({"status": "blocked", "reason": "invalid_expected_sha"}))
        return 1

    expected_binding = None
    if args.expected_redis_secret_name is not None:
        if not _SECRET_LABEL.fullmatch(args.expected_redis_secret_name):
            print(json.dumps({"status": "blocked", "reason": "invalid_expected_redis_binding"}))
            return 1
        expected_binding = hashlib.sha256(
            ("latexy-modal-redis-binding:v1\0" + args.expected_redis_secret_name).encode()
        ).hexdigest()

    endpoint = args.url.rstrip("/") + "/health"
    observed: str | None = None
    last_reason = "unreachable"

    for attempt in range(1, max(1, args.attempts) + 1):
        try:
            body = _fetch_health(endpoint, args.timeout_seconds)
        except (urllib.error.URLError, ValueError, OSError, TimeoutError):
            last_reason = "unreachable"
        else:
            reported = body.get("commit_sha")
            if isinstance(reported, str) and _GIT_SHA.fullmatch(reported.strip().lower()):
                observed = reported.strip().lower()
                if observed == expected:
                    if expected_binding is not None and body.get("redis_binding_fingerprint") != expected_binding:
                        last_reason = "serving_redis_binding_mismatch"
                        if attempt < args.attempts:
                            time.sleep(max(0.0, args.delay_seconds))
                        continue
                    print(json.dumps({
                        "status": "verified",
                        "source_sha": expected,
                        "serving_sha": observed,
                        "attempt": attempt,
                        **({"redis_binding_fingerprint": expected_binding} if expected_binding is not None else {}),
                    }, sort_keys=True))
                    return 0
                last_reason = "serving_revision_mismatch"
            else:
                last_reason = "serving_revision_unattested"

        if attempt < args.attempts:
            time.sleep(max(0.0, args.delay_seconds))

    report: dict[str, object] = {"status": "blocked", "reason": last_reason, "attempts": args.attempts}
    if observed is not None:
        report["serving_sha"] = observed
    print(json.dumps(report, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
