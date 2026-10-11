"""The optional bounded artifact sweep cannot abort ordinary job recovery."""
from unittest.mock import MagicMock

from app.workers.cleanup_worker import _prune_render_artifacts


def test_unavailable_sweep_lock_defers_without_aborting_cleanup():
    redis = MagicMock()
    redis.set.side_effect = ConnectionError("Redis unavailable")
    assert _prune_render_artifacts(redis) == {"scanned": 0, "deleted": 0, "protected": 0}
    redis.eval.assert_not_called()


def test_failed_lock_release_preserves_successful_sweep(monkeypatch):
    from app.services.render_engine import retention

    async def sweep(**kwargs):
        return {"scanned": 3, "deleted": 1, "protected": 2, "next_cursor": None}

    monkeypatch.setattr(retention, "sweep_artifacts", sweep)
    redis = MagicMock()
    redis.get.return_value = None
    redis.eval.side_effect = ConnectionError("Redis unavailable")
    assert _prune_render_artifacts(redis) == {"scanned": 3, "deleted": 1, "protected": 2}
