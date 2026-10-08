from __future__ import annotations

import gzip
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import storage_service
from app.services.latex_service import find_recorder_read_escape
from app.utils.bounded_io import (
    MAX_COMPILE_LOG_BYTES,
    MAX_COMPILE_LOG_LINE_BYTES,
    MAX_COMPILED_PDF_BYTES,
    MAX_RECORDER_BYTES,
    BoundedReadError,
    BoundedTranscript,
    capture_process_output_bounded,
    iter_bounded_lines,
    read_file_bounded,
    read_gzip_file_bounded,
    read_httpx_response_bounded,
)
from app.workers import latex_worker


class _ChunkedResponse:
    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None):
        self.chunks = chunks
        self.headers = headers or {}
        self.chunk_sizes: list[int] = []
        self.iterations = 0

    async def aiter_bytes(self, *, chunk_size: int):
        self.chunk_sizes.append(chunk_size)
        for chunk in self.chunks:
            self.iterations += 1
            yield chunk


@pytest.mark.asyncio
async def test_http_response_declared_oversize_is_rejected_before_streaming():
    response = _ChunkedResponse([b"unused"], {"content-length": "11"})

    with pytest.raises(BoundedReadError):
        await read_httpx_response_bounded(response, 10)

    assert response.iterations == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{}, {"content-length": "not-a-number"}, {"content-length": "2"}])
async def test_http_response_chunked_or_lying_length_is_still_bounded(headers):
    response = _ChunkedResponse([b"abc", b"def"], headers)

    with pytest.raises(BoundedReadError):
        await read_httpx_response_bounded(response, 5)

    # The helper asks httpx for no more than max+1 decoded bytes at a time.
    assert response.chunk_sizes == [6]


def test_gzip_expansion_is_bounded_without_allocating_the_expanded_payload(tmp_path: Path):
    compressed = tmp_path / "resume.synctex.gz"
    compressed.write_bytes(gzip.compress(b"x" * 128 * 1024))

    with pytest.raises(BoundedReadError):
        read_gzip_file_bounded(
            compressed,
            max_compressed_bytes=compressed.stat().st_size,
            max_decompressed_bytes=1024,
        )


def test_gzip_compressed_input_is_bounded(tmp_path: Path):
    compressed = tmp_path / "resume.synctex.gz"
    compressed.write_bytes(gzip.compress(b"small"))

    with pytest.raises(BoundedReadError):
        read_gzip_file_bounded(
            compressed,
            max_compressed_bytes=compressed.stat().st_size - 1,
            max_decompressed_bytes=1024,
        )


def test_worker_drops_oversized_synctex_instead_of_caching_it(tmp_path: Path):
    (tmp_path / "resume.pdf").write_bytes(b"%PDF-1.7")
    (tmp_path / "resume.synctex.gz").write_bytes(gzip.compress(b"x" * 4096))
    redis = MagicMock()
    redis.exists.return_value = 0

    with (
        patch.object(latex_worker, "get_worker_redis", return_value=redis),
        patch.object(latex_worker, "MAX_SYNCTEX_COMPRESSED_BYTES", 1024),
        patch.object(latex_worker, "MAX_SYNCTEX_DECOMPRESSED_BYTES", 1024),
    ):
        latex_worker.cache_compile_output("job", tmp_path)

    assert all(call.args[0] != "latexy:job:job:synctex" for call in redis.set.call_args_list)


def test_compiled_pdf_cache_rejects_oversize_before_reading_payload(tmp_path: Path):
    redis = MagicMock()
    redis.exists.return_value = 0
    with (
        patch.object(latex_worker, "get_worker_redis", return_value=redis),
        patch.object(
            latex_worker,
            "read_file_bounded",
            side_effect=BoundedReadError("file exceeds byte limit"),
        ) as read_file,
    ):
        with pytest.raises(BoundedReadError):
            latex_worker.cache_compile_output("job", tmp_path)

    read_file.assert_called_once_with(tmp_path / "resume.pdf", MAX_COMPILED_PDF_BYTES)
    # A stale duplicate must not delete an artifact that a newer owner may
    # already have published for the same job.
    redis.delete.assert_not_called()


def test_compile_transcript_bounds_lines_and_retains_visible_tail():
    transcript = BoundedTranscript(max_bytes=256, max_line_bytes=32)
    for index in range(1000):
        transcript.append(f"line {index}: " + "x" * 200)

    text = transcript.text()
    assert len(text.encode("utf-8")) <= 256
    assert "compile log truncated" in text
    assert "line truncated" in text or "line 999" in text


def test_recorder_inspection_rejects_an_oversized_generated_file(tmp_path: Path):
    recorder = tmp_path / "resume.fls"
    recorder.write_bytes(b"INPUT /workspace/resume.tex\n" + b"x" * MAX_RECORDER_BYTES)

    violation = find_recorder_read_escape(recorder, "/workspace")

    assert violation is not None
    assert "exceeds" in violation


def test_regular_artifact_read_rejects_size_before_retaining_payload(tmp_path: Path):
    artifact = tmp_path / "artifact.pdf"
    artifact.write_bytes(b"x" * 32)

    with pytest.raises(BoundedReadError):
        read_file_bounded(artifact, 16)


@pytest.mark.parametrize("compressed", [False, True])
def test_generated_artifact_reader_rejects_outside_symlink(tmp_path, compressed):
    import gzip

    sentinel = tmp_path / "outside"
    sentinel.write_bytes(gzip.compress(b"synthetic-private-sentinel") if compressed else b"synthetic-private-sentinel")
    job = tmp_path / "job"
    job.mkdir()
    artifact = job / "resume.synctex"
    try:
        artifact.symlink_to(sentinel)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {type(exc).__name__}")
    with pytest.raises(BoundedReadError):
        if compressed:
            read_gzip_file_bounded(artifact, max_compressed_bytes=1024, max_decompressed_bytes=1024)
        else:
            read_file_bounded(artifact, 1024)


def test_regular_artifact_reader_rejects_fifo_without_blocking(tmp_path):
    import os

    if not hasattr(os, "mkfifo"):
        pytest.skip("POSIX FIFO fixture")
    artifact = tmp_path / "resume.synctex"
    os.mkfifo(artifact)
    with pytest.raises(BoundedReadError):
        read_file_bounded(artifact, 1024)


def test_artifact_reader_rejects_directory_handles(tmp_path):
    with pytest.raises(BoundedReadError):
        read_file_bounded(tmp_path, 1024)


def test_no_follow_checks_file_at_open_not_an_earlier_path_check(tmp_path, monkeypatch):
    import os

    if os.name == "nt":
        pytest.skip("POSIX atomic open fixture; Windows uses OPEN_REPARSE_POINT")
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"synthetic-private-sentinel")
    artifact = tmp_path / "resume.synctex"
    artifact.write_bytes(b"ordinary")
    original = os.open
    def replace_then_open(path, flags, *args, **kwargs):
        artifact.unlink()
        artifact.symlink_to(sentinel)
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", replace_then_open)
    with pytest.raises(BoundedReadError):
        read_file_bounded(artifact, 1024)


def test_windows_same_handle_read_survives_post_open_path_replacement(tmp_path, monkeypatch):
    import os

    if os.name != "nt":
        pytest.skip("actual Windows handle proof")
    import ctypes
    from ctypes import wintypes
    from types import SimpleNamespace

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    prototype = ctypes.WINFUNCTYPE(wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD,
        wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.argtypes = list(prototype._argtypes_)
    kernel.CreateFileW.restype = wintypes.HANDLE
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"original-safe-artifact")
    @prototype
    def open_then_replace(*arguments):
        handle = kernel.CreateFileW(*arguments)
        artifact.replace(tmp_path / "held-original")
        artifact.write_bytes(b"replacement-path-content")
        return handle
    proxy = SimpleNamespace(CreateFileW=open_then_replace,
        GetFileInformationByHandle=kernel.GetFileInformationByHandle, CloseHandle=kernel.CloseHandle)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: proxy)
    assert read_file_bounded(artifact, 1024) == b"original-safe-artifact"
    assert artifact.read_bytes() == b"replacement-path-content"


@pytest.mark.parametrize("rename", [False, True])
def test_actual_confined_lua_link_never_becomes_a_trusted_artifact(tmp_path, rename):
    import json
    import shutil
    import subprocess
    import sys

    if sys.platform != "linux" or not shutil.which("lualatex"):
        pytest.skip("requires actual Linux Lua kernel launcher")
    from app.services.latex_service import engine_env, engine_sandbox_flags, native_engine_command

    sentinel = tmp_path / "outside-sentinel"
    sentinel.write_bytes(b"synthetic-private-sentinel")
    job = tmp_path / "job"
    job.mkdir()
    if rename:
        # Independently check output renaming without weakening LuaTeX's
        # existing rejection of link creation under no-shell-escape.
        (job / "intermediate-link").symlink_to(sentinel)
        lua = 'assert(os.rename("intermediate-link","untrusted-output"));'
    else:
        lua = f'local lfs=require("lfs"); assert(lfs.link({json.dumps(str(sentinel))},"untrusted-output",true));'
    source = r"\documentclass{article}\begin{document}\directlua{" + lua + r"}Safe visible text\end{document}"
    (job / "resume.tex").write_text(source, encoding="utf-8")
    command = native_engine_command("lualatex", [*engine_sandbox_flags("lualatex"),
        "-interaction=nonstopmode", "-halt-on-error", "-jobname", "resume", "resume.tex"], job)
    result = subprocess.run(command, cwd=job, env=engine_env(job, "lualatex"),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
    if result.returncode:
        assert b"LuaTeX: operation not permitted" in result.stdout, result.stdout[-2000:].decode("utf-8", "replace")
        assert not (job / "untrusted-output").exists()
        return
    assert (job / "resume.pdf").read_bytes().startswith(b"%PDF-")
    assert (job / "untrusted-output").is_symlink()
    with pytest.raises(BoundedReadError):
        read_file_bounded(job / "untrusted-output", 1024)


def test_pdfminer_sink_aborts_before_retaining_oversized_text():
    sink = latex_worker._BoundedPdfTextWriter(4)

    assert sink.write("abc") == 3
    with pytest.raises(BoundedReadError):
        sink.write("de")


def test_pdftotext_pipe_kills_converter_on_output_overflow(monkeypatch):
    class _Pipe:
        def read(self, size: int) -> bytes:
            return b"x" * size

        def close(self) -> None:
            pass

    class _Process:
        def __init__(self):
            self.stdout = _Pipe()
            self.returncode = None

        def kill(self):
            self.returncode = -9

        def poll(self):
            return self.returncode

        def wait(self):
            if self.returncode is None:
                self.returncode = 0

    process = _Process()
    monkeypatch.setattr(latex_worker.subprocess, "Popen", lambda *args, **kwargs: process)

    extracted, blocked = latex_worker._run_pdftotext_bounded("pdftotext", Path("resume.pdf"))

    assert extracted is None
    assert blocked is True
    assert process.returncode == -9


class _BoundedReadStream:
    def __init__(self, payload: bytes | str):
        self.payload = payload
        self.read_sizes: list[int] = []

    def read(self, size: int):
        self.read_sizes.append(size)
        if not self.payload:
            return b"" if isinstance(self.payload, bytes) else ""
        chunk = self.payload[:size]
        self.payload = self.payload[size:]
        return chunk


class _AsyncBoundedReadStream(_BoundedReadStream):
    async def read(self, size: int):
        return super().read(size)


def test_iter_bounded_lines_never_requests_or_retains_a_giant_line():
    stream = _BoundedReadStream(b"x" * (MAX_COMPILE_LOG_LINE_BYTES * 20))

    lines = list(iter_bounded_lines(stream))

    assert stream.read_sizes
    assert max(stream.read_sizes) <= MAX_COMPILE_LOG_LINE_BYTES
    assert lines
    assert all(len(line.encode("utf-8")) <= MAX_COMPILE_LOG_LINE_BYTES for line in lines)


def test_iter_bounded_lines_rejects_iterable_before_consuming_it():
    consumed = False

    def unsupported_stream():
        nonlocal consumed
        consumed = True
        yield b"x" * (MAX_COMPILE_LOG_LINE_BYTES * 20)

    with pytest.raises(BoundedReadError, match="bounded reads"):
        list(iter_bounded_lines(unsupported_stream()))

    assert consumed is False


@pytest.mark.asyncio
async def test_capture_process_output_drains_giant_multibyte_lines_with_bounded_reads():
    stdout = _AsyncBoundedReadStream("é" * (MAX_COMPILE_LOG_LINE_BYTES * 64))
    stderr = _AsyncBoundedReadStream(b"error\n" * 1000)
    process = MagicMock(stdout=stdout, stderr=stderr)
    process.wait = AsyncMock()

    text = await capture_process_output_bounded(process)

    assert max(stdout.read_sizes) <= MAX_COMPILE_LOG_LINE_BYTES
    assert max(stderr.read_sizes) <= MAX_COMPILE_LOG_LINE_BYTES
    assert len(text.encode("utf-8")) <= MAX_COMPILE_LOG_BYTES
    assert "compile log truncated" in text


@pytest.mark.asyncio
async def test_capture_process_output_rejects_an_unbounded_second_pipe():
    process = MagicMock(stdout=_AsyncBoundedReadStream(b"ok\n"), stderr=MagicMock())

    with pytest.raises(BoundedReadError):
        await capture_process_output_bounded(process)


class _Body:
    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.read_sizes: list[int] = []
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if size >= 0 and len(chunk) > size:
            self.chunks.insert(0, chunk[size:])
            return chunk[:size]
        return chunk

    def close(self) -> None:
        self.closed = True


def test_storage_declared_oversize_is_rejected_before_read():
    body = _Body([b"unused"])
    client = MagicMock()
    client.get_object.return_value = {"Body": body, "ContentLength": 11}

    with patch.object(storage_service, "_get_client", return_value=client):
        with pytest.raises(storage_service.StorageObjectTooLarge):
            storage_service.download_bytes("object", max_bytes=10)

    client.head_object.assert_not_called()
    assert body.closed is True
    assert body.read_sizes == []


def test_storage_bounded_download_uses_one_request_and_checks_actual_bytes():
    body = _Body([b"PDF bytes"])
    client = MagicMock()
    client.head_object.side_effect = AssertionError("redundant storage round trip")
    # Incorrect length metadata must not truncate the actual payload or allow
    # a caller's cap to be exceeded; the stream, not the header, is authoritative.
    client.get_object.return_value = {"Body": body, "ContentLength": 1}

    with patch.object(storage_service, "_get_client", return_value=client):
        assert storage_service.download_bytes("object", max_bytes=9) == b"PDF bytes"

    client.get_object.assert_called_once()
    assert body.closed is True
    assert all(0 < size <= 10 for size in body.read_sizes)


@pytest.mark.parametrize("code", ["404", "NoSuchKey"])
def test_storage_missing_object_uses_get_and_returns_none(code):
    from botocore.exceptions import ClientError

    client = MagicMock()
    client.get_object.side_effect = ClientError({"Error": {"Code": code}}, "GetObject")
    with patch.object(storage_service, "_get_client", return_value=client):
        assert storage_service.download_bytes("missing", max_bytes=10) is None
    client.head_object.assert_not_called()


def test_storage_missing_length_is_bounded_and_closes_body():
    body = _Body([b"123456", b"789"])
    client = MagicMock()
    client.head_object.return_value = {}
    client.get_object.return_value = {"Body": body}

    with patch.object(storage_service, "_get_client", return_value=client):
        with pytest.raises(storage_service.StorageObjectTooLarge):
            storage_service.download_bytes("object", max_bytes=8)

    assert body.closed is True
    assert body.read_sizes[-1] <= 3  # remaining budget + one byte


def test_storage_get_content_length_is_checked_and_body_is_closed():
    body = _Body([b"unused"])
    client = MagicMock()
    client.head_object.return_value = {}
    client.get_object.return_value = {"Body": body, "ContentLength": 11}

    with patch.object(storage_service, "_get_client", return_value=client):
        with pytest.raises(storage_service.StorageObjectTooLarge):
            storage_service.download_bytes("object", max_bytes=10)

    assert body.closed is True
    assert body.read_sizes == []
