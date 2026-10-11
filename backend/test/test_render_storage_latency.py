"""Independent storage RTTs overlap without weakening the publication gate."""
import threading
from unittest.mock import Mock

import pytest

from app.services.render_engine import artifacts, retention


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


def test_pdf_and_synctex_upload_overlap_before_both_refs_return(monkeypatch):
    barrier = threading.Barrier(2, timeout=5)
    completed = set()
    lock = threading.Lock()

    def put(scope, kind, data, media_type):
        assert scope == artifacts.sha256("user:test")
        barrier.wait()
        with lock:
            completed.add(kind)
        return artifacts.ObjectRef(key=artifacts.binary_key(scope, artifacts.sha256(data), kind),
                                   sha256=artifacts.sha256(data), size=len(data), media_type=media_type)

    monkeypatch.setattr(artifacts, "_put", put)
    pdf, synctex = artifacts._put_render_binaries(artifacts.sha256("user:test"), b"%PDF-test", b"compressed")
    assert completed == {"pdf", "synctex"}
    assert pdf.media_type == "application/pdf"
    assert synctex.media_type == "application/gzip"


@pytest.mark.parametrize("failed_kind", ["pdf", "synctex"])
def test_upload_failure_joins_other_binary_before_caller_cleanup(monkeypatch, failed_kind):
    barrier = threading.Barrier(2, timeout=5)
    completed = threading.Event()

    def put(scope, kind, data, media_type):
        barrier.wait()
        if kind == failed_kind:
            raise OSError("upload failed")
        completed.set()

    monkeypatch.setattr(artifacts, "_put", put)
    with pytest.raises(OSError, match="upload failed"):
        artifacts._put_render_binaries("scope", b"pdf", b"synctex")
    assert completed.is_set()


def test_pdf_only_does_not_create_an_auxiliary_upload(monkeypatch):
    put = Mock(return_value="pdf-ref")
    monkeypatch.setattr(artifacts, "_put", put)
    assert artifacts._put_render_binaries("scope", b"pdf", None) == ("pdf-ref", None)
    put.assert_called_once_with("scope", "pdf", b"pdf", "application/pdf")
