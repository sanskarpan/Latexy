"""Offline regressions for the operator-only Modal VM certification harness."""

import base64
import io
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.services.render_engine.modal_sandbox import _BOUNDED_EXPORT, ModalEngineProcess
from scripts import certify_modal_vm_engine as certification


class _RemoteProcess:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = io.BytesIO(stdout)
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode


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
        if len(args) >= 3 and args[0:2] == ("python3", "-c") and args[2] == _BOUNDED_EXPORT:
            path = args[3]
            self.export_calls.append(path)
            if path not in self.files:
                return _RemoteProcess(returncode=44)
            return _RemoteProcess(base64.b64encode(self.files[path]))

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

    import pdfminer.high_level

    extracted_by_name = {
        "resume.pdf": "Latin Bold",
        "hindi.pdf": "हिंदी",
        "cjk.pdf": "日本語",
    }
    monkeypatch.setattr(
        pdfminer.high_level,
        "extract_text",
        lambda pdf: extracted_by_name.get(pdf.name, ""),
    )

    constructed_basenames = []

    class RecordingModalEngineProcess(ModalEngineProcess):
        def __init__(self, sandbox_arg, process, workspace, basename):
            constructed_basenames.append(basename)
            super().__init__(sandbox_arg, process, workspace, basename)

    monkeypatch.setattr(certification, "ModalEngineProcess", RecordingModalEngineProcess)

    def create_engine(*, workspace, **_kwargs):
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
    return sandbox, constructed_basenames


def test_main_uses_case_jobnames_and_certifies_extracted_text(monkeypatch, tmp_path, capsys):
    sandbox, constructed = _install_fake_operator_environment(monkeypatch, tmp_path)

    certification.main()

    assert [name for name, _, _ in sandbox.compile_calls] == ["hindi", "cjk"]
    assert all(f"-jobname={name}" in args for name, args, _ in sandbox.compile_calls)
    assert constructed == ["resume", "hindi", "cjk"]
    assert "/workspace/hindi.pdf" in sandbox.export_calls
    assert "/workspace/cjk.pdf" in sandbox.export_calls
    assert '"asset_identity_verified": true' in capsys.readouterr().out
    assert sandbox.terminated


def test_main_rejects_missing_case_pdf_instead_of_accepting_stale_resume_pdf(
    monkeypatch, tmp_path, capsys
):
    sandbox, constructed = _install_fake_operator_environment(
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
    assert sandbox.terminated


def test_main_cannot_certify_valid_fixture_outputs_without_asset_identity(
    monkeypatch, tmp_path
):
    sandbox, _ = _install_fake_operator_environment(monkeypatch, tmp_path, marker=b"not-a-fingerprint\n")

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
        ("clean compile log\n", "unrelated text"),
    ],
)
def test_verify_fixture_rejects_glyph_errors_and_text_mismatch(
    monkeypatch, tmp_path, log, extracted
):
    import pdfminer.high_level

    pdf = tmp_path / "hindi.pdf"
    log_path = tmp_path / "hindi.log"
    pdf.write_bytes(b"nonempty synthetic PDF")
    log_path.write_text(log, encoding="utf-8")
    monkeypatch.setattr(pdfminer.high_level, "extract_text", lambda _pdf: extracted)

    assert not certification.verify_fixture(tmp_path, "hindi", "हिंदी")
