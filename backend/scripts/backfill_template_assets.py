"""
One-off: regenerate template thumbnails and preview PDFs into object storage.

Run from backend/:
    modal run scripts/backfill_template_assets.py

Why this exists. Production served `502 Storage unavailable` for every template
thumbnail and preview PDF — 0 of 147 (#1143). The cause was configuration:
MINIO_ENDPOINT fell back to `http://localhost:9000`, which does not exist inside a
Modal container. Pointing it at real storage fixes the *access* problem but not the
*content* one: the new bucket is empty, and the assets cannot be copied from a
development MinIO because template UUIDs are per-database, so local keys match
nothing in production.

So they have to be regenerated against the production database. This runs
`app/scripts/compile_templates.py` inside `latex_image`, which already carries the
full TeX toolchain and poppler — the same code path that produced the assets
originally, rather than a second implementation that could drift.

Read-only with respect to the database: it selects active templates and writes only
to object storage. Idempotent — the script skips any template whose .png and .pdf
are both already present, so it is safe to re-run after a partial failure.

Ephemeral (`modal run`, not `modal deploy`), so it does not become part of the
deployed app.
"""

from pathlib import Path

import modal

_BACKEND_DIR = Path(__file__).parent.parent

# Import the deployed app's image and secret definitions rather than restating
# them: a divergent copy here would be exactly the deployment-parity bug class
# that test_modal_deployment_parity.py exists to catch.
import sys

sys.path.insert(0, str(_BACKEND_DIR))
from modal_app import _secrets, latex_image  # noqa: E402

app = modal.App("latexy-backfill-template-assets")


@app.function(
    image=latex_image,
    secrets=_secrets,
    # ~150 templates, two pdflatex passes each plus a PNG conversion. Generous, and
    # it only has to hold for a single manual run.
    timeout=3600,
)
def backfill() -> str:
    import asyncio
    import io
    import sys

    sys.path.insert(0, "/backend")

    from app.core.config import settings
    from app.scripts.compile_templates import main
    from app.services import storage_service

    # Fail loudly rather than quietly writing to the wrong place: this whole
    # exercise exists because storage was silently misconfigured.
    ok, detail = storage_service.probe()
    if not ok:
        raise RuntimeError(
            f"object storage unreachable ({detail}); endpoint={settings.MINIO_ENDPOINT!r} "
            f"bucket={settings.MINIO_BUCKET!r} — check the latexy-storage secret"
        )
    print(f"storage OK: endpoint={settings.MINIO_ENDPOINT} bucket={settings.MINIO_BUCKET}")

    buffer = io.StringIO()
    original = sys.stdout
    sys.stdout = _Tee(original, buffer)
    try:
        asyncio.run(main())
    finally:
        sys.stdout = original
    return buffer.getvalue()[-4000:]


class _Tee:
    """Echo to the live Modal log and capture for the return value."""

    def __init__(self, *streams) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        for s in self._streams:
            s.write(data)
        return len(data)

    def flush(self) -> None:
        for s in self._streams:
            s.flush()


@app.local_entrypoint()
def run() -> None:
    print(backfill.remote())
