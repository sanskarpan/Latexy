"""Execution identity is resolved before engines or cloud clients are created."""
from unittest.mock import Mock

import pytest

from app.services.render_engine.backend import RendererBackend, resolve_backend, start_engine_process
from app.services.render_engine.modal_sandbox import ModalEngineUnavailable


def test_modal_missing_certificate_fails_before_any_process(monkeypatch):
    monkeypatch.setenv("DEPLOY_TARGET", "modal")
    monkeypatch.delenv("MODAL_ENGINE_VM_CERTIFIED", raising=False)
    with pytest.raises(ModalEngineUnavailable):
        resolve_backend("lualatex")


def test_vm_fingerprint_distinct_and_asset_scoped(monkeypatch):
    monkeypatch.setenv("DEPLOY_TARGET", "modal")
    monkeypatch.setenv("MODAL_ENGINE_VM_CERTIFIED", "true")
    monkeypatch.setenv("MODAL_ENGINE_VM_IMAGE_ID", "im-certifiedPureTex")
    monkeypatch.setenv("MODAL_ENGINE_VM_ASSETS_FINGERPRINT", "a" * 64)
    first = resolve_backend("lualatex")
    monkeypatch.setenv("MODAL_ENGINE_VM_ASSETS_FINGERPRINT", "b" * 64)
    second = resolve_backend("lualatex")
    assert first.kind == "modal_vm" and first.policy_identity == "lua-credential-free-vm-v1"
    assert first.engine_fingerprint != second.engine_fingerprint


def test_mutable_docker_image_cannot_share_cache(monkeypatch):
    monkeypatch.delenv("DEPLOY_TARGET", raising=False)
    monkeypatch.setenv("LATEXY_RENDER_BACKEND", "docker")
    from app.core.config import settings
    monkeypatch.setattr(settings, "LATEX_DOCKER_IMAGE", "texlive:latest")
    assert not resolve_backend("lualatex").cacheable
    monkeypatch.setattr(settings, "LATEX_DOCKER_IMAGE", "texlive@sha256:" + "a" * 64)
    assert resolve_backend("lualatex").cacheable


def test_native_preserves_existing_popen_contract():
    factory = Mock(return_value="process")
    assert start_engine_process(["lualatex", "resume.tex"], cwd="/job", env={}, workspace="/job",
                                compiler="lualatex", timeout=30, backend=RendererBackend("native", "assets", "policy"),
                                popen_factory=factory, stdout=-1, stderr=-2) == "process"
    factory.assert_called_once_with(["lualatex", "resume.tex"], cwd="/job", env={}, stdout=-1, stderr=-2)


def test_modal_factory_uses_actual_bibtex_and_original_session(monkeypatch):
    start = Mock(return_value="process")
    monkeypatch.setattr("app.services.render_engine.backend.create_modal_engine", start)
    selected = RendererBackend("modal_vm", "assets", "lua-credential-free-vm-v1", "im-certified", "a" * 64)
    session = object()
    assert start_engine_process(["python3", "/wrapper", "/job", "bibtex", "resume"], cwd="/job", env={},
                                workspace="/job", compiler="lualatex", actual_engine="bibtex", timeout=12,
                                backend=selected, engine_session=session) == "process"
    assert start.call_args.kwargs["compiler"] == "bibtex"
    assert start.call_args.kwargs["arguments"] == ["resume"]
    assert start.call_args.kwargs["session"] is session
