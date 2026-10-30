"""Short-lived authorization proofs for held production Modal operations.

The signer key is shared only between the protected Production workflow and
the two remote database cutover functions. Proofs attest a recent external
drain check; they do not make that observation atomic with the operation.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
from collections.abc import Mapping

from app.core.deployment_hold import modal_redis_secret_name

KEY_ENV = "MODAL_RECOVERY_OPERATION_SIGNING_KEY"
MAX_TTL_SECONDS = 120
_SHA = re.compile(r"^[0-9a-f]{40}$")
_APP_ID = re.compile(r"^ap-[A-Za-z0-9]{22}$")
_FREEZE_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_HEX_KEY = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = frozenset({"v", "action", "sha", "environment", "app_id", "redis_fingerprint", "freeze_id", "issued_at", "expires_at"})
_DOMAIN = b"latexy-modal-operation-authorization:v1\0"


class OperationAuthorizationError(ValueError):
    """Fixed, safe authorization error suitable for logs."""


def _key(value: str | None) -> bytes:
    if not isinstance(value, str) or not _HEX_KEY.fullmatch(value):
        raise OperationAuthorizationError("operation authorization is unavailable")
    return bytes.fromhex(value)


def _canonical(payload: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise OperationAuthorizationError("operation authorization is invalid") from exc


def _redis_fingerprint(label: str) -> str:
    try:
        label = modal_redis_secret_name(label)
    except (TypeError, ValueError) as exc:
        raise OperationAuthorizationError("operation authorization is invalid") from exc
    return hashlib.sha256(b"latexy-modal-redis-binding:v1\0" + label.encode("ascii")).hexdigest()


def mint_proof(*, action: str, sha: str, app_id: str, redis_secret_name: str,
               freeze_id: str = "", now: int | None = None,
               environ: Mapping[str, str] | None = None) -> str:
    source = environ if environ is not None else os.environ
    if action not in {"migrate", "freeze"} or not _SHA.fullmatch(sha) or not _APP_ID.fullmatch(app_id):
        raise OperationAuthorizationError("operation authorization is invalid")
    if source.get("MODAL_ENVIRONMENT") != "main" or source.get("MODAL_DEPLOYMENT_TRAFFIC_HOLD") != "true":
        raise OperationAuthorizationError("operation authorization requires held main deployment")
    if action == "freeze" and not _FREEZE_ID.fullmatch(freeze_id):
        raise OperationAuthorizationError("operation authorization is invalid")
    if action == "migrate" and freeze_id:
        raise OperationAuthorizationError("operation authorization is invalid")
    issued = int(time.time()) if now is None else now
    payload = {
        "v": 1, "action": action, "sha": sha, "environment": "main", "app_id": app_id,
        "redis_fingerprint": _redis_fingerprint(redis_secret_name),
        "freeze_id": freeze_id, "issued_at": issued, "expires_at": issued + MAX_TTL_SECONDS,
    }
    body = _canonical(payload)
    signature = hmac.new(_key(source.get(KEY_ENV)), _DOMAIN + body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body).rstrip(b"=").decode("ascii") + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def verify_proof(token: str, *, action: str, expected_freeze_id: str = "", environ: Mapping[str, str] | None = None,
                 now: int | None = None) -> None:
    source = environ if environ is not None else os.environ
    try:
        if source.get("MODAL_ENVIRONMENT") != "main" or source.get("MODAL_DEPLOYMENT_TRAFFIC_HOLD") != "true":
            raise OperationAuthorizationError("operation authorization requires held main deployment")
        if action not in {"migrate", "freeze"} or len(token) > 2048 or token.count(".") != 1:
            raise OperationAuthorizationError("operation authorization is invalid")
        body_part, signature_part = token.split(".")
        body = base64.urlsafe_b64decode(body_part + "=" * (-len(body_part) % 4))
        signature = base64.urlsafe_b64decode(signature_part + "=" * (-len(signature_part) % 4))
        if (base64.urlsafe_b64encode(body).rstrip(b"=").decode("ascii") != body_part
                or base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii") != signature_part):
            raise OperationAuthorizationError("operation authorization is invalid")
        payload = json.loads(body.decode("ascii"))
        if not isinstance(payload, dict) or set(payload) != _FIELDS or _canonical(payload) != body:
            raise OperationAuthorizationError("operation authorization is invalid")
        expected = hmac.new(_key(source.get(KEY_ENV)), _DOMAIN + body, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise OperationAuthorizationError("operation authorization is invalid")
        current = int(time.time()) if now is None else now
        issued, expires = payload["issued_at"], payload["expires_at"]
        if (type(payload["v"]) is not int or payload["v"] != 1 or payload["action"] != action or payload["environment"] != "main"
                or not isinstance(issued, int) or isinstance(issued, bool)
                or not isinstance(expires, int) or isinstance(expires, bool)
                or issued > current or expires <= current or expires - issued != MAX_TTL_SECONDS
                or not _SHA.fullmatch(payload["sha"]) or payload["sha"] != source.get("DEPLOY_SHA")
                or not _APP_ID.fullmatch(payload["app_id"])
                or payload["redis_fingerprint"] != _redis_fingerprint(source.get("MODAL_REDIS_SECRET_NAME", "latexy-redis") or "latexy-redis")):
            raise OperationAuthorizationError("operation authorization is invalid")
        if action == "freeze":
            if (not _FREEZE_ID.fullmatch(payload["freeze_id"])
                    or not _FREEZE_ID.fullmatch(expected_freeze_id)
                    or payload["freeze_id"] != expected_freeze_id):
                raise OperationAuthorizationError("operation authorization is invalid")
        elif payload["freeze_id"] != "":
            raise OperationAuthorizationError("operation authorization is invalid")
    except OperationAuthorizationError:
        raise
    except Exception as exc:
        raise OperationAuthorizationError("operation authorization is invalid") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("migrate", "freeze"), required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--redis-secret-name", default="latexy-redis")
    parser.add_argument("--freeze-id", default="")
    args = parser.parse_args(argv)
    try:
        print(mint_proof(action=args.action, sha=args.sha, app_id=args.app_id,
                         redis_secret_name=args.redis_secret_name, freeze_id=args.freeze_id))
    except OperationAuthorizationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
