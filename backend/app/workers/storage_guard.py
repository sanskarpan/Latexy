"""Cross-worker guard tying stored compilation objects to a specific database.

``latex_worker`` uploads ``compilations/{job_id}/resume.pdf`` only after the
owning ``Compilation`` row is updated, and ``cleanup_worker`` deletes objects
whose job_id has no row. Those two decisions are only sound if BOTH workers are
talking to the SAME database — otherwise the pruner sees every live PDF as an
orphan and deletes it.

``app.utils.db_url.resolve_database_url`` makes them resolve the same DSN by
construction, but that is a code invariant, not a runtime fact: the two workers
are separate processes with separate environments. So the uploader stamps the
database it wrote to into Redis, and the pruner refuses to delete anything
unless it verified against that exact database.

Fail-closed by design: no stamp (or a stamp we cannot read) means no deletes.
Storage growth is recoverable; deleting a user's PDFs is not.
"""

from typing import Optional

from ..core.logging import get_logger

logger = get_logger(__name__)

_MARKER_KEY = "latexy:storage:compilations:db"
# Long enough to survive a quiet weekend between compiles, short enough that a
# retired database eventually stops authorising deletes.
_MARKER_TTL = 30 * 86400


def record_compilation_database(identity: str) -> None:
    """Stamp the database identity that the uploaded objects are indexed by."""
    if not identity:
        return
    try:
        from .event_publisher import get_worker_redis

        get_worker_redis().setex(_MARKER_KEY, _MARKER_TTL, identity)
    except Exception as exc:  # best-effort: a missing stamp only blocks pruning
        logger.debug(f"Could not record compilation database marker: {exc}")


def read_compilation_database() -> Optional[str]:
    """Return the stamped database identity, or None when it is unknown."""
    try:
        from .event_publisher import get_worker_redis

        value = get_worker_redis().get(_MARKER_KEY)
    except Exception as exc:
        logger.warning(f"Could not read compilation database marker: {exc}")
        return None
    if isinstance(value, bytes):
        value = value.decode()
    return value or None
