from __future__ import annotations

import base64
import hashlib
import json

import pytest
from cryptography.fernet import Fernet

from app.core.config import settings
from app.services.resume_engine.credential_scope import credential_scope
from app.services.resume_engine.stages import (
    OptimizationCheckpoint,
    StageCheckpointError,
    durable_run_context_fingerprint,
    paid_stage_input_fingerprint,
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


def test_credential_scope_matches_frozen_previous_implementation_vector(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", _FIXED_KEY)
    api_key = "synthetic-provider-key"
    # Frozen from the previous stdlib HMAC implementation, with only synthetic
    # inputs. Preserve byte compatibility without recomputing a second oracle.
    assert credential_scope(api_key) == "99f0d009214de620e1697c2eb1454805d721c420890f56752232ad037165b19e"
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


@pytest.mark.parametrize("fingerprint", [durable_run_context_fingerprint, paid_stage_input_fingerprint])
def test_private_durable_identities_are_canonical_keyed_and_fail_closed(monkeypatch, fingerprint):
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", _FIXED_KEY)
    original = fingerprint(_CONTEXT)
    assert original == fingerprint(dict(reversed(list(_CONTEXT.items()))))
    assert original != stage_fingerprint(_CONTEXT)
    assert original != fingerprint({**_CONTEXT, "instructions": "different"})
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    assert fingerprint(_CONTEXT) != original
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", "")
    with pytest.raises(ValueError, match="Credential scope key"):
        fingerprint(_CONTEXT)


def test_durable_run_and_paid_input_use_separate_purpose_domains(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", _FIXED_KEY)
    assert len({private_stage_context_fingerprint(_CONTEXT), durable_run_context_fingerprint(_CONTEXT),
                paid_stage_input_fingerprint(_CONTEXT), credential_scope(json.dumps(_CONTEXT))}) == 4
