from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.serve_identity import redis_binding_fingerprint
from scripts.modal_operation_authorization import (
    KEY_ENV,
    OperationAuthorizationError,
    _redis_fingerprint,
    mint_proof,
    verify_proof,
)

KEY = "a" * 64
SHA = "b" * 40
APP_ID = "ap-abcdefghijklmnopqrstuv"
FREEZE = "11111111-2222-4333-8444-555555555555"
BACKEND = Path(__file__).resolve().parents[1]


def env(**updates):
    result = {
        KEY_ENV: KEY,
        "MODAL_ENVIRONMENT": "main",
        "MODAL_DEPLOYMENT_TRAFFIC_HOLD": "true",
        "DEPLOY_SHA": SHA,
        "MODAL_REDIS_SECRET_NAME": "latexy-redis-held",
        "MODAL_REDIS_RECOVERY_FREEZE_ID": FREEZE,
    }
    result.update(updates)
    return result


def issue(action="migrate", **kwargs):
    return mint_proof(action=action, sha=SHA, app_id=APP_ID,
                      redis_secret_name="latexy-redis-held",
                      freeze_id=FREEZE if action == "freeze" else "",
                      now=1000, environ=env(**kwargs))


@pytest.mark.parametrize("action", ["migrate", "freeze"])
def test_proof_verifies_only_for_exact_bounded_operation(action):
    token = issue(action)
    assert re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token)
    verify_proof(token, action=action, expected_freeze_id=FREEZE if action == "freeze" else "", environ=env(), now=1119)
    with pytest.raises(OperationAuthorizationError, match="authorization is invalid"):
        verify_proof(token, action=action, environ=env(), now=1120)
    with pytest.raises(OperationAuthorizationError):
        verify_proof(token, action="freeze" if action == "migrate" else "migrate", environ=env(), now=1001)


@pytest.mark.parametrize("changes", [
    {"DEPLOY_SHA": "c" * 40},
    {"MODAL_ENVIRONMENT": "dev"},
    {"MODAL_DEPLOYMENT_TRAFFIC_HOLD": "false"},
    {"MODAL_REDIS_SECRET_NAME": "latexy-redis"},
    {KEY_ENV: "f" * 64},
])
def test_proof_rejects_runtime_identity_or_binding_mismatch(changes):
    token = issue("migrate")
    with pytest.raises(OperationAuthorizationError):
        verify_proof(token, action="migrate", environ=env(**changes), now=1001)


def test_freeze_proof_binds_canonical_freeze_uuid():
    token = issue("freeze")
    with pytest.raises(OperationAuthorizationError):
        verify_proof(token, action="freeze", expected_freeze_id="66666666-2222-4333-8444-555555555555", environ=env(), now=1001)


@pytest.mark.parametrize("bad_key", [None, "", "A" * 64, "a" * 63, "a" * 64 + "a"])
def test_signer_requires_exact_lowercase_256_bit_hex(bad_key):
    with pytest.raises(OperationAuthorizationError, match="authorization is unavailable"):
        issue("migrate", **{KEY_ENV: bad_key})


def test_mint_requires_held_main_and_valid_app_id():
    with pytest.raises(OperationAuthorizationError):
        issue("migrate", MODAL_DEPLOYMENT_TRAFFIC_HOLD="false")
    with pytest.raises(OperationAuthorizationError):
        mint_proof(action="migrate", sha=SHA, app_id="bad", redis_secret_name="latexy-redis", now=1, environ=env())


def test_redis_fingerprint_matches_serving_identity_contract():
    token = issue()
    verify_proof(token, action="migrate", environ=env(), now=1001)
    body = token.split(".", 1)[0]
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    assert payload["redis_fingerprint"] == redis_binding_fingerprint(env())
    assert _redis_fingerprint("latexy-redis-held") == payload["redis_fingerprint"]


def test_tampered_malformed_and_oversized_tokens_fail_with_fixed_error():
    token = issue()
    for candidate in (token + "x", "garbage", "x" * 2049):
        with pytest.raises(OperationAuthorizationError, match="operation authorization is invalid"):
            verify_proof(candidate, action="migrate", environ=env(), now=1001)


def test_module_cli_works_from_backend_directory_without_pythonpath():
    child_env = dict(os.environ)
    child_env.pop("PYTHONPATH", None)
    child_env.update(env())
    minted = subprocess.run(
        [sys.executable, "-m", "scripts.modal_operation_authorization", "--action", "migrate",
         "--sha", SHA, "--app-id", APP_ID, "--redis-secret-name", "latexy-redis-held"],
        cwd=BACKEND, env=child_env, capture_output=True, text=True, check=False,
    )
    assert minted.returncode == 0, minted.stderr
    token = minted.stdout.strip()
    verified = subprocess.run(
        [sys.executable, "-c",
         "import sys; from scripts.modal_operation_authorization import verify_proof; "
         "verify_proof(sys.argv[1], action='migrate')", token],
        cwd=BACKEND, env=child_env, capture_output=True, text=True, check=False,
    )
    assert verified.returncode == 0, verified.stderr
