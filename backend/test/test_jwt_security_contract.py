"""Pure JWT dependency and application-boundary regressions.

These tests intentionally avoid the database and the FastAPI client.  The
application only accepts a raw, configured HS256 secret for its migration-only
JWT fallback; the dependency-level JWK/PEM controls are tested separately so
future auth work cannot accidentally widen that boundary.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from importlib.metadata import version

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from packaging.version import Version

_SECRET = b"test_jwt_security_contract_secret_with_more_than_48_bytes"


def _b64url(value: bytes) -> bytes:
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def _hs256_token(key: bytes) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps({"sub": "jwt-contract", "exp": int(time.time()) + 300}, separators=(",", ":")).encode()
    )
    signing_input = header + b"." + payload
    signature = _b64url(hmac.new(key, signing_input, hashlib.sha256).digest())
    return b".".join((header, payload, signature)).decode()


def test_pyjwt_version_is_patched_for_jwk_and_key_confusion_advisories():
    assert Version(version("PyJWT")) >= Version("2.14.0")


def test_pyjwt_rejects_empty_hmac_jwk_key():
    token = _hs256_token(b"")

    with pytest.raises(jwt.InvalidKeyError):
        empty_jwk = jwt.PyJWK({"kty": "oct", "k": ""}, algorithm="HS256")
        jwt.decode(token, empty_jwk, algorithms=["HS256"])


def test_pyjwt_rejects_public_pem_as_hmac_key_under_mixed_allowlist():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    canonical_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    mutations = {
        "marker-adjacent whitespace": canonical_pem.replace(b"-----END PUBLIC KEY-----", b"\t-----END PUBLIC KEY-----"),
        "CR-only line endings": canonical_pem.replace(b"\n", b"\r"),
        "folded single line": canonical_pem.replace(b"\n", b""),
    }
    for label, public_pem in mutations.items():
        serialization.load_pem_public_key(public_pem)
        with pytest.raises(jwt.InvalidKeyError, match="asymmetric|HMAC"):
            jwt.decode(
                _hs256_token(public_pem),
                public_pem,
                algorithms=["RS256", "HS256"],
            )


def test_pyjwt_rejects_public_jwk_json_as_hmac_key_under_mixed_allowlist():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key())
    public_jwk_bytes = public_jwk.encode("utf-8")

    with pytest.raises(jwt.InvalidKeyError):
        jwt.decode(
            _hs256_token(public_jwk_bytes),
            public_jwk,
            algorithms=["RS256", "HS256"],
        )


def test_legacy_validator_keeps_raw_hs256_expiry_boundary(monkeypatch):
    from app.middleware import auth_middleware

    observed: dict[str, object] = {}

    def fake_decode(token, key, **kwargs):
        observed.update(token=token, key=key, **kwargs)
        return {"sub": "jwt-contract"}

    monkeypatch.setattr(auth_middleware.jwt, "decode", fake_decode)
    validator = auth_middleware._LegacyJWTValidator(_SECRET.decode())

    assert validator.user_id("opaque-token") == "jwt-contract"
    assert observed == {
        "token": "opaque-token",
        "key": _SECRET.decode(),
        "algorithms": ["HS256"],
        "options": {"require": ["exp"], "verify_exp": True},
    }


def test_legacy_validator_accepts_valid_hs256_token_only():
    from app.middleware.auth_middleware import _LegacyJWTValidator

    token = _hs256_token(_SECRET)
    assert _LegacyJWTValidator(_SECRET.decode()).user_id(token) == "jwt-contract"


def test_legacy_validator_rejects_missing_exp_expired_wrong_secret_and_other_algs():
    from app.middleware.auth_middleware import _LegacyJWTValidator

    validator = _LegacyJWTValidator(_SECRET.decode())
    missing_exp = jwt.encode({"sub": "jwt-contract"}, _SECRET, algorithm="HS256")
    expired = jwt.encode(
        {"sub": "jwt-contract", "exp": int(time.time()) - 1},
        _SECRET,
        algorithm="HS256",
    )
    wrong_secret = _hs256_token(b"a-different-secret-that-is-long-enough")
    hs384 = jwt.encode(
        {"sub": "jwt-contract", "exp": int(time.time()) + 300},
        _SECRET,
        algorithm="HS384",
    )
    none = jwt.encode(
        {"sub": "jwt-contract", "exp": int(time.time()) + 300},
        key=None,
        algorithm="none",
    )

    for token in (missing_exp, expired, wrong_secret, hs384, none):
        assert validator.user_id(token) is None
