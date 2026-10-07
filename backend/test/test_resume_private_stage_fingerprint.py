from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings
from app.services.resume_engine.credential_scope import credential_scope
from app.services.resume_engine.stages import (
    OptimizationCheckpoint,
    StageCheckpointError,
    private_stage_context_fingerprint,
    stage_fingerprint,
)

_FIXED_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
_CONTEXT = {
    "source": "synthetic resume text",
    "job_description": "synthetic job requirement",
    "instructions": "synthetic private direction",
    "credential_scope": "synthetic keyed scope",
}


def test_credential_scope_matches_previous_stdlib_hmac_bytes(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", _FIXED_KEY)
    api_key = "synthetic-provider-key"
    material = base64.urlsafe_b64decode(_FIXED_KEY)
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"latexy/resume-engine/credential-scope/hkdf-salt/v1",
        info=b"latexy/resume-engine/credential-scope/hmac-key/v1",
    ).derive(material)
    previous_stdlib_result = hmac.new(
        derived,
        b"latexy/resume-engine/credential-scope/v1\x00" + api_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert credential_scope(api_key) == previous_stdlib_result
    assert credential_scope(api_key) == credential_scope(api_key)


def test_private_stage_context_is_canonical_and_sensitive_to_fields(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", _FIXED_KEY)
    reordered = dict(reversed(list(_CONTEXT.items())))

    fingerprint = private_stage_context_fingerprint(_CONTEXT)
    assert fingerprint == private_stage_context_fingerprint(reordered)
    assert fingerprint != private_stage_context_fingerprint({**_CONTEXT, "instructions": "different"})
    assert len(fingerprint) == 64
    assert all(value not in fingerprint for value in _CONTEXT.values())


def test_private_stage_context_fails_closed_when_server_key_missing_or_invalid(monkeypatch):
    for configured_key in ("", None, "not-a-fernet-key"):
        monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", configured_key)
        with pytest.raises(ValueError, match="Credential scope key"):
            private_stage_context_fingerprint(_CONTEXT)


def test_key_rotation_changes_private_context_namespace(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", _FIXED_KEY)
    original = private_stage_context_fingerprint(_CONTEXT)
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))

    assert private_stage_context_fingerprint(_CONTEXT) != original


def test_old_unkeyed_checkpoint_namespace_cannot_replay_paid_output(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", _FIXED_KEY)
    old_fingerprint = stage_fingerprint(_CONTEXT)
    output = ["\\documentclass{article}\\begin{document}Synthetic\\end{document}", [], 10, 0.5]

    class MemoryRedis:
        def __init__(self, value):
            self.value = value
            self.reads = 0

        def get(self, _key):
            self.reads += 1
            return self.value

    redis = MemoryRedis(
        json.dumps(
            {
                "version": 1,
                "fingerprint": old_fingerprint,
                "status": "complete",
                "output": output,
                "output_hash": stage_fingerprint({"output": output}),
            }
        )
    )
    new_fingerprint = private_stage_context_fingerprint(_CONTEXT)
    assert new_fingerprint != old_fingerprint

    checkpoint = OptimizationCheckpoint(redis, "synthetic-job", new_fingerprint)
    with pytest.raises(StageCheckpointError, match="context changed"):
        checkpoint.restore()
    assert redis.reads == 1


def test_generic_output_checksum_remains_unkeyed_and_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", _FIXED_KEY)
    output = {"source": "synthetic completed output", "tokens": 17}
    expected = hashlib.sha256(
        json.dumps(output, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()

    assert stage_fingerprint(output) == expected
