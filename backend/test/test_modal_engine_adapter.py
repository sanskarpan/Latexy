"""Pinned SDK call contract and fail-closed preflight; no live cloud calls."""

import base64
import io
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from app.services.render_engine.modal_sandbox import (
    _BATCH_EXPORT,
    _BATCH_EXPORT_HEADER,
    _BATCH_EXPORT_MAGIC,
    _BATCH_EXPORT_MAX_BYTES,
    _BATCH_EXPORT_SLOTS,
    _BOUNDED_EXPORT,
    ModalEngineProcess,
    ModalEngineSession,
    ModalEngineUnavailable,
    _decode_remote_batch,
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


def _batch_payload(records):
    output = bytearray(_BATCH_EXPORT_MAGIC)
    output.append(len(_BATCH_EXPORT_SLOTS))
    for index, (name, _limit) in enumerate(_BATCH_EXPORT_SLOTS):
        data = records.get(name)
        if data is None:
            output.extend(_BATCH_EXPORT_HEADER.pack(index, 0, 0))
        else:
            output.extend(_BATCH_EXPORT_HEADER.pack(index, 1, len(data)))
            output.extend(data)
    return bytes(output)


class _FakeRemoteProcess:
    def __init__(self, payload=b"", returncode=0, on_read=None):
        self.stdout = io.BytesIO(payload) if on_read is None else _ReadHook(payload, on_read)
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode


class _ReadHook:
    def __init__(self, payload, on_read):
        self.payload = payload
        self.on_read = on_read

    def read(self):
        self.on_read()
        return self.payload

    def __iter__(self):
        self.on_read()
        yield self.payload


class _ExportSandbox:
    def __init__(self, payload, *, returncode=0, on_read=None):
        self.payload = payload
        self.returncode = returncode
        self.on_read = on_read
        self.calls = []
        self.terminated = False

    def exec(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return _FakeRemoteProcess(self.payload, self.returncode, self.on_read)

    def terminate(self, **_kwargs):
        self.terminated = True


def _adapter_process(tmp_path, sandbox, *, session=None):
    process = ModalEngineProcess(sandbox, _FakeRemoteProcess(), tmp_path, "resume")
    if session is not None:
        process.renderer_session = session
    return process


def test_batch_export_uses_one_bytes_command_and_preserves_artifact_and_stdout_order(tmp_path):
    records = {
        ".pdf": b"%PDF\x00\xff",
        ".log": b"compiler log\n",
        ".synctex.gz": b"sync\x00data",
        "engine.stdout": b"engine output\n",
    }
    sandbox = _ExportSandbox(_batch_payload(records))
    process = _adapter_process(tmp_path, sandbox)

    assert process.wait() == 0
    assert len(sandbox.calls) == 1
    args, kwargs = sandbox.calls[0]
    assert args == ("python3", "-c", _BATCH_EXPORT, "resume")
    assert kwargs == {"timeout": 30, "text": False, "secrets": []}
    assert (tmp_path / "resume.pdf").read_bytes() == records[".pdf"]
    assert (tmp_path / "resume.log").read_bytes() == records[".log"]
    assert (tmp_path / "resume.synctex.gz").read_bytes() == records[".synctex.gz"]
    assert not (tmp_path / "resume.fls").exists()
    assert process.stdout.read(64) == b"engine output\n"
    assert process.stdout.read(64) == b""


def test_batch_missing_artifacts_skip_but_missing_stdout_fails_only_when_read(tmp_path):
    sandbox = _ExportSandbox(_batch_payload({}))
    process = _adapter_process(tmp_path, sandbox)

    assert process.wait() == 0
    assert len(sandbox.calls) == 1
    assert not list(tmp_path.glob("resume.*"))
    with pytest.raises(FileNotFoundError, match="engine.stdout"):
        process.stdout.read(64)


def test_batch_missing_pdf_is_not_an_export_error(tmp_path):
    records = {".log": b"no PDF produced\n", "engine.stdout": b"engine output\n"}
    process = _adapter_process(tmp_path, _ExportSandbox(_batch_payload(records)))

    assert process.wait() == 0
    assert (tmp_path / "resume.log").read_bytes() == records[".log"]
    assert not (tmp_path / "resume.pdf").exists()


def test_batch_export_keeps_only_small_stdout_after_materializing_large_artifacts(tmp_path):
    sandbox = _ExportSandbox(_batch_payload({".pdf": b"p" * (1024 * 1024), "engine.stdout": b"log"}))
    process = _adapter_process(tmp_path, sandbox)
    assert process.wait() == 0
    # Keeping this as a memoryview would retain the entire aggregate frame,
    # including the PDF/SyncTeX, throughout subsequent worker bookkeeping.
    assert type(process._stdout_data) is bytes
    assert process._stdout_data == b"log"
    assert process.stdout.read(32) == b"log"


@pytest.mark.parametrize(
    "corruption",
    ["magic", "truncated-header", "wrong-count", "wrong-index", "invalid-status",
     "missing-with-data", "oversized-slot", "truncated-data", "trailing-data"],
)
def test_batch_parser_rejects_malformed_or_truncated_frames(corruption):
    payload = bytearray(_batch_payload({".pdf": b"pdf"}))
    header_offset = len(_BATCH_EXPORT_MAGIC) + 1
    if corruption == "magic":
        payload[0] ^= 0x01
    elif corruption == "truncated-header":
        payload = payload[:header_offset + _BATCH_EXPORT_HEADER.size - 1]
    elif corruption == "wrong-count":
        payload[len(_BATCH_EXPORT_MAGIC)] -= 1
    elif corruption == "wrong-index":
        payload[header_offset] = 1
    elif corruption == "invalid-status":
        payload[header_offset + 1] = 9
    elif corruption == "missing-with-data":
        payload[header_offset + 1] = 0
    elif corruption == "oversized-slot":
        payload[header_offset + 2:header_offset + 6] = (20 * 1024 * 1024 + 1).to_bytes(4, "big")
    elif corruption == "truncated-data":
        payload[header_offset + _BATCH_EXPORT_HEADER.size:] = b""
    elif corruption == "trailing-data":
        payload.extend(b"x")

    with pytest.raises(ModalEngineUnavailable, match="(Invalid|Truncated|Unexpected)"):
        _decode_remote_batch(bytes(payload))


@pytest.mark.parametrize("file_kind", ["symlink", "fifo", "directory"])
def test_batch_remote_export_rejects_unsafe_files_without_following_or_blocking(
    tmp_path, file_kind
):
    workspace = tmp_path / "remote-workspace"
    workspace.mkdir()
    if file_kind == "symlink":
        outside = tmp_path / "outside.pdf"
        outside.write_bytes(b"must not be read")
        (workspace / "resume.pdf").symlink_to(outside)
    elif file_kind == "fifo":
        os.mkfifo(workspace / "resume.pdf")
    else:
        (workspace / "resume.pdf").mkdir()
    script = _BATCH_EXPORT.replace(
        "path='/workspace/'+name", "path=os.environ['LATEXY_TEST_WORKSPACE']+'/'+name"
    )

    result = subprocess.run(
        [sys.executable, "-c", script, "resume"],
        capture_output=True,
        check=False,
        timeout=2,
        env={"LATEXY_TEST_WORKSPACE": str(workspace)},
    )
    assert result.returncode == 78
    if file_kind == "symlink":
        assert b"must not be read" not in result.stdout


def test_batch_remote_script_emits_bounded_raw_binary_frames(tmp_path):
    workspace = tmp_path / "remote-workspace"
    workspace.mkdir()
    files = {
        "resume.pdf": b"%PDF\x00\xffbinary",
        "resume.log": b"compile log\n",
        "engine.stdout": b"stdout\x00\xfe",
    }
    for name, data in files.items():
        (workspace / name).write_bytes(data)
    script = _BATCH_EXPORT.replace(
        "path='/workspace/'+name", "path=os.environ['LATEXY_TEST_WORKSPACE']+'/'+name"
    )

    result = subprocess.run(
        [sys.executable, "-c", script, "resume"],
        capture_output=True,
        check=False,
        timeout=2,
        env={"LATEXY_TEST_WORKSPACE": str(workspace)},
    )
    assert result.returncode == 0
    records = _decode_remote_batch(result.stdout)
    assert records[".pdf"] == files["resume.pdf"]
    assert records[".log"] == files["resume.log"]
    assert records["engine.stdout"] == files["engine.stdout"]
    assert records[".aux"] is None


def test_batch_remote_export_rejects_oversized_sparse_file(tmp_path):
    workspace = tmp_path / "remote-workspace"
    workspace.mkdir()
    with (workspace / "resume.pdf").open("wb") as oversized:
        oversized.truncate(20 * 1024 * 1024 + 1)
    script = _BATCH_EXPORT.replace(
        "path='/workspace/'+name", "path=os.environ['LATEXY_TEST_WORKSPACE']+'/'+name"
    )

    result = subprocess.run(
        [sys.executable, "-c", script, "resume"],
        capture_output=True,
        check=False,
        timeout=2,
        env={"LATEXY_TEST_WORKSPACE": str(workspace)},
    )
    assert result.returncode == 78
    # The exporter writes its fixed preamble before examining slots, but must
    # not frame or emit any bytes from the oversized artifact.
    assert result.stdout == _BATCH_EXPORT_MAGIC + bytes((len(_BATCH_EXPORT_SLOTS),))


def test_batch_export_rejects_nonzero_exit_and_never_materializes_partial_frame(tmp_path):
    sandbox = _ExportSandbox(_batch_payload({".pdf": b"partial"}), returncode=78)
    process = _adapter_process(tmp_path, sandbox)

    with pytest.raises(ModalEngineUnavailable, match="batch export rejected"):
        process.wait()
    assert not (tmp_path / "resume.pdf").exists()
    assert sandbox.terminated


def test_batch_export_rejects_truncated_payload_without_partial_artifacts(tmp_path):
    payload = _batch_payload({".pdf": b"pdf", ".log": b"log"})[:-2]
    sandbox = _ExportSandbox(payload)
    process = _adapter_process(tmp_path, sandbox)

    with pytest.raises(ModalEngineUnavailable, match="Truncated"):
        process.wait()
    assert not (tmp_path / "resume.pdf").exists()
    assert not (tmp_path / "resume.log").exists()
    assert sandbox.terminated


def test_batch_export_uses_remaining_session_deadline_and_rejects_late_response(tmp_path):
    records = {".pdf": b"pdf", "engine.stdout": b"logs"}
    holder = {}
    sandbox = _ExportSandbox(
        _batch_payload(records),
        on_read=lambda: setattr(holder["session"], "deadline", time.monotonic() - 1),
    )
    timer = SimpleNamespace(cancel=lambda: None)
    session = ModalEngineSession(
        sandbox, timer, time.monotonic() + 2, tmp_path, "kernel", "image", None
    )
    holder["session"] = session
    process = _adapter_process(tmp_path, sandbox, session=session)

    with pytest.raises(ModalEngineUnavailable, match="deadline exceeded"):
        process.wait()
    assert sandbox.calls[0][1]["timeout"] == 2
    assert sandbox.terminated
    assert not (tmp_path / "resume.pdf").exists()


def test_batch_export_caps_command_timeout_when_session_budget_is_long(tmp_path, monkeypatch):
    sandbox = _ExportSandbox(_batch_payload({}))
    timer = SimpleNamespace(cancel=lambda: None)
    session = ModalEngineSession(
        sandbox, timer, time.monotonic() + 180, tmp_path, "kernel", "image", None
    )
    observed = {}

    def read_batch(_sandbox, _basename, timeout):
        observed["timeout"] = timeout
        return {
            name: None for name, _limit in _BATCH_EXPORT_SLOTS
        }

    monkeypatch.setattr(
        "app.services.render_engine.modal_sandbox._read_remote_batch", read_batch
    )
    process = _adapter_process(tmp_path, sandbox, session=session)

    assert process.wait() == 0
    assert observed["timeout"] == 30


def test_batch_export_cancellation_during_stream_prevents_local_writes(tmp_path):
    holder = {}
    sandbox = _ExportSandbox(
        _batch_payload({".pdf": b"pdf", "engine.stdout": b"logs"}),
        on_read=lambda: holder["process"].kill(),
    )
    timer = SimpleNamespace(cancel=lambda: None)
    session = ModalEngineSession(
        sandbox, timer, time.monotonic() + 30, tmp_path, "kernel", "image", None
    )
    process = _adapter_process(tmp_path, sandbox, session=session)
    holder["process"] = process

    with pytest.raises(ModalEngineUnavailable, match="cancelled"):
        process.wait()
    assert sandbox.terminated
    assert not (tmp_path / "resume.pdf").exists()


def test_batch_parser_enforces_total_response_bound_before_parsing():
    oversized = b"x" * (_BATCH_EXPORT_MAX_BYTES + 1)
    with pytest.raises(ModalEngineUnavailable, match="exceeds limit"):
        _decode_remote_batch(oversized)


def test_batch_export_rejects_text_stream_from_bytes_api():
    sandbox = SimpleNamespace(
        exec=lambda *args, **kwargs: SimpleNamespace(stdout=iter(("not bytes",)), wait=lambda: 0)
    )
    from app.services.render_engine.modal_sandbox import _read_remote_batch

    with pytest.raises(ModalEngineUnavailable, match="Invalid remote artifact batch stream"):
        _read_remote_batch(sandbox, "resume", 5)


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


@pytest.mark.parametrize("expire", ["deadline", "closed"])
def test_session_upload_expiry_never_starts_another_engine(tmp_path, expire):
    sandbox = FakeSandbox()
    sdk, _ = fake_sdk(sandbox)
    first = request(tmp_path, sdk)
    session = first.renderer_session
    calls_before = len(sandbox.calls)

    def upload_and_expire(data, path):
        sandbox.upload(data, path)
        if expire == "deadline":
            session.deadline = time.monotonic() - 1
        else:
            session.close()

    sandbox.filesystem.write_bytes = upload_and_expire
    try:
        with pytest.raises(ModalEngineUnavailable, match="deadline"):
            create_modal_engine(workspace=tmp_path, compiler="lualatex", arguments=["resume.tex"],
                                timeout=1, sdk=sdk, enabled=True, image_id="im-cachedPureTeX",
                                session=session)
        assert len(sandbox.calls) == calls_before
        assert session.closed and sandbox.terminated
    finally:
        first.close()


def test_session_upload_failure_closes_vm(tmp_path):
    sandbox = FakeSandbox()
    sdk, _ = fake_sdk(sandbox)
    first = request(tmp_path, sdk)
    calls_before = len(sandbox.calls)

    def failed_upload(data, path):
        raise OSError("synthetic upload failure")

    sandbox.filesystem.write_bytes = failed_upload
    try:
        with pytest.raises(OSError, match="synthetic upload"):
            create_modal_engine(workspace=tmp_path, compiler="lualatex", arguments=["resume.tex"],
                                timeout=1, sdk=sdk, enabled=True, image_id="im-cachedPureTeX",
                                session=first.renderer_session)
        assert len(sandbox.calls) == calls_before
        assert first.renderer_session.closed and sandbox.terminated
    finally:
        first.close()
