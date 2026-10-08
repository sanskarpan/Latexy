"""Independent storage RTTs overlap without weakening the publication gate."""
import threading
from unittest.mock import Mock

import pytest

from app.services.render_engine import retention


def test_all_four_storage_checks_overlap_and_complete_before_return(monkeypatch):
    barrier = threading.Barrier(4, timeout=5)
    completed = set()
    lock = threading.Lock()
    expected = [(f"object-{number}", number + 1) for number in range(4)]

    def head(key):
        barrier.wait()
        with lock:
            completed.add(key)
        return dict(expected)[key]

    monkeypatch.setattr(retention.storage_service, "head_size", head)
    assert retention._storage_objects_present(expected)
    assert completed == {key for key, _ in expected}


def test_mismatch_rejects_publication_after_all_checks_complete(monkeypatch):
    head = Mock(side_effect=lambda key: {"pdf": 20, "synctex": 3, "manifest": 100}[key])
    monkeypatch.setattr(retention.storage_service, "head_size", head)
    assert not retention._storage_objects_present([("pdf", 20), ("synctex", 4), ("manifest", 100)])
    assert head.call_count == 3


def test_error_joins_other_checks_before_releasing_caller_locks(monkeypatch):
    barrier = threading.Barrier(2, timeout=5)
    finished = threading.Event()

    def head(key):
        barrier.wait()
        if key == "missing":
            raise OSError("storage unavailable")
        finished.set()
        return 1

    monkeypatch.setattr(retention.storage_service, "head_size", head)
    with pytest.raises(OSError, match="storage unavailable"):
        retention._storage_objects_present([("missing", 1), ("pdf", 1)])
    assert finished.is_set()


@pytest.mark.parametrize("expected", [[], [(str(n), 1) for n in range(5)]])
def test_storage_check_concurrency_is_bounded(monkeypatch, expected):
    head = Mock()
    monkeypatch.setattr(retention.storage_service, "head_size", head)
    with pytest.raises(ValueError):
        retention._storage_objects_present(expected)
    head.assert_not_called()
