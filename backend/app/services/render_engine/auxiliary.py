"""Bounded auxiliary snapshots: literal labels only, never executable TeX blobs."""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from ...utils.bounded_io import read_file_bounded
from .artifacts import canonical_json, sha256
from .coalescing import RenderLease

_SAFE_LABEL = re.compile(r"\\newlabel\{[A-Za-z0-9:_-]{1,128}\}\{\{[0-9.]{1,32}\}\{[0-9]{1,8}\}\}")
MAX_AUX_BYTES = 32 * 1024


class AuxiliaryWorkspace:
    def __init__(self, redis: Any, job_dir: Path, request: dict, timeout: float):
        self.redis, self.job_dir, self.lease, self.key, self.loaded = redis, job_dir, None, None, False
        document_id = request.get("document_id")
        source = request.get("render_source", "")
        if not document_id or not request.get("owner_scope") or r"\begin{document}" not in source:
            return
        material = {"document_id": document_id, "owner": request["owner_scope"],
                    "preamble": source.split(r"\begin{document}", 1)[0],
                    "compiler": request["compiler"], "engine": request["engine_fingerprint"],
                    "settings": request["settings"]}
        self.key = "latexy:auxiliary:" + sha256(canonical_json(material))
        token = uuid.uuid4().hex
        if not redis.set(self.key + ":lease", token, nx=True, ex=max(2, min(360, int(timeout) + 30))):
            self.key = None  # Busy documents compile in their own fresh workspace.
            return
        self.lease = RenderLease(redis, self.key + ":lease", token)
        raw = redis.get(self.key)
        if isinstance(raw, str):
            raw = raw.encode()
        if isinstance(raw, bytes) and len(raw) <= MAX_AUX_BYTES:
            safe = self.sanitize(raw)
            if safe != b"\\relax\n":
                (job_dir / "resume.aux").write_bytes(safe)
                self.loaded = True

    @staticmethod
    def sanitize(data: bytes) -> bytes:
        if len(data) > MAX_AUX_BYTES:
            return b"\\relax\n"
        lines = [line for line in data.decode("utf-8", errors="replace").splitlines() if _SAFE_LABEL.fullmatch(line)]
        return ("\\relax\n" + "\n".join(lines[:400]) + ("\n" if lines else "")).encode()

    def save(self) -> None:
        if not self.key or not self.lease:
            return
        from ...workers.job_lifecycle import write_owned_artifacts

        # Auxiliary reuse is disposable. It never determines terminal success,
        # and a cancelled or replaced capability cannot seed a later snapshot.
        try:
            value = self.redis.get(self.lease.key)
            if isinstance(value, bytes):
                value = value.decode()
            if value != self.lease.token:
                return
            safe = self.sanitize(read_file_bounded(self.job_dir / "resume.aux", MAX_AUX_BYTES))
            job_id = self.job_dir.name
            write_owned_artifacts(self.redis, job_id, {self.key: safe.decode()}, 900)
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        if self.lease:
            self.lease.close()
