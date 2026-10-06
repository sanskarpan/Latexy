"""Cross-worker guard tying stored compilation objects to a specific database.

``latex_worker`` uploads an owner-tokenized
``compilations/{job_id}/finalization-<owner-hash>.pdf`` and records the
owning ``Compilation`` row only after the upload succeeds; the database
identity marker is written only after that durable row commit, and
``cleanup_worker`` deletes objects
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

        get_worker_redis().set(_MARKER_KEY, identity, ex=_MARKER_TTL)
    except Exception as exc:  # best-effort: a missing stamp only blocks pruning
        logger.debug("Could not record compilation database marker", extra={"error_type": type(exc).__name__})


def read_compilation_database() -> Optional[str]:
    """Return the stamped database identity, or None when it is unknown."""
    try:
        from .event_publisher import get_worker_redis

        value = get_worker_redis().get(_MARKER_KEY)
    except Exception as exc:
        logger.warning("Could not read compilation database marker", extra={"error_type": type(exc).__name__})
        return None
    if isinstance(value, bytes):
        value = value.decode()
    return value or None
