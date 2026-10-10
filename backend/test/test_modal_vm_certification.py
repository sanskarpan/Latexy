"""Offline regressions for the operator-only Modal VM certification harness."""

import io
import os
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.services.render_engine.modal_sandbox import (
    _BATCH_EXPORT,
    _BATCH_EXPORT_HEADER,
    _BATCH_EXPORT_MAGIC,
    _BATCH_EXPORT_SLOTS,
    ModalEngineProcess,
)
from scripts import certify_modal_vm_engine as certification


class _RemoteProcess:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = io.BytesIO(stdout)
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode


class _FakeTextProcess:
    def __init__(self, output=b"", returncode=0):
        read_fd, write_fd = os.pipe()
        with os.fdopen(write_fd, "wb") as output_pipe:
            output_pipe.write(output)
        self.stdout = os.fdopen(read_fd, "rb")
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


class _FakeHangingTextProcess:
    def __init__(self):
        read_fd, self.write_fd = os.pipe()
        self.stdout = os.fdopen(read_fd, "rb")
        self.returncode = None
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True
        os.close(self.write_fd)
        self.returncode = -9


def _install_fake_pdftotext(monkeypatch, output_by_name, *, returncode=0):
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        assert command[0] == "/fake/bin/pdftotext"
        assert command[1:4] == ["-layout", "-enc", "UTF-8"]
        assert command[-1] == "-"
        return _FakeTextProcess(output_by_name.get(command[-2].split("/")[-1], b""), returncode)

    monkeypatch.setattr(certification.shutil, "which", lambda name: "/fake/bin/pdftotext" if name == "pdftotext" else None)
    monkeypatch.setattr(certification.subprocess, "Popen", fake_popen)
    return calls


class _FakeSandbox:
    def __init__(self, *, missing_pdf=None, marker=b"a" * 64 + b"\n"):
        self.files = {}
        self.missing_pdf = missing_pdf
        self.marker = marker
        self.compile_calls = []
        self.export_calls = []
        self.uploads = []
        self.terminated = False
        self.filesystem = SimpleNamespace(write_bytes=self._write_bytes)

    def _write_bytes(self, data, path):
        self.uploads.append((path, data))
        self.files[path] = data

    def exec(self, *args, **kwargs):
        if len(args) >= 4 and args[0:3] == ("python3", "-c", _BATCH_EXPORT):
            basename = args[3]
            payload = bytearray(_BATCH_EXPORT_MAGIC)
            payload.append(len(_BATCH_EXPORT_SLOTS))
            for index, (suffix, _limit) in enumerate(_BATCH_EXPORT_SLOTS):
                name = "engine.stdout" if suffix == "engine.stdout" else basename + suffix
                path = "/workspace/" + name
                self.export_calls.append(path)
                data = self.files.get(path)
                if data is None:
                    payload.extend(_BATCH_EXPORT_HEADER.pack(index, 0, 0))
                else:
                    payload.extend(_BATCH_EXPORT_HEADER.pack(index, 1, len(data)))
                    payload.extend(data)
            return _RemoteProcess(bytes(payload))

        if args[0:2] == ("python3", "-c"):
            return _RemoteProcess(self.marker)

        if len(args) >= 2 and args[1].endswith("sandbox_io_bridge.py"):
            jobname = next((arg.partition("=")[2] for arg in args if arg.startswith("-jobname=")), "resume")
            self.compile_calls.append((jobname, args, kwargs))
            self.files[f"/workspace/{jobname}.log"] = b"LuaTeX fixture log\n"
            self.files[f"/workspace/{jobname}.fls"] = b"INPUT resume.tex\n"
            self.files[f"/workspace/{jobname}.aux"] = b"fixture-specific aux\n"
            self.files["/workspace/engine.stdout"] = b"synthetic compiler output\n"
            if jobname != self.missing_pdf:
                self.files[f"/workspace/{jobname}.pdf"] = f"%PDF-synthetic-{jobname}".encode()
            return _RemoteProcess(returncode=0)

        raise AssertionError(f"Unexpected fake sandbox command: {args[:3]!r}")

    def terminate(self, **kwargs):
        self.terminated = True


class _FakeApp:
    @contextmanager
    def run(self):
        yield


def _install_fake_operator_environment(monkeypatch, tmp_path, *, missing_pdf=None, marker=None):
    sandbox = _FakeSandbox(missing_pdf=missing_pdf, marker=b"a" * 64 + b"\n" if marker is None else marker)
    fake_modal = SimpleNamespace(App=lambda _name: _FakeApp())
    monkeypatch.setitem(sys.modules, "modal", fake_modal)

    extracted_by_name = {
        "resume.pdf": b"Latin Bold",
        "hindi.pdf": "हिंदी".encode("utf-8"),
        "cjk.pdf": "日本語".encode("utf-8"),
    }
    poppler_calls = _install_fake_pdftotext(monkeypatch, extracted_by_name)

    constructed_basenames = []

    class RecordingModalEngineProcess(ModalEngineProcess):
        def __init__(self, sandbox_arg, process, workspace, basename):
            constructed_basenames.append(basename)
            super().__init__(sandbox_arg, process, workspace, basename)

    monkeypatch.setattr(certification, "ModalEngineProcess", RecordingModalEngineProcess)

    def create_engine(*, workspace, **_kwargs):
        sandbox.creation_options = _kwargs
        sandbox.files.update(
            {
                "/workspace/resume.pdf": b"%PDF-synthetic-resume",
                "/workspace/resume.log": b"LuaTeX fixture log\n",
                "/workspace/resume.fls": b"INPUT resume.tex\n",
                "/workspace/resume.aux": b"initial fixture aux\n",
                "/workspace/engine.stdout": (
                    b"AUDIT ROOT DENIED\nAUDIT ENVIRON DENIED\nAUDIT BOOTSTRAP DENIED\n"
                ),
            }
        )
        return RecordingModalEngineProcess(sandbox, _RemoteProcess(), workspace, "resume")

    monkeypatch.setattr(certification, "create_modal_engine", create_engine)
    fake_script = tmp_path / "fake-repo" / "backend" / "scripts" / "certify_modal_vm_engine.py"
    monkeypatch.setattr(certification, "__file__", str(fake_script))
    return sandbox, constructed_basenames, poppler_calls


def test_main_uses_case_jobnames_and_certifies_extracted_text(monkeypatch, tmp_path, capsys):
    sandbox, constructed, poppler_calls = _install_fake_operator_environment(monkeypatch, tmp_path)

    certification.main()

    assert [name for name, _, _ in sandbox.compile_calls] == ["hindi", "cjk"]
    assert all(f"-jobname={name}" in args for name, args, _ in sandbox.compile_calls)
    assert constructed == ["resume", "hindi", "cjk"]
    assert "/workspace/hindi.pdf" in sandbox.export_calls
    assert "/workspace/cjk.pdf" in sandbox.export_calls
    output = capsys.readouterr().out
    assert '"asset_fingerprint_discovered": true' in output
    assert '"asset_identity_comparison": "not_configured"' in output
    assert len(poppler_calls) == 3
    assert all(args[0][1:4] == ["-layout", "-enc", "UTF-8"] for args in poppler_calls)
    assert sandbox.terminated


def test_main_rejects_missing_case_pdf_instead_of_accepting_stale_resume_pdf(
    monkeypatch, tmp_path, capsys
):
    sandbox, constructed, poppler_calls = _install_fake_operator_environment(
        monkeypatch, tmp_path, missing_pdf="cjk"
    )

    with pytest.raises(RuntimeError, match="VM multilingual proof failed"):
        certification.main()

    # The initial proof left a valid resume.pdf in the same remote workspace,
    # but the CJK process is asked for (and must produce) cjk.pdf.
    assert "/workspace/resume.pdf" in sandbox.files
    assert "/workspace/cjk.pdf" not in sandbox.files
    assert "/workspace/cjk.pdf" in sandbox.export_calls
    assert [name for name, _, _ in sandbox.compile_calls] == ["hindi", "cjk"]
    assert constructed == ["resume", "hindi", "cjk"]
    output = capsys.readouterr().out
    assert '"case": "cjk"' in output
    assert '"pdf": false' in output
    assert '"text_and_glyphs_checked": false' in output
    assert len(poppler_calls) == 2
    assert sandbox.terminated


def test_main_cannot_certify_valid_fixture_outputs_without_asset_identity(
    monkeypatch, tmp_path
):
    sandbox, _, _ = _install_fake_operator_environment(monkeypatch, tmp_path, marker=b"not-a-fingerprint\n")

    with pytest.raises(RuntimeError, match="immutable renderer asset identity is unavailable"):
        certification.main()

    # A good-looking compile is not enough if its immutable image identity is
    # absent or malformed.
    assert [name for name, _, _ in sandbox.compile_calls] == ["hindi", "cjk"]
    assert sandbox.terminated


@pytest.mark.parametrize(
    ("log", "extracted"),
    [
        ("Missing character: There is no Devanagari glyph\n", "हिंदी"),
        ("! Undefined control sequence.\n", "हिंदी"),
        ("clean compile log\n", "\ufffdहंदी"),
        ("clean compile log\n", "unrelated text"),
    ],
)
def test_verify_fixture_rejects_glyph_errors_and_text_mismatch(
    monkeypatch, tmp_path, log, extracted
):
    pdf = tmp_path / "hindi.pdf"
    log_path = tmp_path / "hindi.log"
    pdf.write_bytes(b"nonempty synthetic PDF")
    log_path.write_text(log, encoding="utf-8")
    calls = _install_fake_pdftotext(monkeypatch, {"hindi.pdf": extracted.encode("utf-8")})

    assert not certification.verify_fixture(tmp_path, "hindi", "हिंदी")
    if "Missing character" in log or log.startswith("!"):
        assert calls == []


def test_main_requires_pdftotext_before_constructing_modal_app(monkeypatch):
    monkeypatch.setattr(certification.shutil, "which", lambda _name: None)
    fake_modal = SimpleNamespace(App=lambda _name: pytest.fail("Modal app must not be created"))
    monkeypatch.setitem(sys.modules, "modal", fake_modal)

    with pytest.raises(RuntimeError, match=r"pdftotext \(Poppler\) is required"):
        certification.main()


@pytest.mark.parametrize("arguments", [
    ["--image-id", "im-intended"],
    ["--expected-assets", "a" * 64],
    ["--image-id", "mutable-image-tag", "--expected-assets", "a" * 64],
    ["--image-id", "im-intended", "--expected-assets", "not-a-fingerprint"],
])
def test_invalid_operator_pins_fail_before_cloud_setup(monkeypatch, arguments):
    monkeypatch.setattr(certification.shutil, "which", lambda _name: pytest.fail("Tool discovery must follow pin validation"))
    with pytest.raises(SystemExit) as error:
        certification.main(arguments)
    assert error.value.code == 2


def test_configured_pin_reaches_preupload_adapter_check(monkeypatch, tmp_path, capsys):
    sandbox, _, _ = _install_fake_operator_environment(monkeypatch, tmp_path)
    certification.main(["--image-id", "im-intended", "--expected-assets", "a" * 64])
    assert sandbox.creation_options["image_id"] == "im-intended"
    assert sandbox.creation_options["expected_assets"] == "a" * 64
    output = capsys.readouterr().out
    assert '"asset_identity_comparison": "matched"' in output
    assert '"intended_image_and_assets_verified": true' in output
    assert '"default_resume_flow_certified": false' in output
    assert sandbox.terminated


def test_configured_pin_mismatch_never_certifies_fixture_results(monkeypatch, tmp_path):
    sandbox, _, poppler_calls = _install_fake_operator_environment(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="differs from the configured pin"):
        certification.main(["--image-id", "im-intended", "--expected-assets", "b" * 64])
    assert poppler_calls == []
    assert sandbox.compile_calls == []
    assert sandbox.terminated


def test_verify_fixture_rejects_nonzero_pdftotext_exit(monkeypatch, tmp_path):
    pdf = tmp_path / "hindi.pdf"
    log_path = tmp_path / "hindi.log"
    pdf.write_bytes(b"nonempty synthetic PDF")
    log_path.write_text("clean compile log\n", encoding="utf-8")
    _install_fake_pdftotext(monkeypatch, {"hindi.pdf": "हिंदी".encode("utf-8")}, returncode=1)

    assert not certification.verify_fixture(tmp_path, "hindi", "हिंदी")


def test_verify_fixture_bounds_pdftotext_output(monkeypatch, tmp_path):
    pdf = tmp_path / "hindi.pdf"
    log_path = tmp_path / "hindi.log"
    pdf.write_bytes(b"nonempty synthetic PDF")
    log_path.write_text("clean compile log\n", encoding="utf-8")
    monkeypatch.setattr(certification, "MAX_FIXTURE_TEXT_BYTES", 3)
    _install_fake_pdftotext(monkeypatch, {"hindi.pdf": "हिंदी".encode("utf-8")})

    assert not certification.verify_fixture(tmp_path, "hindi", "हिंदी")


def test_verify_fixture_times_out_and_kills_pdftotext(monkeypatch, tmp_path):
    pdf = tmp_path / "hindi.pdf"
    log_path = tmp_path / "hindi.log"
    pdf.write_bytes(b"nonempty synthetic PDF")
    log_path.write_text("clean compile log\n", encoding="utf-8")
    monkeypatch.setattr(certification.shutil, "which", lambda name: "/fake/bin/pdftotext" if name == "pdftotext" else None)
    monkeypatch.setattr(certification, "PDFTOTEXT_TIMEOUT_SECONDS", 0.01)
    process = _FakeHangingTextProcess()
    monkeypatch.setattr(certification.subprocess, "Popen", lambda *_args, **_kwargs: process)

    assert not certification.verify_fixture(tmp_path, "hindi", "हिंदी")
    assert process.killed
