"""
LaTeX compilation worker — event-driven rebuild.

Streams pdflatex log lines via publish_event() instead of collecting
them all at once.  Uses subprocess.Popen for line-by-line stdout
streaming.  All Redis I/O goes through the synchronous event_publisher helpers;
the only asyncio here is the short-lived asyncio.run() used to reconcile the
Compilation row (SQLAlchemy async engine has no sync counterpart in this app).
"""

import asyncio
import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from celery.exceptions import SoftTimeLimitExceeded

from ..core.celery_app import celery_app, get_task_priority
from ..core.config import get_compile_timeout, resolve_plan_family, settings
from ..core.logging import get_logger
from ..core.observability import record_compile
from ..core.tracing import traced
from ..services.auto_fit_service import (
    AUTO_FIT_PROFILES,
    apply_auto_fit,
    profile_for_intensity,
    remove_auto_fit,
)
from ..services.cover_letter_signature_service import materialize_embedded_signature
from ..services.latex_service import (
    ENGINE_READ_ESCAPE_ERROR,
    LATEX_SANDBOX_FLAGS,
    RECORDER_SUFFIX,
    assert_local_engine_allowed,
    cleanup_docker_container,
    docker_container_name,
    docker_engine_available,
    docker_sandbox_args,
    engine_env,
    find_engine_read_escape,
    find_recorder_read_escape,
    latex_service,
)
from ..utils.bounded_io import (
    MAX_COMPILED_PDF_BYTES,
    MAX_SYNCTEX_COMPRESSED_BYTES,
    MAX_SYNCTEX_DECOMPRESSED_BYTES,
    BoundedReadError,
    BoundedTranscript,
    decode_base64_bounded,
    iter_bounded_lines,
    read_file_bounded,
    read_gzip_file_bounded,
    read_text_file_bounded,
)
from ..utils.process_watchdog import ProcessWatchdog
from ..workers.event_publisher import (
    _DEFAULT_TTL,
    get_worker_redis,
    is_cancelled,
    publish_event,
    publish_job_result,
)
from ..workers.job_lifecycle import (
    admit_worker,
    begin_finalizing,
    current_owner_epoch,
    lifecycle_key,
    write_owned_artifacts,
)
from ..workers.quota_refund import clear_quota_refund_receipt, refund_quota_once

logger = get_logger(__name__)

PAGE_COUNT_RE = re.compile(r"Output written on .*?\((\d+) page", re.IGNORECASE)
BEAMER_RE = re.compile(r"\\documentclass\s*(?:\[.*?\])?\s*\{beamer\}", re.DOTALL)
_MAX_EXTRA_PACKAGES = 64


def _strip_latex_comments(latex_content: str) -> str:
    """Remove TeX comments while preserving escaped percent signs/newlines."""
    cleaned: list[str] = []
    for line in latex_content.splitlines(keepends=True):
        backslashes = 0
        comment_at: Optional[int] = None
        for index, char in enumerate(line):
            if char == "%" and backslashes % 2 == 0:
                comment_at = index
                break
            if char == "\\":
                backslashes += 1
            else:
                backslashes = 0
        if comment_at is None:
            cleaned.append(line)
        else:
            prefix = line[:comment_at]
            cleaned.append(prefix + ("\n" if line.endswith("\n") else ""))
    return "".join(cleaned)


def is_beamer_document(latex_content: str) -> bool:
    """Return whether an uncommented documentclass selects Beamer."""
    return bool(BEAMER_RE.search(_strip_latex_comments(latex_content)))

# Flags allowed to be appended from compile_settings (must match resume_routes whitelist)
# NOTE: --shell-escape is intentionally excluded — it enables arbitrary code execution
_ALLOWED_EXTRA_FLAGS = {
    "--file-line-error",
}
# Note: --synctex=1 and --interaction=nonstopmode are always on. Halt-on-error
# defaults on but is a validated per-resume boolean (B19.6).

_MAIN_FILE_RE = re.compile(r"^[a-zA-Z0-9_-]+\.tex$")
_MAX_REFERENCE_LIBRARY_BYTES = 5_000_000
_MAX_EXTRACTED_TEXT_BYTES = 4 * 1024 * 1024
_PDFTOTEXT_READ_CHUNK_BYTES = 64 * 1024
_HOST_PDFTOTEXT_CANDIDATES = (
    "/opt/homebrew/bin/pdftotext",
    "/usr/local/bin/pdftotext",
    "/usr/bin/pdftotext",
)

# Watermark validation
_WATERMARK_RE = re.compile(r"^[A-Za-z0-9 \-\.]+$")
_WATERMARK_MAX_LEN = 30

_PDFTOTEXT_FALLBACK_PATHS = (
    "/opt/homebrew/bin/pdftotext",
    "/usr/local/bin/pdftotext",
    "/usr/bin/pdftotext",
)

# Successful exact-input compiles can be reused for a day. The epoch is part of
# every key so a compiler-image or cache-format change can invalidate all old
# entries without scanning Redis. Operators may override it per deployment.
_COMPILE_CACHE_TTL = 86400
_COMPILE_CACHE_EPOCH = os.environ.get("LATEXY_COMPILE_CACHE_EPOCH", "v1")


def _refund_compile_quota_once(
    job_id: str,
    quota_refund: Optional[Dict[str, Any]],
) -> bool:
    """Compatibility wrapper for the compile worker's terminal paths."""
    return refund_quota_once(
        job_id,
        quota_refund,
        expected_dimension="compilations",
    )


# ------------------------------------------------------------------ #
#  Timing instrumentation (#1281 — "Compile latency: 37s median ->    #
#  target <10s"). Production measurement showed ~8s job submit + ~24s#
#  more of opaque "processing" before completion, with the job's own #
#  reported compilation_time at ~15.5s — i.e. roughly half the       #
#  "processing" window is unaccounted for by the one number we       #
#  already report. These helpers break that window into phases that #
#  get logged as structured (grep-able) fields instead of prose, so  #
#  the next measurement shows which phase actually dominates:        #
#    - queue_wait_seconds: job creation (API writes :meta.submitted_at)  #
#      to this worker picking the task up.                            #
#    - cold_start_seconds: only set for the FIRST task this worker    #
#      process (== this Modal container) handles — the gap between    #
#      module import (proxy for container start) and task start, i.e. #
#      container boot + image pull. None on every task after that,    #
#      i.e. on a warm min_containers=1 container.                      #
#    - compile_subprocess_seconds: the pdflatex/xelatex/lualatex        #
#      subprocess itself (already computed elsewhere as                #
#      compilation_time — reused, not duplicated).                     #
#    - reporting_seconds: everything after the subprocess exits —      #
#      recorder-escape check, log/PDF caching to Redis, Compilation    #
#      row reconcile (+ MinIO upload), event publishing.               #
# ------------------------------------------------------------------ #

# Stamped once, at import time — this module is imported fresh in every worker
# OS process (a Celery worker fork, or a Modal container for run_latex_task /
# run_orchestrator_task), so this is a reliable proxy for "this process started".
_PROCESS_STARTED_AT = time.monotonic()
_first_task_lock = threading.Lock()
_first_task_seen = False


def consume_cold_start_seconds() -> Optional[float]:
    """Elapsed time since this worker process started, but only once.

    The first caller (the first task this process handles) gets the real gap;
    every later call returns None so a warm container's fast tasks are never
    mislabeled as cold starts.
    """
    global _first_task_seen
    with _first_task_lock:
        if _first_task_seen:
            return None
        _first_task_seen = True
        return time.monotonic() - _PROCESS_STARTED_AT


def compute_queue_wait_seconds(job_id: str) -> Optional[float]:
    """Time between job creation and this worker picking the task up.

    Reads the :meta key the API writes (with submitted_at) at submission time
    (see job_routes._write_initial_redis_state), before the task is dispatched.
    Best-effort: returns None when there is no meta (e.g. a task invoked
    directly in a unit test, or a compile path that skips the API's initial
    Redis write) rather than raising, since this is diagnostics, not a
    correctness dependency.
    """
    try:
        raw = get_worker_redis().get(f"latexy:job:{job_id}:meta")
        if not raw:
            return None
        submitted_at = json.loads(raw).get("submitted_at")
        if not submitted_at:
            return None
        return max(0.0, time.time() - float(submitted_at))
    except Exception:
        return None


def _inject_watermark(latex_content: str, watermark_text: str) -> str:
    """Inject draftwatermark directives immediately before \\begin{document}."""
    marker = r"\begin{document}"
    pos = latex_content.find(marker)
    if pos == -1:
        return latex_content  # Validation should have caught this; leave unchanged
    watermark_block = (
        "\\usepackage{draftwatermark}\n"
        f"\\SetWatermarkText{{{watermark_text}}}\n"
        "\\SetWatermarkScale{1.2}\n"
        "\\SetWatermarkColor[gray]{0.94}\n"
    )
    return latex_content[:pos] + watermark_block + latex_content[pos:]


def _inject_packages(latex_content: str, packages: list) -> str:
    """Prepend \\usepackage{pkg} directives after \\documentclass line for any missing package."""
    # Validate again at the worker boundary; persisted metadata and queue
    # payloads must never be interpolated as arbitrary TeX primitives.
    # Legacy metadata can bypass ResumeSettingsUpdate. Bound the raw list
    # before filtering/deduplicating so stale JSON cannot cause unbounded work.
    packages = packages[:_MAX_EXTRA_PACKAGES] if isinstance(packages, list) else []
    packages = list(dict.fromkeys(
        pkg for pkg in packages
        if isinstance(pkg, str) and re.fullmatch(r"[a-zA-Z0-9-]{1,50}", pkg)
    ))
    docclass_match = re.search(r"\\documentclass\s*(?:\[[^\]]*\]\s*)?\{[^}]+\}", latex_content)
    if not docclass_match:
        return latex_content  # Can't find safe insertion point
    insert_pos = docclass_match.end()
    # Treat a package as present regardless of optional arguments or harmless
    # whitespace variations (``\\usepackage[table]{xcolor}``,
    # ``\\usepackage {xcolor}``, and grouped package lists). Injecting a second
    # declaration can produce an option clash and is never needed.
    package_source = _strip_latex_comments(latex_content)
    loaded_packages = set()
    for match in re.finditer(
        r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\]\s*)?\{([^}]*)\}",
        package_source,
        re.DOTALL,
    ):
        loaded_packages.update(name.strip() for name in match.group(1).split(","))
    lines_to_insert = [
        f"\\usepackage{{{pkg}}}"
        for pkg in packages
        if pkg not in loaded_packages
    ]
    if not lines_to_insert:
        return latex_content
    return latex_content[:insert_pos] + "\n" + "\n".join(lines_to_insert) + "\n" + latex_content[insert_pos:]


def _inject_draft_graphics(latex_content: str) -> str:
    """Ask graphicx to keep image boxes but skip decoding/rasterization."""
    option_list = r"(?:^|,)\s*draft\s*(?:,|$)"
    documentclass = re.search(
        r"\\documentclass\s*(?:\[([^\]]*)\]\s*)?\{[^}]+\}",
        latex_content,
        re.DOTALL,
    )
    if not documentclass:
        return latex_content
    if documentclass.group(1) and re.search(option_list, documentclass.group(1)):
        return latex_content
    for expression in (
        r"\\usepackage\s*\[([^\]]*)\]\s*\{[^}]*\bgraphicx\b[^}]*\}",
        r"\\PassOptionsToPackage\s*\{([^}]*)\}\s*\{[^}]*\bgraphicx\b[^}]*\}",
    ):
        for options in re.findall(expression, latex_content, re.DOTALL):
            if re.search(option_list, options):
                return latex_content
    insertion = "\n\\PassOptionsToPackage{draft}{graphicx} % Latexy draft mode\n"
    return latex_content[: documentclass.end()] + insertion + latex_content[documentclass.end() :]


def _probe_auto_fit_candidate(
    *,
    job_id: str,
    latex_content: str,
    profile_intensity: int,
    compiler: str,
    main_file: str,
    custom_flags: list[str],
    error_mode_flags: list[str],
    bibtex: object,
    timeout: float,
) -> tuple[bool, Optional[int], str]:
    """Compile an isolated fit candidate without publishing its artifact or log."""
    probe_dir = Path(settings.TEMP_DIR) / f"{job_id}-autofit-{profile_intensity}"
    container_name: Optional[str] = None
    try:
        probe_dir.mkdir(parents=True, exist_ok=False)
        (probe_dir / main_file).write_text(latex_content, encoding="utf-8")
        materialize_embedded_signature(latex_content, probe_dir)
        write_reference_library(probe_dir, bibtex)
        use_docker = docker_engine_available()
        container_name = docker_container_name(job_id, "probe") if use_docker else None
        if use_docker:
            command = [
                "docker",
                "run",
                "--rm",
                "--name",
                container_name,
                *docker_sandbox_args(),
                "-v",
                f"{probe_dir}:/workspace",
                "-w",
                "/workspace",
                settings.LATEX_DOCKER_IMAGE,
                compiler,
                *LATEX_SANDBOX_FLAGS,
                *error_mode_flags,
                "-output-directory",
                "/workspace",
                "-jobname",
                "resume",
                *custom_flags,
                main_file,
            ]
            compile_cwd = None
            workspace = "/workspace"
        else:
            assert_local_engine_allowed(job_id)
            command = [
                compiler,
                *LATEX_SANDBOX_FLAGS,
                *error_mode_flags,
                "-jobname",
                "resume",
                "-output-directory",
                ".",
                *custom_flags,
                main_file,
            ]
            compile_cwd = str(probe_dir)
            workspace = str(probe_dir)

        completed = subprocess.run(
            command,
            cwd=compile_cwd,
            env=engine_env(),
            # The compiler log is the bounded source of diagnostics/page
            # counts.  Do not let a generated document fill subprocess pipes.
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=max(1.0, timeout),
        )
        log_file = probe_dir / "resume.log"
        transcript = read_text_file_bounded(log_file) if log_file.is_file() else ""
        for line in transcript.splitlines():
            transcript_escape = find_engine_read_escape(line, workspace)
            if transcript_escape:
                logger.warning(
                    "Auto-fit probe %s read outside its jail: %s",
                    job_id,
                    transcript_escape,
                )
                return False, None, ENGINE_READ_ESCAPE_ERROR
        recorder_escape = find_recorder_read_escape(
            probe_dir / f"resume{RECORDER_SUFFIX}",
            workspace,
            require_recorder=completed.returncode == 0,
        )
        if recorder_escape:
            logger.warning(
                "Auto-fit probe %s recorder read outside its jail: %s",
                job_id,
                recorder_escape,
            )
            return False, None, ENGINE_READ_ESCAPE_ERROR
        counts = [int(match.group(1)) for match in PAGE_COUNT_RE.finditer(transcript)]
        page_count = counts[-1] if counts else None
        success = completed.returncode == 0 and (probe_dir / "resume.pdf").exists()
        return success, page_count, "" if success else f"{compiler} probe failed"
    except subprocess.TimeoutExpired:
        return False, None, "Auto-fit probe timed out"
    finally:
        cleanup_docker_container(container_name)
        if probe_dir.exists():
            shutil.rmtree(probe_dir, ignore_errors=True)


def write_reference_library(job_dir: Path, bibtex: object) -> bool:
    """Materialize the saved, read-only provider snapshot as references.bib."""
    if not isinstance(bibtex, str) or not bibtex.strip() or "\x00" in bibtex:
        return False
    encoded = bibtex.encode("utf-8")
    if len(encoded) > _MAX_REFERENCE_LIBRARY_BYTES:
        logger.warning("Saved reference library exceeds the compile sidecar limit")
        return False
    (job_dir / "references.bib").write_bytes(encoded)
    return True


def _resolve_pdftotext_binary() -> Optional[str]:
    """Find a usable host pdftotext binary for ATS text extraction."""
    binary = shutil.which("pdftotext")
    if binary:
        return binary
    for candidate in _PDFTOTEXT_FALLBACK_PATHS:
        if Path(candidate).exists():
            return candidate
    return None


def _run_pdftotext_bounded(
    binary: str,
    pdf_file: Path,
    *,
    timeout: float = 10,
) -> tuple[Optional[str], bool]:
    """Run pdftotext through a capped pipe and kill it on output overflow.

    Returning ``(text, blocked)`` lets callers distinguish an ordinary converter
    failure (which may use the pdfminer fallback) from a resource-bound failure.
    The latter must not be handed to another extractor and repeated indefinitely.
    """
    proc = subprocess.Popen(
        [binary, "-layout", str(pdf_file), "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    stdout = proc.stdout
    if stdout is None:
        proc.kill()
        proc.wait()
        return None, True

    watchdog = ProcessWatchdog(proc, timeout=timeout).start()
    output = bytearray()
    overflowed = False
    try:
        while True:
            chunk = stdout.read(
                min(_PDFTOTEXT_READ_CHUNK_BYTES, _MAX_EXTRACTED_TEXT_BYTES - len(output) + 1)
            )
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > _MAX_EXTRACTED_TEXT_BYTES:
                overflowed = True
                proc.kill()
                break
    except (OSError, ValueError):
        overflowed = True
        try:
            proc.kill()
        except (OSError, ProcessLookupError):
            pass
    finally:
        watchdog_reason = watchdog.stop()
        if proc.poll() is None:
            try:
                proc.kill()
            except (OSError, ProcessLookupError):
                pass
        proc.wait()
        stdout.close()

    if overflowed or watchdog_reason == "timeout":
        return None, True
    if proc.returncode != 0:
        return None, False
    return bytes(output).decode("utf-8", errors="replace"), False


class _BoundedPdfTextWriter(io.TextIOBase):
    """Text sink that aborts pdfminer before retaining oversized output."""

    def __init__(self, max_bytes: int) -> None:
        super().__init__()
        self._max_bytes = max_bytes
        self._size = 0
        self._chunks: list[str] = []

    def write(self, value: str) -> int:
        if not isinstance(value, str):
            value = str(value)
        encoded = value.encode("utf-8", errors="replace")
        if self._size + len(encoded) > self._max_bytes:
            raise BoundedReadError("extracted PDF text exceeds byte limit")
        self._chunks.append(value)
        self._size += len(encoded)
        return len(value)

    def getvalue(self) -> str:
        return "".join(self._chunks)


def _extract_pdfminer_text_bounded(pdf_file: Path) -> Optional[str]:
    """Extract PDF text through pdfminer's streaming device with a hard sink cap."""
    # Keep the fallback used by lightweight test doubles (which intentionally do
    # not materialize a PDF) while all real files use the bounded device below.
    if not pdf_file.is_file():
        from pdfminer.high_level import extract_text

        extracted = extract_text(str(pdf_file))
        if not extracted:
            return None
        encoded = extracted.encode("utf-8", errors="replace")
        if len(encoded) > _MAX_EXTRACTED_TEXT_BYTES:
            raise BoundedReadError("extracted PDF text exceeds byte limit")
        return extracted if extracted.strip() else None

    from pdfminer.converter import TextConverter
    from pdfminer.layout import LAParams
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage

    sink = _BoundedPdfTextWriter(_MAX_EXTRACTED_TEXT_BYTES)
    resource_manager = PDFResourceManager()
    device = TextConverter(resource_manager, sink, laparams=LAParams())
    try:
        with pdf_file.open("rb") as handle:
            interpreter = PDFPageInterpreter(resource_manager, device)
            for page in PDFPage.get_pages(handle):
                interpreter.process_page(page)
        extracted = sink.getvalue()
        return extracted if extracted.strip() else None
    finally:
        device.close()


def _extract_pdf_text(pdf_file: Path, job_id: str) -> Optional[str]:
    """Extract text from the compiled PDF with host pdftotext, then pdfminer fallback."""
    pdftotext_bin = _resolve_pdftotext_binary()
    if pdftotext_bin:
        # Real artifacts stream directly through a capped pipe. The temporary
        # output-file branch only supports existing test doubles that report
        # stdout and do not materialize the fake PDF on disk.
        if pdf_file.is_file():
            for attempt in range(1, 4):
                try:
                    extracted, blocked = _run_pdftotext_bounded(pdftotext_bin, pdf_file)
                    if extracted and extracted.strip():
                        return extracted
                    if blocked:
                        logger.warning(
                            "pdftotext output exceeded the limit for job %s on attempt %s",
                            job_id,
                            attempt,
                        )
                        return None
                    logger.warning(
                        "pdftotext returned empty output for job %s on attempt %s",
                        job_id,
                        attempt,
                    )
                except Exception as exc:
                    logger.warning(
                        "pdftotext failed for job %s on attempt %s: %s",
                        job_id,
                        attempt,
                        exc,
                    )
                if attempt < 3:
                    time.sleep(0.5)
        else:
            # Compatibility path for existing unit-test doubles.
            for attempt in range(1, 4):
                text_file = pdf_file.with_suffix(".pdftotext")
                try:
                    pt_result = subprocess.run(
                        [pdftotext_bin, "-layout", str(pdf_file), str(text_file)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                    )
                    extracted = ""
                    if pt_result.returncode == 0 and text_file.is_file():
                        extracted = read_file_bounded(text_file, _MAX_EXTRACTED_TEXT_BYTES).decode(
                            "utf-8", errors="replace"
                        )
                    mocked_stdout = getattr(pt_result, "stdout", None)
                    if pt_result.returncode == 0 and not extracted and isinstance(mocked_stdout, str):
                        extracted = mocked_stdout[:_MAX_EXTRACTED_TEXT_BYTES]
                    if extracted.strip():
                        return extracted
                    logger.warning(
                        "pdftotext returned empty output for job %s on attempt %s",
                        job_id,
                        attempt,
                    )
                except Exception as exc:
                    logger.warning(
                        "pdftotext failed for job %s on attempt %s: %s",
                        job_id,
                        attempt,
                        exc,
                    )
                finally:
                    try:
                        text_file.unlink(missing_ok=True)
                    except OSError:
                        pass
                if attempt < 3:
                    time.sleep(0.5)
    else:
        logger.warning("pdftotext binary not found for job %s; falling back to pdfminer", job_id)

    try:
        return _extract_pdfminer_text_bounded(pdf_file)
    except BoundedReadError as exc:
        logger.warning("PDF text extraction exceeded the byte limit for job %s", job_id, extra={"error_type": type(exc).__name__})
        return None
    except Exception as exc:
        logger.warning("pdfminer extraction failed for job %s", job_id, extra={"error_type": type(exc).__name__})
        return None


# ------------------------------------------------------------------ #
#  Shared artifact / bookkeeping helpers (also used by orchestrator) #
# ------------------------------------------------------------------ #


def cache_compile_log(job_id: str, log_text: str) -> None:
    """Store a bounded compile-log tail in Redis for cross-container serving."""
    try:
        transcript = BoundedTranscript()
        for line in log_text.splitlines():
            transcript.append(line)
        redis = get_worker_redis()
        if not write_owned_artifacts(
            redis,
            job_id,
            {f"latexy:job:{job_id}:log": transcript.text()},
            _DEFAULT_TTL,
        ):
            logger.info("Skipped artifact write for fenced job %s", job_id)
    except Exception as exc:
        logger.warning("Failed to cache logs in Redis for job %s", job_id, extra={"error_type": type(exc).__name__})


def cache_compile_output(job_id: str, job_dir: Path) -> Optional[bytes]:
    """
    Cache the compiled PDF and SyncTeX data from job_dir in Redis.

    Must run before job_dir is rmtree'd: GET /download/{job_id} and
    GET /download/{job_id}/synctex read these keys, which is the only way the
    artifacts survive cleanup (and the only way they are reachable from a
    different container — Modal serverless has no shared filesystem).

    Returns the PDF bytes so callers can reuse them without re-reading the file.
    """
    pdf_bytes: Optional[bytes] = None
    redis = None
    pdf_key = f"latexy:job:{job_id}:pdf"
    try:
        pdf_bytes = read_file_bounded(job_dir / "resume.pdf", MAX_COMPILED_PDF_BYTES)
        redis = get_worker_redis()
        if not write_owned_artifacts(
            redis,
            job_id,
            {pdf_key: base64.b64encode(pdf_bytes).decode()},
            _DEFAULT_TTL,
        ):
            return None
    except BoundedReadError:
        # Do not delete an existing key here: a duplicate/stale worker can
        # fail its own read after a newer owner has published the artifact.
        raise
    except Exception as exc:
        logger.warning("Failed to cache PDF in Redis for job %s", job_id, extra={"error_type": type(exc).__name__})

    try:
        synctex_gz = job_dir / "resume.synctex.gz"
        synctex_plain = job_dir / "resume.synctex"
        synctex_text: Optional[str] = None
        if synctex_gz.exists():
            synctex_text = read_gzip_file_bounded(
                synctex_gz,
                max_compressed_bytes=MAX_SYNCTEX_COMPRESSED_BYTES,
                max_decompressed_bytes=MAX_SYNCTEX_DECOMPRESSED_BYTES,
            ).decode("utf-8", errors="replace")
        elif synctex_plain.exists():
            synctex_text = read_file_bounded(
                synctex_plain, MAX_SYNCTEX_DECOMPRESSED_BYTES
            ).decode("utf-8", errors="replace")
        if synctex_text:
            if not write_owned_artifacts(
                redis,
                job_id,
                {f"latexy:job:{job_id}:synctex": synctex_text},
                _DEFAULT_TTL,
            ):
                logger.info("Skipped SyncTeX write for fenced job %s", job_id)
    except Exception as exc:
        logger.warning("Failed to cache SyncTeX in Redis for job %s", job_id, extra={"error_type": type(exc).__name__})

    return pdf_bytes


def compile_cache_key(
    latex_content: str,
    compiler: str,
    compile_settings: Dict[str, Any],
    owner_scope: Optional[str],
) -> Optional[str]:
    """Build an exact, tenant-scoped cache key for a fully prepared compile.

    The caller passes source after package/draft/watermark injection. The
    complete settings payload (including BibTeX), compiler image, and an
    operator-controlled epoch keep semantically different builds separate.
    Anonymous internal jobs without a stable device/user scope are not cached.
    """
    if not owner_scope:
        return None
    material = json.dumps(
        {
            "epoch": _COMPILE_CACHE_EPOCH,
            "image": settings.LATEX_DOCKER_IMAGE,
            "owner": owner_scope,
            "compiler": compiler,
            "settings": compile_settings,
            "latex": latex_content,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"latexy:compile-cache:{hashlib.sha256(material).hexdigest()}"


def restore_compile_cache(cache_key: Optional[str], job_id: str) -> Optional[Dict[str, Any]]:
    """Copy a cached success into fresh job-owned Redis keys.

    Cache entries only point at a prior job. The current request keeps its own
    job id/meta/authorization and receives copied artifacts, so downloads never
    leak or depend on another user's job identity.
    """
    if not cache_key:
        return None
    try:
        redis = get_worker_redis()
        source_job_id = redis.get(cache_key)
        if isinstance(source_job_id, bytes):
            source_job_id = source_job_id.decode("utf-8")
        if not isinstance(source_job_id, str) or not source_job_id or source_job_id == job_id:
            return None
        pdf, synctex, log_text, raw_result = redis.mget(
            f"latexy:job:{source_job_id}:pdf",
            f"latexy:job:{source_job_id}:synctex",
            f"latexy:job:{source_job_id}:log",
            f"latexy:job:{source_job_id}:result",
        )
        if not pdf or not raw_result:
            redis.delete(cache_key)
            return None
        try:
            decode_base64_bounded(pdf, MAX_COMPILED_PDF_BYTES)
        except BoundedReadError:
            redis.delete(cache_key)
            redis.delete(f"latexy:job:{source_job_id}:pdf")
            return None
        if isinstance(raw_result, bytes):
            raw_result = raw_result.decode("utf-8")
        result = json.loads(raw_result)
        if not isinstance(result, dict) or result.get("success") is not True:
            redis.delete(cache_key)
            return None
        result.update(
            {
                "job_id": job_id,
                "pdf_job_id": job_id,
                "compilation_time": 0.0,
                "cached": True,
            }
        )
        artifacts = {f"latexy:job:{job_id}:pdf": pdf}
        if synctex:
            artifacts[f"latexy:job:{job_id}:synctex"] = synctex
        if log_text:
            artifacts[f"latexy:job:{job_id}:log"] = log_text
        if not write_owned_artifacts(redis, job_id, artifacts, _DEFAULT_TTL):
            return None
        return result
    except Exception as exc:
        logger.warning("Failed to restore compile cache for job %s", job_id, extra={"error_type": type(exc).__name__})
        return None


def remember_compile_cache(cache_key: Optional[str], job_id: str) -> None:
    """Point an exact-input cache key at a completed job's durable artifacts."""
    if not cache_key:
        return
    try:
        get_worker_redis().set(cache_key, job_id, ex=_COMPILE_CACHE_TTL)
    except Exception as exc:
        logger.warning("Failed to remember compile cache for job %s", job_id, extra={"error_type": type(exc).__name__})


class CompilationPersistenceOutcome(str, Enum):
    """Outcome of reconciling a compile row and its durable PDF artifact."""

    SUCCESS = "success"
    NO_ROW = "no_row"
    STORAGE_FAILURE = "storage_failure"


@dataclass(frozen=True)
class LatexFinalizationResult:
    """Outcome plus the immutable payload selected by the arbiter."""

    accepted: bool
    canonical_result: Optional[Dict[str, Any]] = None
    replayed: bool = False
    terminal_status: Optional[str] = None

    def __bool__(self) -> bool:
        return self.accepted


def reconcile_compilation_record(
    job_id: str,
    success: bool,
    compilation_time: Optional[float] = None,
    pdf_bytes: Optional[bytes] = None,
    error_message: Optional[str] = None,
    status: Optional[str] = None,
    lifecycle_owner: Optional[str] = None,
    lifecycle_epoch: Optional[int] = None,
    terminal_result: Optional[Dict[str, Any]] = None,
) -> CompilationPersistenceOutcome:
    """
    Move the Compilation row for this job out of "processing" into its terminal state.

    The API creates the row with status="processing" at submission time and has no
    other way to learn the outcome, so the worker owns this transition. Everything
    gated on Compilation.status == "completed" (share links, one-click apply,
    compile history, dashboard success rate) depends on it.

    On success the PDF is also uploaded to MinIO and recorded in pdf_path so the
    persistent-storage path works instead of only the temp-dir fallback — but only
    after we know a row exists to point at it (see _update_compilation_record).

    Args:
        status: Overrides the derived "completed"/"failed" terminal status
            (used for "cancelled", which is not a compile failure).
    """
    return asyncio.run(
        _update_compilation_record(
            job_id=job_id,
            status=status or ("completed" if success else "failed"),
            compilation_time=compilation_time,
            pdf_bytes=pdf_bytes if success else None,
            error_message=(error_message or "")[:500] or None,
            lifecycle_owner=lifecycle_owner,
            lifecycle_epoch=lifecycle_epoch,
            terminal_result=terminal_result,
        )
    )


def commit_latex_finalization(
    job_id: str,
    lifecycle_owner: str,
    owner_epoch: int,
    result_payload: Dict[str, Any],
    pdf_bytes: bytes,
    compilation_time: Optional[float],
    *,
    resume_id: Optional[str] = None,
    resume_user_id: Optional[str] = None,
    resume_content: Optional[str] = None,
    expected_resume_sha256: Optional[str] = None,
) -> LatexFinalizationResult:
    """Upload and atomically commit a lifecycle-owned successful compile.

    A Compilation row gets an immutable owner-tokenized object before the DB
    transaction. Jobs without a Compilation row retain their Redis-only PDF
    retention policy and commit no durable PDF path.
    """

    async def _commit() -> LatexFinalizationResult:
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        from ..core.config import settings
        from ..database.models import Compilation, JobFinalization
        from ..services.storage_service import upload_compilation_pdf
        from ..utils.db_url import database_identity, normalize_database_url
        from .finalization_arbiter import FinalizationOutcome, commit_failure, commit_success

        engine = create_async_engine(normalize_database_url(settings.DATABASE_URL), poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            # First acquire and release the authority lock. This preflight
            # prevents cancellation/replacement from causing an upload, while
            # keeping object storage outside any DB row lock.
            async with factory() as session:
                existing = await session.scalar(
                    select(JobFinalization)
                    .where(JobFinalization.job_id == job_id)
                    .with_for_update()
                )
                if existing is not None and existing.state == "completed":
                    canonical = existing.result_payload if isinstance(existing.result_payload, dict) else None
                    await session.rollback()
                    return LatexFinalizationResult(True, canonical, replayed=True, terminal_status="completed")
                if existing is not None and existing.state in {"cancelled", "failed", "fenced"}:
                    canonical = existing.result_payload if isinstance(existing.result_payload, dict) else None
                    await session.rollback()
                    return LatexFinalizationResult(
                        False,
                        canonical,
                        terminal_status="cancelled" if existing.state == "cancelled" else "failed",
                    )
                if existing is None:
                    await session.rollback()
                    return LatexFinalizationResult(False, terminal_status="failed")
                authorized = await session.scalar(
                    select(JobFinalization.id).where(
                        JobFinalization.job_id == job_id,
                        JobFinalization.owner_token == lifecycle_owner,
                        JobFinalization.owner_epoch == owner_epoch,
                        JobFinalization.cancel_requested.is_(False),
                        JobFinalization.lease_expires_at.is_not(None),
                        JobFinalization.lease_expires_at > func.clock_timestamp(),
                    )
                )
                if existing is not None and authorized is None:
                    outcome = await commit_success(
                        session,
                        job_id=job_id,
                        owner_token=lifecycle_owner,
                        owner_epoch=owner_epoch,
                        result_payload=result_payload,
                    )
                    if outcome is FinalizationOutcome.BUSY:
                        await session.rollback()
                        return LatexFinalizationResult(False, terminal_status="failed")
                    row = await session.scalar(
                        select(JobFinalization).where(JobFinalization.job_id == job_id)
                    )
                    canonical = row.result_payload if row is not None and isinstance(row.result_payload, dict) else None
                    if outcome in {
                        FinalizationOutcome.ACCEPTED,
                        FinalizationOutcome.ALREADY_COMPLETED,
                        FinalizationOutcome.FAILED,
                        FinalizationOutcome.FENCED,
                    }:
                        await session.commit()
                    else:
                        await session.rollback()
                    return LatexFinalizationResult(
                        False,
                        canonical,
                        terminal_status="cancelled" if outcome is FinalizationOutcome.CANCELLED else "failed",
                    )

                has_compilation = bool(
                    await session.scalar(
                        select(Compilation.id).where(Compilation.job_id == job_id)
                    )
                )
                await session.rollback()

            pdf_path = pdf_sha256 = None
            pdf_size = None
            if has_compilation:
                failure_message = "Compiled PDF could not be durably stored"

                async def _record_storage_failure(session):
                    """Linearize a storage failure and return its replay payload."""
                    failure_payload = {
                        **result_payload,
                        "success": False,
                        "error": failure_message,
                        "error_code": "pdf_storage_failure",
                    }
                    outcome = await commit_failure(
                        session,
                        job_id=job_id,
                        owner_token=lifecycle_owner,
                        owner_epoch=owner_epoch,
                        failure_code="pdf_storage_failure",
                        result_payload=failure_payload,
                    )
                    row = await session.scalar(
                        select(JobFinalization).where(JobFinalization.job_id == job_id)
                    )
                    canonical = row.result_payload if row is not None and isinstance(row.result_payload, dict) else None
                    if outcome is FinalizationOutcome.ALREADY_COMPLETED or (
                        row is not None and row.state == "completed"
                    ):
                        # Another owner may have committed successfully while
                        # this worker was uploading.  Its durable success wins;
                        # never turn that outcome into a synthetic failure or
                        # refund the accepted work.
                        await session.rollback()
                        return LatexFinalizationResult(
                            True,
                            canonical,
                            replayed=True,
                            terminal_status="completed",
                        )
                    if outcome in {FinalizationOutcome.BUSY, FinalizationOutcome.NO_ROW}:
                        # Do not expose another owner's nonterminal payload to
                        # this failed attempt.  The owner/recovery worker will
                        # publish its own terminal decision.
                        await session.rollback()
                        return LatexFinalizationResult(False, None)
                    if outcome is FinalizationOutcome.ACCEPTED:
                        compilation = await session.scalar(
                            select(Compilation)
                            .where(Compilation.job_id == job_id)
                            .with_for_update()
                        )
                        if compilation is not None and compilation.status == "processing":
                            compilation.status = "failed"
                            compilation.error_message = failure_message
                        await session.commit()
                    else:
                        await session.rollback()
                    terminal_status = "cancelled" if row is not None and row.state == "cancelled" else "failed"
                    return LatexFinalizationResult(False, canonical, terminal_status=terminal_status)

                if not pdf_bytes:
                    async with factory() as failure_session:
                        return await _record_storage_failure(failure_session)
                try:
                    # Anonymous/preview jobs have no Compilation row and must
                    # not receive a durable 40-day object.
                    pdf_path, pdf_sha256 = upload_compilation_pdf(
                        job_id, lifecycle_owner, pdf_bytes
                    )
                except SoftTimeLimitExceeded:
                    # Celery's worker deadline is a task timeout, not an
                    # object-storage failure. Let the outer timeout handler
                    # publish the canonical compile_timeout result.
                    raise
                except Exception:
                    async with factory() as failure_session:
                        return await _record_storage_failure(failure_session)
                pdf_size = len(pdf_bytes)

            # Reacquire the authority and let commit_success take the required
            # arbiter -> Compilation -> Resume locks for the one DB commit.
            async with factory() as session:
                existing = await session.scalar(
                    select(JobFinalization)
                    .where(JobFinalization.job_id == job_id)
                    .with_for_update()
                )
                if existing is not None and existing.state == "completed":
                    canonical = existing.result_payload if isinstance(existing.result_payload, dict) else None
                    await session.rollback()
                    return LatexFinalizationResult(True, canonical, replayed=True, terminal_status="completed")
                if existing is not None and existing.state in {"cancelled", "failed", "fenced"}:
                    canonical = existing.result_payload if isinstance(existing.result_payload, dict) else None
                    await session.rollback()
                    return LatexFinalizationResult(False, canonical, terminal_status="cancelled" if existing.state == "cancelled" else "failed")
                outcome = await commit_success(
                    session,
                    job_id=job_id,
                    owner_token=lifecycle_owner,
                    owner_epoch=owner_epoch,
                    result_payload=result_payload,
                    pdf_path=pdf_path,
                    pdf_sha256=pdf_sha256,
                    pdf_size=pdf_size,
                    compilation_time=compilation_time,
                    resume_id=resume_id,
                    resume_user_id=resume_user_id,
                    resume_content=resume_content,
                    expected_resume_sha256=expected_resume_sha256,
                    require_pdf=has_compilation,
                )
                row = await session.scalar(
                    select(JobFinalization).where(JobFinalization.job_id == job_id)
                )
                canonical = row.result_payload if row is not None and isinstance(row.result_payload, dict) else None
                committed_compilation = None
                if outcome in {FinalizationOutcome.ACCEPTED, FinalizationOutcome.ALREADY_COMPLETED} and pdf_path is not None:
                    committed_compilation = await session.scalar(
                        select(Compilation.id).where(
                            Compilation.job_id == job_id,
                            Compilation.status == "completed",
                            Compilation.pdf_path == pdf_path,
                        )
                    )
                if outcome in {
                    FinalizationOutcome.ACCEPTED,
                    FinalizationOutcome.ALREADY_COMPLETED,
                    FinalizationOutcome.FAILED,
                    FinalizationOutcome.FENCED,
                }:
                    await session.commit()
                else:
                    await session.rollback()
                if outcome in {FinalizationOutcome.ACCEPTED, FinalizationOutcome.ALREADY_COMPLETED} and committed_compilation:
                    try:
                        from .storage_guard import record_compilation_database

                        record_compilation_database(
                            database_identity(normalize_database_url(settings.DATABASE_URL))
                        )
                    except Exception as exc:
                        logger.warning(
                            "Could not record compilation database identity for %s",
                            job_id,
                            extra={"error_type": type(exc).__name__},
                        )
                return LatexFinalizationResult(
                    outcome in {FinalizationOutcome.ACCEPTED, FinalizationOutcome.ALREADY_COMPLETED},
                    canonical,
                    terminal_status=(
                        "completed" if outcome in {FinalizationOutcome.ACCEPTED, FinalizationOutcome.ALREADY_COMPLETED}
                        else "cancelled" if outcome is FinalizationOutcome.CANCELLED
                        else "failed"
                    ),
                )
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_commit())
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        logger.warning(
            "Durable compile finalization failed for %s",
            job_id,
            extra={"error_type": "database"},
        )
        return LatexFinalizationResult(False, terminal_status="failed")


async def _update_compilation_record(
    job_id: str,
    status: str,
    compilation_time: Optional[float],
    pdf_bytes: Optional[bytes],
    error_message: Optional[str],
    session_factory=None,
    lifecycle_owner: Optional[str] = None,
    lifecycle_epoch: Optional[int] = None,
    terminal_result: Optional[Dict[str, Any]] = None,
) -> CompilationPersistenceOutcome:
    """
    Persist terminal state and durable PDF storage as one completion contract.

    Successful rows are marked ``completed`` only after the deterministic PDF
    object is uploaded and ``pdf_path`` is recorded. Jobs without a Compilation
    row are inspected before upload, and retries are idempotent when they see an
    already-indexed path. Upload failures become visible failed rows instead of
    false successful completions.

    Args:
        session_factory: Optional async session factory for dependency injection
            (used in tests). When None, creates its own engine from DATABASE_URL.

    Returns:
        A typed outcome distinguishing anonymous/no-row jobs from durable
        success and storage failure.
    """
    from sqlalchemy import func, select, update

    from ..database.models import Compilation, JobFinalization

    engine = None
    db_identity: Optional[str] = None
    if session_factory is None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from ..utils.db_url import database_identity, resolve_database_url

        # Shared resolver: the cleanup worker's orphan pruner decides what to
        # delete from the SAME database this upload registers itself in, so the
        # two must never resolve DATABASE_URL differently.
        db_url = resolve_database_url()
        if not db_url:
            logger.warning("DATABASE_URL not set — cannot reconcile compilation record")
            return CompilationPersistenceOutcome.STORAGE_FAILURE
        db_identity = database_identity(db_url)
        engine = create_async_engine(db_url, echo=False)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            # The arbiter is the durable terminal authority.  It must be
            # locked before Compilation so a stale worker cannot turn a live
            # replacement's row failed after the replacement has taken over.
            # A missing arbiter row is the narrow compatibility path for
            # genuinely legacy (pre-arbiter) jobs only.
            finalization = await session.scalar(
                select(JobFinalization)
                .where(JobFinalization.job_id == job_id)
                .with_for_update()
            )
            durable_terminal_status: Optional[str] = None
            if finalization is not None:
                if status == "completed":
                    # Durable success must use commit_latex_finalization so
                    # PDF/output writes share the arbiter transaction.
                    await session.rollback()
                    return CompilationPersistenceOutcome.STORAGE_FAILURE
                if finalization.state == "completed":
                    await session.rollback()
                    return CompilationPersistenceOutcome.SUCCESS
                if finalization.state in {"failed", "cancelled", "fenced"}:
                    durable_terminal_status = (
                        "cancelled" if finalization.state == "cancelled" else "failed"
                    )
                else:
                    # Pending/committing rows require the immutable admission
                    # capability. Redis ownership alone is insufficient.
                    if not lifecycle_owner or lifecycle_epoch is None or not isinstance(terminal_result, dict):
                        await session.rollback()
                        return CompilationPersistenceOutcome.STORAGE_FAILURE
                    owner_active = await session.scalar(
                        select(JobFinalization.id).where(
                            JobFinalization.id == finalization.id,
                            JobFinalization.owner_token == lifecycle_owner,
                            JobFinalization.owner_epoch == lifecycle_epoch,
                            JobFinalization.cancel_requested.is_(False),
                            JobFinalization.lease_expires_at.is_not(None),
                            JobFinalization.lease_expires_at > func.clock_timestamp(),
                        )
                    )
                    if owner_active is None:
                        await session.rollback()
                        return CompilationPersistenceOutcome.STORAGE_FAILURE
                    from .finalization_arbiter import (
                        FinalizationOutcome,
                        bounded_result_payload,
                        commit_failure,
                        request_cancel,
                    )

                    if status == "cancelled":
                        outcome = await request_cancel(
                            session,
                            job_id=job_id,
                            reason_code="worker_cancelled",
                        )
                        if outcome is FinalizationOutcome.CANCELLED:
                            # Preserve the exact payload that the caller will
                            # pass through publish_job_result's equality
                            # guard, including its cancellation metadata.
                            finalization.result_payload = bounded_result_payload(
                                job_id,
                                terminal_result,
                            )
                        durable_terminal_status = "cancelled"
                    else:
                        outcome = await commit_failure(
                            session,
                            job_id=job_id,
                            owner_token=lifecycle_owner,
                            owner_epoch=lifecycle_epoch,
                            failure_code=str(terminal_result.get("error_code") or "worker_failed"),
                            result_payload=terminal_result,
                        )
                        durable_terminal_status = "failed"
                    if outcome not in {FinalizationOutcome.ACCEPTED, FinalizationOutcome.CANCELLED}:
                        await session.rollback()
                        return CompilationPersistenceOutcome.STORAGE_FAILURE

            # Read before uploading so anonymous/preview jobs without a
            # Compilation row never create an unowned object.
            lookup = await session.execute(
                select(Compilation)
                .where(Compilation.job_id == job_id)
                .with_for_update()
            )
            compilation = lookup.scalar_one_or_none()
            if compilation is None:
                logger.debug(
                    f"No Compilation row for job {job_id} — "
                    f"skipping reconcile to {status} (and any PDF upload)"
                )
                # A batch/LLM job may be durable in JobFinalization without a
                # Compilation row. Preserve the terminal arbiter decision even
                # though there is no legacy history row to reconcile.
                if finalization is not None and durable_terminal_status is not None:
                    await session.commit()
                else:
                    await session.rollback()
                return CompilationPersistenceOutcome.NO_ROW

            current_status = compilation.status
            # Duplicate delivery after a successful commit is a no-op.
            if current_status == "completed":
                await session.rollback()
                return CompilationPersistenceOutcome.SUCCESS
            if current_status in {"failed", "cancelled"}:
                if durable_terminal_status is not None:
                    await session.commit()
                    return CompilationPersistenceOutcome.SUCCESS
                await session.rollback()
                return CompilationPersistenceOutcome.STORAGE_FAILURE

            if durable_terminal_status is not None:
                # A durable terminal decision wins over the worker's requested
                # status. Lock order is arbiter -> Compilation for this path.
                terminal_update = await session.execute(
                    update(Compilation)
                    .where(
                        Compilation.job_id == job_id,
                        Compilation.status == current_status,
                    )
                    .values(
                        status=durable_terminal_status,
                        compilation_time=compilation_time,
                        error_message=error_message,
                    )
                )
                await session.commit()
                return (
                    CompilationPersistenceOutcome.SUCCESS
                    if terminal_update.rowcount
                    else CompilationPersistenceOutcome.NO_ROW
                )

            # Keep the row lock while uploading. This prevents two concurrent
            # owners that both observed ``processing`` from overwriting the
            # deterministic completed object between the read and UPDATE.
            def _lifecycle_owner_active() -> bool:
                if not lifecycle_owner:
                    # Ownerless mutation is retained only for genuinely
                    # legacy jobs. If a lifecycle exists, an unowned caller
                    # must not write through a live/replacement worker.
                    try:
                        from ..workers.job_lifecycle import lifecycle_key

                        return not bool(get_worker_redis().exists(lifecycle_key(job_id)))
                    except Exception:
                        return False
                from ..workers.job_lifecycle import lifecycle_key

                lifecycle_redis = get_worker_redis()
                lifecycle_status = lifecycle_redis.hget(lifecycle_key(job_id), "status")
                lifecycle_current_owner = lifecycle_redis.hget(lifecycle_key(job_id), "owner")
                lifecycle_current_epoch = lifecycle_redis.hget(lifecycle_key(job_id), "epoch")
                lifecycle_lease = lifecycle_redis.hget(lifecycle_key(job_id), "lease_until")
                if isinstance(lifecycle_status, bytes):
                    lifecycle_status = lifecycle_status.decode("utf-8")
                if isinstance(lifecycle_current_owner, bytes):
                    lifecycle_current_owner = lifecycle_current_owner.decode("utf-8")
                if isinstance(lifecycle_current_epoch, bytes):
                    lifecycle_current_epoch = lifecycle_current_epoch.decode("utf-8")
                try:
                    lease_active = float(lifecycle_lease or 0) > time.time()
                except (TypeError, ValueError):
                    lease_active = False
                return not (
                    lifecycle_status not in {"running", "finalizing"}
                    or lifecycle_current_owner != lifecycle_owner
                    or (
                        lifecycle_current_epoch not in (None, "")
                        and (
                            lifecycle_epoch is None
                            or lifecycle_current_epoch != str(lifecycle_epoch)
                        )
                    )
                    or not lease_active
                )

            if not _lifecycle_owner_active():
                await session.rollback()
                return CompilationPersistenceOutcome.STORAGE_FAILURE

            # The durable key is produced only by upload_compilation_pdf after
            # validating the admitted owner; never construct a mutable global
            # ``compilations/{job_id}/resume.pdf`` key here.
            pdf_path: Optional[str] = None
            if status == "completed":
                # Completed compilations must have a durable PDF. A missing
                # artifact is a visible failure, never a successful row.
                if not pdf_bytes:
                    failure_message = "Compiled PDF storage failed: artifact bytes unavailable"
                    failure_update = await session.execute(
                        update(Compilation)
                        .where(
                            Compilation.job_id == job_id,
                            Compilation.status == current_status,
                            Compilation.pdf_path.is_(None),
                        )
                        .values(
                            status="failed",
                            compilation_time=compilation_time,
                            error_message=failure_message,
                        )
                    )
                    await session.commit()
                    return (
                        CompilationPersistenceOutcome.STORAGE_FAILURE
                        if failure_update.rowcount
                        else CompilationPersistenceOutcome.NO_ROW
                    )
                if not lifecycle_owner:
                    await session.rollback()
                    return CompilationPersistenceOutcome.STORAGE_FAILURE

                # Upload before changing durable status. The deterministic key
                # makes retries idempotent for the storage backend.
                try:
                    from ..services.storage_service import upload_compilation_pdf

                    pdf_path, _pdf_sha256 = upload_compilation_pdf(job_id, lifecycle_owner, pdf_bytes)
                except SoftTimeLimitExceeded:
                    # Preserve the timeout taxonomy for the outer worker
                    # handler; do not persist pdf_storage_failure.
                    raise
                except Exception as exc:
                    failure_message = "Compiled PDF storage failed"
                    logger.warning(
                        "Failed to upload PDF to MinIO for job %s",
                        job_id,
                        extra={"error_type": type(exc).__name__},
                    )
                    failure_update = await session.execute(
                        update(Compilation)
                        .where(
                            Compilation.job_id == job_id,
                            Compilation.status == current_status,
                            Compilation.pdf_path.is_(None),
                        )
                        .values(
                            status="failed",
                            compilation_time=compilation_time,
                            error_message=failure_message,
                        )
                    )
                    await session.commit()
                    return (
                        CompilationPersistenceOutcome.STORAGE_FAILURE
                        if failure_update.rowcount
                        else CompilationPersistenceOutcome.NO_ROW
                    )

                # The lease may expire while the synchronous upload is in
                # flight. Never commit a completed row from a stale owner.
                if not _lifecycle_owner_active():
                    await session.rollback()
                    return CompilationPersistenceOutcome.STORAGE_FAILURE

                completed_update = await session.execute(
                    update(Compilation)
                    .where(
                        Compilation.job_id == job_id,
                        Compilation.status == current_status,
                        Compilation.pdf_path.is_(None),
                    )
                    .values(
                        status="completed",
                        compilation_time=compilation_time,
                        error_message=error_message,
                        pdf_path=pdf_path,
                        pdf_size=len(pdf_bytes),
                    )
                )
                await session.commit()
                if not completed_update.rowcount:
                    await session.rollback()
                    return CompilationPersistenceOutcome.STORAGE_FAILURE

                logger.info(f"Compilation record for job {job_id} reconciled to completed")
                if db_identity:
                    try:
                        from .storage_guard import record_compilation_database

                        record_compilation_database(db_identity)
                    except Exception as exc:
                        logger.warning(
                            "Could not record compilation database identity for %s",
                            job_id,
                            extra={"error_type": type(exc).__name__},
                        )
                return CompilationPersistenceOutcome.SUCCESS

            # Non-success terminal states do not require a PDF. Guard the
            # transition so a late failure cannot overwrite accepted success.
            result = await session.execute(
                update(Compilation)
                .where(
                    Compilation.job_id == job_id,
                    Compilation.status == current_status,
                )
                .values(
                    status=status,
                    compilation_time=compilation_time,
                    error_message=error_message,
                )
            )
            await session.commit()
            return (
                CompilationPersistenceOutcome.SUCCESS
                if result.rowcount
                else CompilationPersistenceOutcome.NO_ROW
            )
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        logger.warning("Failed to reconcile compilation record for job %s", job_id, extra={"error_type": type(exc).__name__})
        return CompilationPersistenceOutcome.STORAGE_FAILURE
    finally:
        if engine is not None:
            await engine.dispose()


@celery_app.task(
    bind=True,
    name="app.workers.latex_worker.compile_latex_task",
    max_retries=3,
    default_retry_delay=60,
)
def compile_latex_task(
    self,
    latex_content: str,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    metadata: Optional[Dict] = None,
    resume_id: Optional[str] = None,
    compiler: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    compile_settings: Optional[Dict] = None,
    watermark: Optional[str] = None,
    quota_refund: Optional[Dict[str, Any]] = None,
    auto_fit: bool = False,
    auto_fit_intensity: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Compile LaTeX content to PDF, streaming each pdflatex log line as
    a log.line event.  Publishes job.completed on success or job.failed
    on error.
    """
    if job_id is None:
        job_id = str(uuid.uuid4())

    # Timing instrumentation (#1281) — captured before anything else so
    # cold_start/queue_wait reflect the true start of this task's execution.
    _task_monotonic_start = time.monotonic()
    _cold_start_seconds = consume_cold_start_seconds()
    _queue_wait_seconds = compute_queue_wait_seconds(job_id)

    # Resolve and validate compiler — None means "use configured default"
    compiler = compiler or settings.DEFAULT_LATEX_COMPILER
    if compiler not in settings.ALLOWED_LATEX_COMPILERS:
        logger.warning(f"Invalid compiler '{compiler}', falling back to {settings.DEFAULT_LATEX_COMPILER}")
        compiler = settings.DEFAULT_LATEX_COMPILER

    # Resolve per-plan compile timeout
    timeout = float(timeout_seconds) if timeout_seconds else float(get_compile_timeout(user_plan))

    task_id = self.request.id
    worker_id = f"latex-{task_id}"
    logger.info(
        f"LaTeX task {task_id} starting for job {job_id} (compiler={compiler})",
        extra={
            "job_id": job_id,
            "task_id": task_id,
            "compiler": compiler,
            "queue_wait_seconds": _queue_wait_seconds,
            "cold_start_seconds": _cold_start_seconds,
        },
    )

    lifecycle_owner = f"{worker_id}:{uuid.uuid4()}"
    queue_redis = get_worker_redis()
    if not admit_worker(queue_redis, job_id, lifecycle_owner, quota_refund, user_id):
        return {
            "success": False,
            "job_id": job_id,
            "error": "Job ownership unavailable",
        }
    lifecycle_owned = bool(queue_redis.exists(lifecycle_key(job_id)))
    # Owner-scoped DB reconciliation is required for admitted jobs. Legacy
    # ownerless calls retain the historical row transition, but must not pass
    # a synthetic worker token that can never satisfy the lifecycle fence.
    reconcile_owner = lifecycle_owner if lifecycle_owned else None
    # Capture the admission capability once. Never re-read a mutable Redis
    # epoch after a lease can be taken over by a duplicate delivery.
    lifecycle_epoch = current_owner_epoch(job_id) if lifecycle_owned else None
    if lifecycle_owned and lifecycle_epoch is None:
        return {"success": False, "job_id": job_id, "error": "Job ownership unavailable"}

    def _log_task_timing(
        outcome: str,
        compile_subprocess_seconds: Optional[float] = None,
        reporting_start: Optional[float] = None,
    ) -> None:
        """One structured, grep-able line per task completion (#1281).

        Breaks the "processing" window a client sees into the phases that
        matter for latency diagnosis, instead of the single opaque
        compilation_time this task already reports in its result payload.
        """
        reporting_seconds = time.monotonic() - reporting_start if reporting_start is not None else None
        logger.info(
            "compile_task_timing",
            extra={
                "job_id": job_id,
                "task_id": task_id,
                "compiler": compiler,
                "outcome": outcome,
                "queue_wait_seconds": _queue_wait_seconds,
                "cold_start_seconds": _cold_start_seconds,
                "compile_subprocess_seconds": compile_subprocess_seconds,
                "reporting_seconds": reporting_seconds,
                "total_task_seconds": time.monotonic() - _task_monotonic_start,
            },
        )

    def _terminal_failure(result: Dict[str, Any], *, accepted: bool = True) -> Dict[str, Any]:
        if accepted:
            _refund_compile_quota_once(job_id, quota_refund)
        return result

    if self.request.retries == 0:
        publish_event(
            job_id,
            "job.started",
            {
                "worker_id": worker_id,
                "stage": "latex_compilation",
            },
        )
    else:
        publish_event(
            job_id,
            "job.retrying",
            {
                "worker_id": worker_id,
                "stage": "latex_compilation",
                "attempt": self.request.retries + 1,
            },
        )

    job_dir: Optional[Path] = None
    try:
        # ── Validation ──────────────────────────────────────────────
        publish_event(
            job_id,
            "job.progress",
            {
                "percent": 5,
                "stage": "latex_compilation",
                "message": "Validating LaTeX content",
            },
        )

        if not latex_service.validate_latex_content(latex_content):
            error_msg = (
                r"Invalid LaTeX: missing \documentclass, "
                r"\begin{document}, or \end{document}"
            )
            # This gate runs BEFORE the compiler ever starts, so there is no
            # pdflatex stdout to stream — without this, the Live Logs panel
            # stays completely empty on failure (see job.failed below), giving
            # the user no actionable detail. Publish the reason as a log line
            # too, matching what a real compiler failure looks like downstream.
            publish_event(
                job_id,
                "log.line",
                {
                    "line": f"! {error_msg}",
                    "source": compiler,
                    "is_error": True,
                },
            )
            result = {"success": False, "job_id": job_id, "error": error_msg}
            terminal_accepted = publish_job_result(job_id, result)
            if terminal_accepted:
                publish_event(
                    job_id,
                    "job.failed",
                    {
                        "stage": "latex_compilation",
                        "error_code": "latex_error",
                        "error_message": error_msg,
                        "retryable": False,
                    },
                )
            reconcile_compilation_record(job_id, success=False, error_message=error_msg, lifecycle_owner=reconcile_owner, lifecycle_epoch=lifecycle_epoch, terminal_result=result)
            return _terminal_failure(result, accepted=terminal_accepted)

        # ── Apply compile settings ───────────────────────────────────
        _cs = compile_settings or {}

        # Inject extra packages if any
        extra_packages = _cs.get("extra_packages") or []
        if extra_packages and isinstance(extra_packages, list):
            latex_content = _inject_packages(latex_content, extra_packages)
        if _cs.get("draft_mode") is True:
            latex_content = _inject_draft_graphics(latex_content)

        # Inject watermark if requested
        if watermark:
            if not _WATERMARK_RE.match(watermark) or len(watermark) > _WATERMARK_MAX_LEN:
                error_msg = "Invalid watermark text"
                result = {"success": False, "job_id": job_id, "error": error_msg}
                terminal_accepted = publish_job_result(job_id, result)
                if terminal_accepted:
                    publish_event(
                        job_id,
                        "job.failed",
                        {
                            "stage": "latex_compilation",
                            "error_code": "invalid_watermark",
                            "error_message": error_msg,
                            "retryable": False,
                        },
                    )
                reconcile_compilation_record(job_id, success=False, error_message=error_msg, lifecycle_owner=reconcile_owner, lifecycle_epoch=lifecycle_epoch, terminal_result=result)
                return _terminal_failure(result, accepted=terminal_accepted)
            latex_content = _inject_watermark(latex_content, watermark)

        # Determine main .tex filename (validated regex, default resume.tex)
        main_file = str(_cs.get("main_file") or "resume.tex")
        if not _MAIN_FILE_RE.fullmatch(main_file):
            main_file = "resume.tex"

        # Extra flags — only from the safe subset (skip flags already hardcoded)
        custom_flags = [f for f in (_cs.get("latexmk_flags") or []) if f in _ALLOWED_EXTRA_FLAGS]
        error_mode_flags = ["-interaction=nonstopmode"]
        if _cs.get("halt_on_error") is not False:
            error_mode_flags.append("-halt-on-error")

        fit_payload: Dict[str, Any] = {}
        if auto_fit:
            original_source = remove_auto_fit(latex_content)
            profiles = (
                (profile_for_intensity(auto_fit_intensity),)
                if auto_fit_intensity is not None and auto_fit_intensity > 0
                else AUTO_FIT_PROFILES
            )
            if auto_fit_intensity == 0:
                profiles = ()

            chosen_source = original_source
            chosen_intensity = 0
            fit_succeeded = False
            attempts = 0
            # Leave room under Modal's 300s hard ceiling for the final artifact
            # compile even on the 240s Pro tier.
            probe_timeout = max(5.0, min(10.0, timeout / max(1, len(profiles))))
            if not profiles:
                fit_succeeded = True
            for index, profile in enumerate(profiles, start=1):
                if is_cancelled(job_id):
                    raise RuntimeError("Job cancelled during auto-fit")
                publish_event(
                    job_id,
                    "job.progress",
                    {
                        "percent": 8 + int(32 * index / len(profiles)),
                        "stage": "auto_fit",
                        "message": f"Testing formatting profile {index} of {len(profiles)}",
                    },
                )
                candidate = apply_auto_fit(original_source, profile)
                success, candidate_pages, probe_error = _probe_auto_fit_candidate(
                    job_id=job_id,
                    latex_content=candidate,
                    profile_intensity=profile.intensity,
                    compiler=compiler,
                    main_file=main_file,
                    custom_flags=custom_flags,
                    error_mode_flags=error_mode_flags,
                    bibtex=_cs.get("bibtex"),
                    timeout=probe_timeout,
                )
                attempts += 1
                if probe_error == ENGINE_READ_ESCAPE_ERROR:
                    chosen_source = candidate
                    chosen_intensity = profile.intensity
                    break
                if not success:
                    continue
                chosen_source = candidate
                chosen_intensity = profile.intensity
                if candidate_pages == 1:
                    fit_succeeded = True
                    break

            latex_content = chosen_source
            fit_payload = {
                "auto_fit": True,
                "fit_succeeded": fit_succeeded,
                "fit_intensity": chosen_intensity,
                "fit_attempts": attempts,
                "fitted_latex": chosen_source,
            }

        # Exact-output caching is deliberately checked only after validation
        # and every source transformation. This cannot bypass watermark,
        # package, or sandbox-input validation, and a fresh job id still owns
        # all restored artifacts and authorization metadata.
        cache_owner = f"user:{user_id}" if user_id else (f"device:{device_fingerprint}" if device_fingerprint else None)
        content_cache_key = compile_cache_key(
            latex_content,
            compiler,
            {
                **_cs,
                "main_file": main_file,
                "latexmk_flags": custom_flags,
                "halt_on_error": _cs.get("halt_on_error") is not False,
            },
            cache_owner,
        )
        _cache_reporting_start = time.monotonic()
        cached_result = restore_compile_cache(content_cache_key, job_id)
        if cached_result is not None:
            for contextual_key in (
                "auto_fit",
                "fit_succeeded",
                "fit_intensity",
                "fit_attempts",
                "fitted_latex",
            ):
                cached_result.pop(contextual_key, None)
            cached_result.update(fit_payload)
            # restore_compile_cache copies the original result verbatim. Replace
            # request-specific metadata so a later ordinary compile never
            # inherits an earlier auto-fit response (or vice versa).
            cached_result["job_id"] = job_id
            cached_result["pdf_job_id"] = job_id
            cached_result["cached"] = True
            replayed = False
            cached_pdf_value = get_worker_redis().get(f"latexy:job:{job_id}:pdf")
            if isinstance(cached_pdf_value, str):
                cached_pdf_value = cached_pdf_value.encode("ascii")
            cached_pdf_bytes = (
                decode_base64_bounded(cached_pdf_value, MAX_COMPILED_PDF_BYTES)
                if cached_pdf_value
                else None
            )
            replayed = False
            if lifecycle_owned:
                if not begin_finalizing(queue_redis, job_id, lifecycle_owner, lifecycle_epoch):
                    return {"success": False, "job_id": job_id, "error": "Job ownership expired"}
                finalization = commit_latex_finalization(
                    job_id,
                    lifecycle_owner,
                    lifecycle_epoch,
                    cached_result,
                    cached_pdf_bytes or b"",
                    0.0,
                )
                if not finalization:
                    failure = finalization.canonical_result or {
                        "success": False,
                        "job_id": job_id,
                        "error": "Job finalization unavailable",
                    }
                    terminal_accepted = publish_job_result(job_id, failure)
                    if terminal_accepted:
                        publish_event(
                            job_id,
                            "job.cancelled" if finalization.terminal_status == "cancelled" else "job.failed",
                            {"stage": "finalization", "error_code": failure.get("error", "finalization_failed")},
                        )
                    return _terminal_failure(failure, accepted=terminal_accepted)
                replayed = finalization.replayed
                cached_result = finalization.canonical_result or cached_result
            else:
                persistence = reconcile_compilation_record(
                    job_id,
                    success=True,
                    compilation_time=0.0,
                    pdf_bytes=cached_pdf_bytes,
                    lifecycle_owner=lifecycle_owner,
                )
                if persistence == CompilationPersistenceOutcome.STORAGE_FAILURE:
                    return {"success": False, "job_id": job_id, "error": "Compiled PDF could not be durably stored"}
            publish_job_result(job_id, cached_result)
            publish_event(
                job_id,
                "job.progress",
                {
                    "percent": 90,
                    "stage": "latex_compilation",
                    "message": "Reusing identical compiled PDF",
                },
            )
            extracted_text = cached_result.get("extracted_text")
            if isinstance(extracted_text, str) and extracted_text:
                publish_event(
                    job_id,
                    "job.pdf_extracted",
                    {
                        "text": extracted_text,
                        "page_count": cached_result.get("page_count") or 1,
                    },
                )
            completion_event = publish_event(
                job_id,
                "job.completed",
                {
                    "percent": 100,
                    "pdf_job_id": job_id,
                    "ats_score": None,
                    "ats_details": None,
                    "changes_made": [],
                    "compilation_time": 0.0,
                    "optimization_time": 0.0,
                    "tokens_used": 0,
                    "page_count": cached_result.get("page_count"),
                    "slide_count": cached_result.get("slide_count"),
                    "is_beamer": bool(cached_result.get("is_beamer")),
                    "compiler": cached_result.get("compiler", compiler),
                    "cached": cached_result.get("cached", True),
                    **({} if replayed else {key: value for key, value in fit_payload.items() if key != "fitted_latex"}),
                },
            )
            logger.info("LaTeX cache hit for job %s", job_id)
            _log_task_timing("cache_hit", 0.0, _cache_reporting_start)
            if quota_refund and completion_event:
                clear_quota_refund_receipt(job_id)
            _resume_id = resume_id or (metadata or {}).get("resume_id")
            skip_auto_save = bool((metadata or {}).get("skip_auto_save"))
            if not replayed and _resume_id and user_id and not watermark and not skip_auto_save:
                from .auto_save_worker import submit_auto_save_checkpoint

                submit_auto_save_checkpoint(_resume_id, user_id, latex_content)
            return cached_result

        # ── Setup ────────────────────────────────────────────────────
        job_dir = Path(settings.TEMP_DIR) / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        # job_dir is now set; finally block will clean it up
        tex_file = job_dir / main_file
        tex_file.write_text(latex_content, encoding="utf-8")
        materialize_embedded_signature(latex_content, job_dir)
        write_reference_library(job_dir, _cs.get("bibtex"))

        publish_event(
            job_id,
            "job.progress",
            {
                "percent": 50 if auto_fit else 10,
                "stage": "latex_compilation",
                "message": f"Starting {compiler} compilation",
            },
        )

        # ── Compile ──────────────────────────────────────────────────
        _use_docker = docker_engine_available()
        container_name = docker_container_name(job_id, "worker") if _use_docker else None
        if _use_docker:
            cmd = [
                "docker",
                "run",
                "--rm",
                "--name",
                container_name,
                *docker_sandbox_args(),
                "-v",
                f"{job_dir}:/workspace",
                "-w",
                "/workspace",
                settings.LATEX_DOCKER_IMAGE,
                compiler,
                *LATEX_SANDBOX_FLAGS,
                *error_mode_flags,
                "-synctex=1",
                "-output-directory",
                "/workspace",
                "-jobname",
                "resume",
                *custom_flags,
                main_file,
            ]
            compile_cwd = None
            workspace = "/workspace"
        else:
            assert_local_engine_allowed(job_id)
            # Run WITH cwd=job_dir and pass RELATIVE paths. The sandbox sets
            # openin_any/openout_any=p (paranoid), under which kpathsea refuses to
            # read/write ABSOLUTE paths (e.g. /tmp/.../resume.tex) — pdflatex would
            # fail with "Not reading from … (openin_any = p)". Relative names
            # resolve against cwd, which paranoid mode permits.
            cmd = [
                compiler,
                *LATEX_SANDBOX_FLAGS,
                *error_mode_flags,
                "-synctex=1",
                "-jobname",
                "resume",
                "-output-directory",
                ".",
                *custom_flags,
                main_file,
            ]
            compile_cwd = str(job_dir)
            workspace = str(job_dir)

        _perf_start = time.perf_counter()
        with traced("latex.compile", compiler=compiler, docker=_use_docker):
            start_time = time.time()
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=compile_cwd,
                env=engine_env(),
            )

            # ── Detect Beamer presentation ───────────────────────────────
            is_beamer = is_beamer_document(latex_content)

            # ── Stream log lines ─────────────────────────────────────────
            page_count: Optional[int] = None
            first_latex_error: Optional[str] = None  # first "! ..." line from pdflatex
            transcript = BoundedTranscript()

            watchdog = ProcessWatchdog(
                proc,
                timeout=timeout,
                is_cancelled=lambda: is_cancelled(job_id),
            ).start()

            def _fail_read_escape(escaped: str) -> Dict[str, Any]:
                """Terminate the job without publishing the log, PDF or extracted text."""
                logger.warning(f"[{job_id}] engine read outside the job directory: {escaped}")
                escape_result = {
                    "success": False,
                    "job_id": job_id,
                    "error": ENGINE_READ_ESCAPE_ERROR,
                }
                terminal_accepted = publish_job_result(job_id, escape_result)
                if terminal_accepted:
                    publish_event(
                        job_id,
                        "job.failed",
                        {
                            "stage": "latex_compilation",
                            "error_code": "engine_read_escape",
                            "error_message": ENGINE_READ_ESCAPE_ERROR,
                            "retryable": False,
                        },
                    )
                cache_compile_log(job_id, ENGINE_READ_ESCAPE_ERROR)
                reconcile_compilation_record(
                    job_id,
                    success=False,
                    compilation_time=time.time() - start_time,
                    error_message="engine_read_escape",
                    lifecycle_owner=reconcile_owner,
                    lifecycle_epoch=lifecycle_epoch,
                    terminal_result=escape_result,
                )
                _log_task_timing("engine_read_escape", time.time() - start_time)
                return _terminal_failure(escape_result, accepted=terminal_accepted)

            try:
                for stripped in iter_bounded_lines(proc.stdout):
                    if not stripped:
                        continue

                    # Read confinement: \input-style reads are announced in the transcript.
                    # Kill before this line is streamed or stored — the following lines
                    # would carry the file's contents, and the PDF would render them.
                    # \openin reads announce nothing here; the recorder check after the run
                    # is what catches those.
                    escaped = find_engine_read_escape(stripped, workspace)
                    if escaped:
                        proc.kill()
                        cleanup_docker_container(container_name)
                        proc.wait()
                        return _fail_read_escape(escaped)

                    bounded_line = transcript.append(stripped)

                    # Extract page count from pdflatex summary line
                    m = PAGE_COUNT_RE.search(stripped)
                    if m:
                        page_count = int(m.group(1))

                    # Capture the first "! <error type>" line for persistent storage
                    if first_latex_error is None and stripped.startswith("!"):
                        first_latex_error = stripped[:250]

                    is_error_line = (
                        "error" in stripped.lower() or stripped.startswith("!") or "fatal" in stripped.lower()
                    )
                    publish_event(
                        job_id,
                        "log.line",
                        {
                            "line": bounded_line,
                            "source": compiler,
                            "is_error": is_error_line,
                        },
                    )

                    # ── Cancellation check ───────────────────────────────────
                    if is_cancelled(job_id):
                        proc.kill()
                        cleanup_docker_container(container_name)
                        proc.wait()
                        result = {"success": False, "job_id": job_id, "cancelled": True}
                        terminal_accepted = publish_job_result(job_id, result)
                        if terminal_accepted:
                            publish_event(job_id, "job.cancelled", {})
                        # Cache the partial log so GET /logs/{job_id} still works, and
                        # move the row out of "processing" — DELETE /jobs/{job_id} is a
                        # shipped endpoint, so this is a reachable terminal path.
                        # "cancelled" (not "failed") keeps it out of the error-history
                        # and failed-compile analytics buckets, both of which already
                        # understand the value.
                        cache_compile_log(job_id, transcript.text())
                        reconcile_compilation_record(
                            job_id,
                            success=False,
                            status="cancelled",
                            compilation_time=time.time() - start_time,
                            error_message="cancelled",
                            lifecycle_owner=reconcile_owner,
                            lifecycle_epoch=lifecycle_epoch,
                            terminal_result=result,
                        )
                        _log_task_timing("cancelled", time.time() - start_time)
                        return _terminal_failure(result, accepted=terminal_accepted)

                    # ── Timeout check ────────────────────────────────────────
                    if time.time() - start_time > timeout:
                        proc.kill()
                        cleanup_docker_container(container_name)
                        proc.wait()
                        record_compile("error", duration_seconds=time.perf_counter() - _perf_start)
                        upgrade_msg = (
                            "Upgrade to Pro for a 4-minute compile timeout"
                            if resolve_plan_family(user_plan) in {"free", "basic"}
                            else None
                        )
                        result = {"success": False, "job_id": job_id, "error": "compile_timeout"}
                        terminal_accepted = publish_job_result(job_id, result)
                        if terminal_accepted:
                            publish_event(
                                job_id,
                                "job.failed",
                                {
                                    "stage": "latex_compilation",
                                    "error_code": "compile_timeout",
                                    "error_message": f"Compilation timed out after {int(timeout)}s ({user_plan} plan limit)",
                                    "upgrade_message": upgrade_msg,
                                    "user_plan": user_plan,
                                    "timeout_seconds": int(timeout),
                                    "retryable": False,
                                },
                            )
                        reconcile_compilation_record(
                            job_id,
                            success=False,
                            compilation_time=time.time() - start_time,
                            error_message="compile_timeout",
                            lifecycle_owner=reconcile_owner,
                            lifecycle_epoch=lifecycle_epoch,
                            terminal_result=result,
                        )
                        _log_task_timing("compile_timeout", time.time() - start_time)
                        return _terminal_failure(result, accepted=terminal_accepted)
            finally:
                watchdog_reason = watchdog.stop()

            if watchdog_reason == "cancelled":
                cleanup_docker_container(container_name)
                proc.wait()
                result = {"success": False, "job_id": job_id, "cancelled": True}
                terminal_accepted = publish_job_result(job_id, result)
                if terminal_accepted:
                    publish_event(job_id, "job.cancelled", {})
                cache_compile_log(job_id, transcript.text())
                reconcile_compilation_record(
                    job_id,
                    success=False,
                    status="cancelled",
                    compilation_time=time.time() - start_time,
                    error_message="cancelled",
                    lifecycle_owner=reconcile_owner,
                    lifecycle_epoch=lifecycle_epoch,
                    terminal_result=result,
                )
                _log_task_timing("cancelled", time.time() - start_time)
                return _terminal_failure(result, accepted=terminal_accepted)

            if watchdog_reason == "timeout":
                cleanup_docker_container(container_name)
                proc.wait()
                record_compile("error", duration_seconds=time.perf_counter() - _perf_start)
                upgrade_msg = (
                    "Upgrade to Pro for a 4-minute compile timeout"
                    if resolve_plan_family(user_plan) in {"free", "basic"}
                    else None
                )
                result = {"success": False, "job_id": job_id, "error": "compile_timeout"}
                terminal_accepted = publish_job_result(job_id, result)
                if terminal_accepted:
                    publish_event(
                        job_id,
                        "job.failed",
                        {
                            "stage": "latex_compilation",
                            "error_code": "compile_timeout",
                            "error_message": f"Compilation timed out after {int(timeout)}s ({user_plan} plan limit)",
                            "upgrade_message": upgrade_msg,
                            "user_plan": user_plan,
                            "timeout_seconds": int(timeout),
                            "retryable": False,
                        },
                    )
                reconcile_compilation_record(
                    job_id,
                    success=False,
                    compilation_time=time.time() - start_time,
                    error_message="compile_timeout",
                    lifecycle_owner=reconcile_owner,
                    lifecycle_epoch=lifecycle_epoch,
                    terminal_result=result,
                )
                _log_task_timing("compile_timeout", time.time() - start_time)
                return _terminal_failure(result, accepted=terminal_accepted)

            proc.wait()
            compilation_time = time.time() - start_time
        _compile_duration = time.perf_counter() - _perf_start
        # Everything from here on is post-subprocess bookkeeping (recorder check,
        # Redis caching, DB reconcile, event publish) — the "reporting" phase.
        _reporting_start = time.monotonic()

        # Post-run read confinement. \openin/\read leaves no trace in the transcript,
        # so the -recorder .fls file is the only complete list of what was opened.
        # Runs before the log is cached and before the PDF/extracted text is published.
        recorder_escape = find_recorder_read_escape(
            job_dir / f"resume{RECORDER_SUFFIX}",
            workspace,
            require_recorder=proc.returncode == 0,
        )
        if recorder_escape:
            return _fail_read_escape(recorder_escape)

        cache_compile_log(job_id, transcript.text())

        publish_event(
            job_id,
            "job.progress",
            {
                "percent": 90,
                "stage": "latex_compilation",
                "message": "Finalizing PDF",
            },
        )

        # ── Success / failure ────────────────────────────────────────
        pdf_file = job_dir / "resume.pdf"

        if proc.returncode == 0 and pdf_file.exists():
            pdf_size = pdf_file.stat().st_size
            if pdf_size > MAX_COMPILED_PDF_BYTES:
                error_msg = f"Compiled PDF exceeds the {MAX_COMPILED_PDF_BYTES} byte limit"
                record_compile("error", duration_seconds=_compile_duration, pdf_bytes=pdf_size)
                result = {"success": False, "job_id": job_id, "error": error_msg}
                terminal_accepted = publish_job_result(job_id, result)
                if terminal_accepted:
                    publish_event(
                        job_id,
                        "job.failed",
                        {
                            "stage": "latex_compilation",
                            "error_code": "pdf_too_large",
                            "error_message": error_msg,
                            "retryable": False,
                        },
                    )
                reconcile_compilation_record(
                    job_id,
                    success=False,
                    compilation_time=compilation_time,
                    error_message="pdf_too_large",
                    lifecycle_owner=reconcile_owner,
                    lifecycle_epoch=lifecycle_epoch,
                    terminal_result=result,
                )
                _log_task_timing("pdf_too_large", _compile_duration, _reporting_start)
                return _terminal_failure(result, accepted=terminal_accepted)
            record_compile(
                "success",
                duration_seconds=_compile_duration,
                pdf_bytes=pdf_size,
                pages=page_count,
            )

            # ── PDF text extraction for ATS pre-flight ───────────────
            extracted_text = _extract_pdf_text(pdf_file, job_id)

            try:
                pdf_bytes = cache_compile_output(job_id, job_dir)
            except BoundedReadError:
                # The stat gate above normally catches this; retain the same
                # terminal behavior if the file grows between stat and read.
                error_msg = f"Compiled PDF exceeds the {MAX_COMPILED_PDF_BYTES} byte limit"
                record_compile("error", duration_seconds=_compile_duration)
                result = {"success": False, "job_id": job_id, "error": error_msg}
                terminal_accepted = publish_job_result(job_id, result)
                if terminal_accepted:
                    publish_event(
                        job_id,
                        "job.failed",
                        {
                            "stage": "latex_compilation",
                            "error_code": "pdf_too_large",
                            "error_message": error_msg,
                            "retryable": False,
                        },
                    )
                reconcile_compilation_record(
                    job_id,
                    success=False,
                    compilation_time=compilation_time,
                    error_message="pdf_too_large",
                    lifecycle_owner=reconcile_owner,
                    lifecycle_epoch=lifecycle_epoch,
                    terminal_result=result,
                )
                _log_task_timing("pdf_too_large", _compile_duration, _reporting_start)
                return _terminal_failure(result, accepted=terminal_accepted)

            # For Beamer, slide_count == page_count (one PDF page per slide)
            slide_count = page_count if is_beamer else None

            result = {
                "success": True,
                "job_id": job_id,
                "pdf_job_id": job_id,
                "compilation_time": compilation_time,
                "pdf_size": pdf_size,
                "page_count": page_count,
                "slide_count": slide_count,
                "is_beamer": is_beamer,
                "extracted_text": extracted_text,
                **fit_payload,
            }
            replayed = False
            if lifecycle_owned:
                if not begin_finalizing(queue_redis, job_id, lifecycle_owner, lifecycle_epoch):
                    return {"success": False, "job_id": job_id, "error": "Job ownership expired"}
                finalization = commit_latex_finalization(
                    job_id,
                    lifecycle_owner,
                    lifecycle_epoch,
                    result,
                    pdf_bytes,
                    compilation_time,
                )
                if not finalization:
                    failure = finalization.canonical_result or {
                        "success": False,
                        "job_id": job_id,
                        "error": "Job finalization unavailable",
                    }
                    terminal_status = finalization.terminal_status or "failed"
                    terminal_accepted = publish_job_result(job_id, failure)
                    if terminal_accepted:
                        publish_event(
                            job_id,
                            "job.cancelled" if terminal_status == "cancelled" else "job.failed",
                            {"stage": "finalization", "error_code": failure.get("error", "finalization_failed")},
                        )
                    return _terminal_failure(failure, accepted=terminal_accepted)
                replayed = finalization.replayed
                result = finalization.canonical_result or result
            else:
                persistence_outcome = reconcile_compilation_record(
                    job_id,
                    success=True,
                    compilation_time=compilation_time,
                    pdf_bytes=pdf_bytes,
                    lifecycle_owner=reconcile_owner,
                    lifecycle_epoch=lifecycle_epoch,
                )
                if persistence_outcome == CompilationPersistenceOutcome.STORAGE_FAILURE:
                    return {"success": False, "job_id": job_id, "error": "Compiled PDF could not be durably stored"}
            if not publish_job_result(job_id, result):
                return {"success": False, "job_id": job_id, "error": "Job ownership expired"}
            remember_compile_cache(content_cache_key, job_id)

            # Publish extracted text as a dedicated event before job.completed.
            event_extracted_text = result.get("extracted_text")
            if event_extracted_text is not None:
                publish_event(
                    job_id,
                    "job.pdf_extracted",
                    {
                        "text": event_extracted_text,
                        "page_count": result.get("page_count", page_count) or 1,
                    },
                )

            completion_event = publish_event(
                job_id,
                "job.completed",
                {
                    "percent": 100,
                    "pdf_job_id": job_id,
                    # A plain compile never runs ATS scoring — send None (not a
                    # fake 0.0) so the client shows a neutral "no score yet"
                    # state instead of a misleading 0/100 "Poor" verdict.
                    "ats_score": None,
                    "ats_details": None,
                    "changes_made": [],
                    "compilation_time": result.get("compilation_time", compilation_time),
                    "optimization_time": 0.0,
                    "tokens_used": 0,
                    "page_count": result.get("page_count", page_count),
                    "slide_count": result.get("slide_count", slide_count),
                    "is_beamer": result.get("is_beamer", is_beamer),
                    "compiler": result.get("compiler", compiler),
                    **({} if replayed else {key: value for key, value in fit_payload.items() if key != "fitted_latex"}),
                },
            )
            logger.info(f"LaTeX task {task_id} succeeded for job {job_id} ({pdf_size} bytes)")
            _log_task_timing("success", _compile_duration, _reporting_start)
            if quota_refund and completion_event:
                clear_quota_refund_receipt(job_id)

            # Preview/redaction jobs are derived artifacts, not user edits. Never
            # let them pollute the resumable version history.
            _resume_id = resume_id or (metadata or {}).get("resume_id")
            skip_auto_save = bool((metadata or {}).get("skip_auto_save"))
            if not replayed and _resume_id and user_id and not watermark and not skip_auto_save:
                from .auto_save_worker import submit_auto_save_checkpoint

                submit_auto_save_checkpoint(_resume_id, user_id, latex_content)

            return result

        record_compile("error", duration_seconds=_compile_duration)
        error_msg = f"{compiler} exited with code {proc.returncode}"
        stderr = transcript.text()
        logger.error(
            "latex_compile_failed",
            extra={
                "job_id": job_id,
                "returncode": proc.returncode,
                "stderr_tail": stderr[-500:] if stderr else "",
            },
        )
        result: Dict[str, Any] = {"success": False, "job_id": job_id, "error": error_msg}
        if first_latex_error:
            result["latex_error_line"] = first_latex_error
        terminal_accepted = publish_job_result(job_id, result)
        if terminal_accepted:
            publish_event(
                job_id,
                "job.failed",
                {
                    "stage": "latex_compilation",
                    "error_code": "latex_error",
                    "error_message": error_msg,
                    "retryable": False,
                },
            )
        # Prefer the specific LaTeX error line over the generic exit-code message.
        reconcile_compilation_record(
            job_id,
            success=False,
            compilation_time=compilation_time,
            error_message=first_latex_error or error_msg,
            lifecycle_owner=reconcile_owner,
            lifecycle_epoch=lifecycle_epoch,
            terminal_result=result,
        )
        _log_task_timing("compile_error", _compile_duration, _reporting_start)
        return _terminal_failure(result, accepted=terminal_accepted)

    except SoftTimeLimitExceeded:
        logger.error(f"LaTeX task {task_id} hit soft time limit for job {job_id}", exc_info=True)
        # Kill the subprocess if it was started before the limit fired
        try:
            proc.kill()
            cleanup_docker_container(container_name)
            proc.wait()
        except Exception:
            pass
        upgrade_msg = (
            "Upgrade to Pro for a 4-minute compile timeout"
            if resolve_plan_family(user_plan) in {"free", "basic"}
            else None
        )
        result = {"success": False, "job_id": job_id, "error": "compile_timeout"}
        terminal_accepted = publish_job_result(job_id, result)
        if terminal_accepted:
            publish_event(
                job_id,
                "job.failed",
                {
                    "stage": "latex_compilation",
                    "error_code": "compile_timeout",
                    "error_message": f"Compilation timed out after {int(timeout)}s ({user_plan} plan limit)",
                    "upgrade_message": upgrade_msg,
                    "user_plan": user_plan,
                    "timeout_seconds": int(timeout),
                    "retryable": False,
                },
            )
        reconcile_compilation_record(
            job_id,
            success=False,
            error_message="compile_timeout",
            lifecycle_owner=reconcile_owner,
            lifecycle_epoch=lifecycle_epoch,
            terminal_result=result,
        )
        _log_task_timing("soft_time_limit_exceeded")
        return _terminal_failure(result, accepted=terminal_accepted)

    except Exception as exc:
        cleanup_docker_container(locals().get("container_name"))
        logger.error("LaTeX task %s raised", task_id, extra={"error_type": type(exc).__name__})
        retryable = self.request.retries < self.max_retries
        if retryable:
            # A retry is scheduled — surface a transient 'retrying' event rather than a
            # terminal job.failed, so the client doesn't flip to a failure state for a job
            # that may still succeed. job.failed is reserved for the terminal case below.
            publish_event(
                job_id,
                "job.retrying",
                {
                    "stage": "latex_compilation",
                    "worker_id": worker_id,
                    "attempt": self.request.retries + 2,
                    "error_message": "LaTeX compilation is retrying",
                },
            )
            raise self.retry(countdown=min(60 * (2**self.request.retries), 600), exc=exc)
        result = {"success": False, "job_id": job_id, "error": "LaTeX compilation failed"}
        terminal_accepted = publish_job_result(job_id, result)
        if terminal_accepted:
            publish_event(
                job_id,
                "job.failed",
                {
                    "stage": "latex_compilation",
                    "error_code": "internal",
                    "error_message": "LaTeX compilation failed",
                    "retryable": False,
                },
            )
        reconcile_compilation_record(
            job_id,
            success=False,
            error_message="LaTeX compilation failed",
            lifecycle_owner=reconcile_owner,
            lifecycle_epoch=lifecycle_epoch,
            terminal_result=result,
        )
        _log_task_timing("exception")
        return _terminal_failure(result, accepted=terminal_accepted)
    finally:
        if job_dir is not None and job_dir.exists():
            try:
                shutil.rmtree(job_dir)
            except Exception as cleanup_exc:
                logger.warning("Failed to remove job_dir %s: %s", job_dir, cleanup_exc)


# ------------------------------------------------------------------ #
#  Submission helper                                                   #
# ------------------------------------------------------------------ #


def submit_latex_compilation(
    latex_content: str,
    job_id: str,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None,
    resume_id: Optional[str] = None,
    compiler: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    compile_settings: Optional[Dict] = None,
    watermark: Optional[str] = None,
    quota_refund: Optional[Dict[str, Any]] = None,
    auto_fit: bool = False,
    auto_fit_intensity: Optional[int] = None,
) -> str:
    """Enqueue compile_latex_task on the latex queue (Celery) or Modal."""
    import os

    if priority is None:
        priority = get_task_priority(user_plan)
    compiler = compiler or settings.DEFAULT_LATEX_COMPILER
    timeout = timeout_seconds or get_compile_timeout(user_plan)

    if os.environ.get("DEPLOY_TARGET") == "modal":
        from ..core.modal_dispatch import spawn

        spawn(
            "run_latex_task",
            {
                "latex_content": latex_content,
                "job_id": job_id,
                "user_id": user_id,
                "user_plan": user_plan,
                "device_fingerprint": device_fingerprint,
                "metadata": metadata,
                "resume_id": resume_id,
                "compiler": compiler,
                "timeout_seconds": timeout,
                "compile_settings": compile_settings,
                "watermark": watermark,
                "quota_refund": quota_refund,
                "auto_fit": auto_fit,
                "auto_fit_intensity": auto_fit_intensity,
            },
        )
        logger.info(f"Modal spawn: LaTeX compilation for job {job_id} (compiler={compiler})")
        return job_id

    compile_latex_task.apply_async(
        args=[latex_content],
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "user_plan": user_plan,
            "device_fingerprint": device_fingerprint,
            "metadata": metadata,
            "resume_id": resume_id,
            "compiler": compiler,
            "timeout_seconds": timeout,
            "compile_settings": compile_settings,
            "watermark": watermark,
            "quota_refund": quota_refund,
            "auto_fit": auto_fit,
            "auto_fit_intensity": auto_fit_intensity,
        },
        priority=priority,
        queue="latex",
        task_id=job_id,
        time_limit=(timeout * 2 + 30) if auto_fit else timeout + 30,
        soft_time_limit=(timeout * 2 + 15) if auto_fit else timeout + 15,
    )
    logger.info(f"Submitted LaTeX compilation for job {job_id} (compiler={compiler}, timeout={timeout}s)")
    return job_id
