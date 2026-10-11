"""Build-provided renderer identity; never mislabel an assets hash as OCI."""
import json
import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def renderer_fingerprint() -> str:
    digest = os.environ.get("LATEXY_RENDER_IMAGE_DIGEST")
    if digest:
        return "oci:" + digest[:400]
    try:
        marker = Path("/opt/latexy-renderer-version.json")
        if marker.stat().st_size <= 65536:
            value = json.loads(marker.read_text(encoding="utf-8"))
            fingerprint = value.get("fingerprint_sha256", "")
            if value.get("schema_version") == 1 and len(fingerprint) == 64 and all(c in "0123456789abcdef" for c in fingerprint):
                return "engine_assets_fingerprint:" + fingerprint
    except (OSError, ValueError, TypeError):
        pass
    # Unversioned development environments cannot share cache entries across
    # process restarts: an operator may have changed fonts or format files.
    return "unversioned-process:" + _PROCESS_ID


_PROCESS_ID = os.urandom(16).hex()
