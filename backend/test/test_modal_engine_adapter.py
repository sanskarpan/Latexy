"""Pinned SDK call contract and fail-closed preflight; no live cloud calls."""

import base64
import io
import json
import time
from types import SimpleNamespace

import pytest

from app.services.render_engine.modal_sandbox import (
    _BOUNDED_EXPORT,
    ModalEngineUnavailable,
    _read_remote_bounded,
    create_modal_engine,
)


class FakeSandbox:
    def __init__(self, observed=None):
        self.observed = observed or {"credential_env_present": False, "application_source_present": False,
                                     "dotenv_present": False, "landlock_abi": 3}
        self.terminated = False
        self.uploads = {}
        self.calls = []
        self.filesystem = SimpleNamespace(make_directory=lambda path: None, write_bytes=self.upload)

    def upload(self, data, path):
        self.uploads[path] = data

    def exec(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return SimpleNamespace(stdout=io.BytesIO(json.dumps(self.observed).encode()), wait=lambda: 0,
                               poll=lambda: 0, returncode=0)

    def terminate(self, **kwargs):
        self.terminated = True


def fake_sdk(sandbox, delay=0):
    calls = []

    def create(*args, **kwargs):
        calls.append((args, kwargs))
        time.sleep(delay)
        return sandbox

    return SimpleNamespace(Image=SimpleNamespace(from_id=lambda identifier: identifier),
                           Sandbox=SimpleNamespace(create=create)), calls


def request(tmp_path, sdk, **kwargs):
    (tmp_path / "resume.tex").write_text("fixture", encoding="utf-8")
    return create_modal_engine(workspace=tmp_path, compiler="lualatex", arguments=["resume.tex"],
                               timeout=kwargs.pop("timeout", 2), sdk=sdk, enabled=True,
                               image_id="im-cachedPureTeX", **kwargs)


def test_sdk_contract_has_no_credentials_network_or_mounts(tmp_path):
    sandbox = FakeSandbox()
    sdk, calls = fake_sdk(sandbox)
    process = request(tmp_path, sdk)
    try:
        options = calls[0][1]
        assert options["experimental_options"] == {"vm_runtime": True}
        assert "runtime" not in options
        assert options["block_network"] is True
        assert options["secrets"] == [] and options["volumes"] == {} and options["network_file_systems"] == {}
        assert options["include_oidc_identity_token"] is False
        assert options["cpu"] == (1, 2) and options["memory"] == (1024, 2048)
        assert sandbox.calls[0][0][0:2] == ("python3", "-c")
        assert "/workspace/resume.tex" in sandbox.uploads
        assert sandbox.calls[1][0][1].endswith("sandbox_io_bridge.py")
    finally:
        process.close()
    assert sandbox.terminated


@pytest.mark.parametrize("bad", [{"landlock_abi": -1}, {"landlock_abi": 2},
                                  {"credential_env_present": True}, {"application_source_present": True},
                                  {"dotenv_present": True}])
def test_preflight_rejects_before_source_upload(tmp_path, bad):
    sandbox = FakeSandbox()
    sandbox.observed.update(bad)
    sdk, _ = fake_sdk(sandbox)
    with pytest.raises(ModalEngineUnavailable, match="preflight rejected"):
        request(tmp_path, sdk)
    assert sandbox.terminated and not sandbox.uploads
    assert len(sandbox.calls) == 1


def test_late_creation_is_terminated_without_upload(tmp_path):
    sandbox = FakeSandbox()
    sdk, _ = fake_sdk(sandbox, delay=0.08)
    with pytest.raises(ModalEngineUnavailable, match="deadline exceeded"):
        request(tmp_path, sdk, timeout=0.02)
    assert sandbox.terminated and not sandbox.uploads


def test_disabled_adapter_never_calls_sdk(tmp_path):
    sandbox = FakeSandbox()
    sdk, calls = fake_sdk(sandbox)
    with pytest.raises(ModalEngineUnavailable, match="not configured"):
        create_modal_engine(workspace=tmp_path, compiler="lualatex", arguments=[], timeout=2,
                            sdk=sdk, enabled=False, image_id="im-test")
    assert not calls


def test_new_export_protocol_is_trusted_bounded_and_avoids_legacy_file_io():
    seen = []
    data = b"bounded PDF bytes"

    def execute(*args, **kwargs):
        seen.append((args, kwargs))
        return SimpleNamespace(stdout=io.BytesIO(base64.b64encode(data)), wait=lambda: 0)

    sandbox = SimpleNamespace(exec=execute)
    assert _read_remote_bounded(sandbox, "/workspace/resume.pdf", 50) == data
    assert seen[0][0] == ("python3", "-c", _BOUNDED_EXPORT, "/workspace/resume.pdf", "50")
    assert "O_NOFOLLOW" in _BOUNDED_EXPORT and "f.read(limit+1)" in _BOUNDED_EXPORT


def test_remote_export_rejects_overlong_or_invalid_encoded_payload():
    sandbox = SimpleNamespace(exec=lambda *a, **kw: SimpleNamespace(stdout=io.BytesIO(b"A" * 100), wait=lambda: 0))
    with pytest.raises(ModalEngineUnavailable, match="export rejected"):
        _read_remote_bounded(sandbox, "/workspace/resume.pdf", 3)


def test_certificate_handles_actual_tex2022_trailing_space_and_rejects_allowed():
    from scripts.certify_modal_vm_engine import audit_denials

    # Actual cached-cloud TeX2022 diagnostic lines, including trailing space.
    log = b"font loader initialized\nAUDIT ROOT DENIED\nAUDIT ENVIRON DENIED\nAUDIT BOOTSTRAP DENIED \n[1]\n"
    assert audit_denials(log, 3)
    assert not audit_denials(log.replace(b"BOOTSTRAP DENIED", b"BOOTSTRAP ALLOWED"), 3)
    assert not audit_denials(log, 4)


def test_expected_image_assets_mismatch_rejects_before_upload(tmp_path):
    sandbox = FakeSandbox()
    sandbox.observed["assets_fingerprint"] = "a" * 64
    sdk, _ = fake_sdk(sandbox)
    with pytest.raises(ModalEngineUnavailable, match="assets differ"):
        request(tmp_path, sdk, expected_assets="b" * 64)
    assert sandbox.terminated and not sandbox.uploads


def test_one_session_reuses_vm_for_bibliography_and_preserves_deadline(tmp_path):
    sandbox = FakeSandbox()
    sdk, calls = fake_sdk(sandbox)
    first = request(tmp_path, sdk)
    try:
        (tmp_path / "resume.bbl").write_text("bounded bibliography", encoding="utf-8")
        deadline = first.renderer_session.deadline
        second = create_modal_engine(workspace=tmp_path, compiler="bibtex", arguments=["resume"], timeout=1,
                                     sdk=sdk, enabled=True, image_id="im-cachedPureTeX",
                                     session=first.renderer_session)
        assert second.renderer_session is first.renderer_session
        assert second.renderer_session.deadline == deadline
        assert len(calls) == 1
        assert sandbox.uploads["/workspace/resume.bbl"] == b"bounded bibliography"
        with pytest.raises(ModalEngineUnavailable, match="identity"):
            create_modal_engine(workspace=tmp_path, compiler="bibtex", arguments=["resume"], timeout=1,
                                sdk=sdk, enabled=True, image_id="im-different", session=first.renderer_session)
    finally:
        first.close()
