"""Fenced per-job LLM checkpoints; never automatically repeat ambiguous paid work."""
from __future__ import annotations

import hashlib
import json
import math

from ...workers.job_lifecycle import write_owned_artifacts
from .credential_scope import _private_stage_context_fingerprint


class StageCheckpointError(RuntimeError):
    """Fail closed when a paid stage cannot be safely recovered."""


def stage_fingerprint(context: dict) -> str:
    return hashlib.sha256(json.dumps(context, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def private_stage_context_fingerprint(context: dict) -> str:
    """Key private admission context used to decide whether paid output may replay.

    This protects low-entropy user text from offline matching against the stored
    context identifier. It is deliberately separate from generic output hashes.
    Rotating the server key changes the ID and causes pending work to fail closed.
    """
    serialized = json.dumps(context, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return _private_stage_context_fingerprint(serialized)


def _validate_output(output) -> tuple:
    if not isinstance(output, (list, tuple)) or len(output) != 4:
        raise StageCheckpointError("Invalid optimization checkpoint output")
    source, changes, tokens, duration = output
    if (not isinstance(source, str) or not source.strip() or not isinstance(changes, list)
            or type(tokens) is not int or tokens < 0
            or type(duration) not in {int, float} or not math.isfinite(duration) or duration < 0
            or any(not isinstance(change, dict) for change in changes)):
        raise StageCheckpointError("Invalid optimization checkpoint fields")
    for change in changes:
        if any(not isinstance(change.get(key), str) for key in ("section", "change_type", "reason")):
            raise StageCheckpointError("Invalid optimization checkpoint change record")
    return source, changes, tokens, duration


class OptimizationCheckpoint:
    """One job's intent and completed output, inside its existing artifact TTL.

    A requesting marker after a crash is ambiguous: the provider may have billed
    it. Never buy it again automatically. Only a validated complete checkpoint
    permits a later render/storage retry. Redis loss fails closed once an intent
    was written; this is not a durable database stage ledger.
    """

    def __init__(self, redis, job_id: str, fingerprint: str):
        self.redis = redis
        self.job_id = job_id
        self.fingerprint = fingerprint
        self.key = f"latexy:job:{job_id}:optimization-checkpoint"

    def restore(self) -> tuple | None:
        try:
            raw = self.redis.get(self.key)
            if raw is None:
                return None
            if not isinstance(raw, (str, bytes)) or len(raw) > 2_000_000:
                raise StageCheckpointError("Invalid optimization checkpoint")
            checkpoint = json.loads(raw)
            if not isinstance(checkpoint, dict) or type(checkpoint.get("version")) is not int or checkpoint["version"] != 1:
                raise StageCheckpointError("Unsupported optimization checkpoint version")
            if checkpoint.get("fingerprint") != self.fingerprint:
                raise StageCheckpointError("Optimization checkpoint context changed")
            if checkpoint.get("status") != "complete":
                raise StageCheckpointError("Prior paid optimization has an ambiguous outcome")
            output = checkpoint["output"]
            source, changes, tokens, duration = _validate_output(output)
            if stage_fingerprint({"output": output}) != checkpoint.get("output_hash"):
                raise StageCheckpointError("Optimization checkpoint integrity failed")
            return source, changes, tokens, duration
        except StageCheckpointError:
            raise
        except Exception as exc:
            raise StageCheckpointError("Optimization checkpoint unavailable") from exc

    def _write(self, value: dict, expected: str | None):
        encoded = json.dumps({"version": 1, "fingerprint": self.fingerprint, **value}, allow_nan=False)
        if len(encoded.encode()) > 2_000_000:
            raise StageCheckpointError("Optimization checkpoint exceeds the size limit")
        try:
            accepted = write_owned_artifacts(self.redis, self.job_id, {self.key: encoded}, 86400,
                                             expected_values={self.key: expected})
        except Exception as exc:
            raise StageCheckpointError("Optimization checkpoint unavailable") from exc
        if not accepted:
            raise StageCheckpointError("Optimization checkpoint ownership or stage transition expired")

    def begin(self):
        self._write({"status": "requesting"}, None)

    def complete(self, output: tuple):
        value = list(_validate_output(output))
        requesting = json.dumps({"version": 1, "fingerprint": self.fingerprint, "status": "requesting"}, allow_nan=False)
        self._write({"status": "complete", "output": value, "output_hash": stage_fingerprint({"output": value})}, requesting)
