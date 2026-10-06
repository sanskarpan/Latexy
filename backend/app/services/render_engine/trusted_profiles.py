"""Select a verified image-built format for an exact owned preamble.

Verification is memoized per immutable manifest bytes. Missing, writable,
symlinked, mismatched, external-Docker or altered assets use ordinary rendering.
This module performs no application imports, image probes, or format builds.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from functools import lru_cache
from pathlib import Path

from .managed_preamble import MANAGED_ENGLISH_FORMAT_ID, MANAGED_ENGLISH_PREAMBLE

MANIFEST_PATH = Path("/opt/latexy-trusted-formats.json")
FORMAT_PATH = Path("/var/lib/texmf/web2c/pdftex") / (MANAGED_ENGLISH_FORMAT_ID + ".fmt")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = {"profile_id", "compiler", "format_path", "format_size", "format_sha256",
    "preamble_sha256", "compiler_binary_sha256", "compiler_version", "dependencies_sha256", "identity_sha256"}


def _immutable(path: Path, maximum: int) -> bytes:
    stat = path.stat()
    if path.is_symlink() or not path.is_file() or stat.st_mode & 0o222 or stat.st_uid != 0:
        raise ValueError("Format asset is not immutable image data")
    if not 0 < stat.st_size <= maximum:
        raise ValueError("Format asset outside size bound")
    return path.read_bytes()


@lru_cache(maxsize=2)
def _verified(manifest: bytes, format_path: str, binary_path: str) -> dict | None:
    try:
        value = json.loads(manifest)
        if set(value) != {"schema_version", "profiles"} or value["schema_version"] != 1:
            return None
        if not isinstance(value["profiles"], list) or len(value["profiles"]) != 1:
            return None
        profile = value["profiles"][0]
        if not isinstance(profile, dict) or set(profile) != _FIELDS:
            return None
        if (profile["profile_id"] != MANAGED_ENGLISH_FORMAT_ID or profile["compiler"] != "pdflatex"
                or profile["format_path"] != format_path or type(profile["format_size"]) is not int
                or not 1024 <= profile["format_size"] <= 16 * 1024 * 1024
                or not isinstance(profile["compiler_version"], str) or len(profile["compiler_version"]) > 512):
            return None
        for field in ("format_sha256", "preamble_sha256", "compiler_binary_sha256", "dependencies_sha256", "identity_sha256"):
            if not isinstance(profile[field], str) or not _SHA.fullmatch(profile[field]):
                return None
        material = {key: item for key, item in profile.items() if key != "identity_sha256"}
        expected_identity = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if profile["identity_sha256"] != expected_identity:
            return None
        if profile["preamble_sha256"] != hashlib.sha256(MANAGED_ENGLISH_PREAMBLE.encode()).hexdigest():
            return None
        fmt = _immutable(Path(format_path), 16 * 1024 * 1024)
        binary = Path(binary_path)
        if binary.stat().st_mode & 0o022 or binary.stat().st_uid != 0:
            return None
        if (len(fmt) != profile["format_size"] or hashlib.sha256(fmt).hexdigest() != profile["format_sha256"]
                or hashlib.sha256(binary.read_bytes()).hexdigest() != profile["compiler_binary_sha256"]):
            return None
        return profile
    except (OSError, ValueError, TypeError, KeyError):
        return None


def trusted_format_identity(source: str, compiler: str) -> dict | None:
    if compiler != "pdflatex" or not source.startswith(MANAGED_ENGLISH_PREAMBLE + r"\begin{document}"):
        return None
    # Host assets do not prove the independently selected Docker image contains
    # that format. Keep that dispatch path ordinary until image identity agrees.
    if shutil.which("docker"):
        return None
    try:
        binary = shutil.which("pdflatex")
        if not binary:
            return None
        verified = _verified(_immutable(MANIFEST_PATH, 32768), str(FORMAT_PATH), str(Path(binary).resolve(strict=True)))
        return dict(verified) if verified else None
    except (OSError, ValueError):
        return None


def trusted_format_flags(source: str, compiler: str) -> list[str]:
    return ["-fmt=" + MANAGED_ENGLISH_FORMAT_ID] if trusted_format_identity(source, compiler) else []
