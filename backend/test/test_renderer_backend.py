"""Execution identity is resolved before engines or cloud clients are created."""
from unittest.mock import Mock

import pytest

from app.services.render_engine.backend import (
    FUNCTIONAL_TEST_VM_POLICY,
    VM_POLICY,
    RendererBackend,
    resolve_backend,
    start_engine_process,
)
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
    assert first.certification_flag_asserted and first.boundary_preflight
    assert first.engine_fingerprint != second.engine_fingerprint


def _functional_test_environment(monkeypatch, **overrides):
    monkeypatch.delenv("MODAL_ENGINE_VM_CERTIFIED", raising=False)
    values = {
        "DEPLOY_TARGET": "modal",
        "ENVIRONMENT": "test",
        "MODAL_ENVIRONMENT": "billing-acceptance-20261014",
        "MODAL_ENGINE_VM_FUNCTIONAL_ONLY_ACCEPTANCE": "true",
        "MODAL_ENGINE_VM_IMAGE_ID": "im-functionalTestImage",
        "MODAL_ENGINE_VM_ASSETS_FINGERPRINT": "a" * 64,
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_functional_only_backend_is_noncacheable_unverified_and_boundary_free(monkeypatch):
    _functional_test_environment(monkeypatch)
    backend = resolve_backend("lualatex")
    assert backend.kind == "modal_vm"
    assert backend.policy_identity == FUNCTIONAL_TEST_VM_POLICY
    assert backend.policy_identity != VM_POLICY
    assert backend.cacheable is False
    assert backend.certification_flag_asserted is False
    assert backend.boundary_preflight is False


@pytest.mark.parametrize("modal_environment", [
    "main", "prod", "production", "prod-west", "production-blue", "live", "unknownenv", "",
])
def test_functional_only_backend_rejects_unallowlisted_modal_environment(monkeypatch, modal_environment):
    _functional_test_environment(monkeypatch, MODAL_ENVIRONMENT=modal_environment)
    with pytest.raises(ModalEngineUnavailable, match="nonproduction tests"):
        resolve_backend("lualatex")


def test_functional_only_backend_rejects_non_test_and_certified_configurations(monkeypatch):
    _functional_test_environment(monkeypatch, ENVIRONMENT="production")
    with pytest.raises(ModalEngineUnavailable, match="nonproduction tests"):
        resolve_backend("lualatex")
    _functional_test_environment(monkeypatch, MODAL_ENGINE_VM_CERTIFIED="true")
    with pytest.raises(ModalEngineUnavailable, match="nonproduction tests"):
        resolve_backend("lualatex")


def test_functional_only_backend_rejects_invalid_tuple_or_flag(monkeypatch):
    _functional_test_environment(monkeypatch, MODAL_ENGINE_VM_IMAGE_ID="bad-image")
    with pytest.raises(ModalEngineUnavailable, match="capability is unavailable"):
        resolve_backend("lualatex")
    _functional_test_environment(monkeypatch, MODAL_ENGINE_VM_FUNCTIONAL_ONLY_ACCEPTANCE="yes")
    with pytest.raises(ModalEngineUnavailable, match="Invalid functional-only"):
        resolve_backend("lualatex")


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
