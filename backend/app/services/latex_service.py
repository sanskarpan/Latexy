"""
LaTeX compilation service.
"""

import asyncio
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from ..core.config import get_compile_timeout, settings
from ..core.logging import get_logger
from ..models.schemas import CompilationResponse

logger = get_logger(__name__)

# ── Engine sandboxing (the PRIMARY control) ─────────────────────────────────
# A denylist of TeX primitives cannot be won by string matching: \csname…\endcsname,
# \catcode games and ^^-notation can reconstruct any control sequence. So the primary
# control is HOW the engine is invoked, not what the source looks like:
#
#   * ``-no-shell-escape``      — \write18 / \ShellEscape are hard-disabled.
#   * ``openout_any=p`` — kpathsea refuses WRITES to dotfiles, parent-directory
#     escapes and absolute paths. Its read-side twin ``openin_any`` is set too but
#     is a NO-OP from TeX Live 2025 onwards (upstream texmf.cnf: "as of 2026,
#     openin_any no longer has any effect"), so reads are policed after the fact by
#     ``find_engine_read_escape()`` (transcript) and ``find_recorder_read_escape()``
#     (the ``-recorder`` .fls file) below — see those functions. Neither PREVENTS the
#     read; both stop the bytes reaching the caller.
#   * ``-recorder`` — makes kpathsea log every file the engine opens to
#     ``<jobname>.fls``. This is the only complete record: \openin reads never appear
#     in the transcript at all.
#   * Docker: no network, no capabilities, no privilege escalation, so a compromised
#     engine only ever sees the ephemeral container plus the job directory.
#   * A minimal subprocess environment — the Celery worker holds DATABASE_URL,
#     REDIS_URL, provider API keys and API_KEY_ENCRYPTION_KEY, and none of that has
#     any business being inherited by pdflatex.
#
# ``validate_latex_content()`` below stays in place as defence in depth, never as the
# only guard.

# Flags appended to every engine invocation (Docker and local alike).
LATEX_SANDBOX_FLAGS: tuple[str, ...] = ("-no-shell-escape", "-recorder")

# kpathsea knobs, passed through the engine environment.
_LATEX_SANDBOX_KPSE_VARS: dict[str, str] = {
    "openin_any": "p",
    "openout_any": "p",
    "shell_escape": "f",
    # Stop the engine wrapping its transcript at 79 columns: a wrapped path would
    # split across two lines and slip past find_engine_read_escape().
    "max_print_line": "10000",
}

# ``docker run`` hardening flags.
_DOCKER_SANDBOX_FLAGS: tuple[str, ...] = (
    "--network", "none",
    "--security-opt", "no-new-privileges",
    "--cap-drop", "ALL",
    "--pids-limit", "512",
)

# Only these variables are forwarded to the engine subprocess. Everything else in the
# worker environment (credentials, connection strings) is dropped. The DOCKER_* entries
# are needed so the ``docker`` CLI can still find its daemon/context.
_ENGINE_ENV_PASSTHROUGH: tuple[str, ...] = (
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SOURCE_DATE_EPOCH",
    "TEXMFHOME", "TEXMFVAR", "TEXMFCONFIG", "TEXMFCNF", "TEXINPUTS",
    "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG",
    "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY",
)

_TRUTHY = ("1", "true", "yes", "on")


def docker_engine_available() -> bool:
    """Whether the sandboxed Docker LaTeX engine can be used."""
    return shutil.which("docker") is not None


def docker_sandbox_args() -> list[str]:
    """``docker run`` arguments that confine the LaTeX engine."""
    args = list(_DOCKER_SANDBOX_FLAGS)
    for name, value in _LATEX_SANDBOX_KPSE_VARS.items():
        args += ["-e", f"{name}={value}"]
    return args


def engine_env() -> dict[str, str]:
    """Minimal environment for the engine subprocess (no app credentials)."""
    env = {name: os.environ[name] for name in _ENGINE_ENV_PASSTHROUGH if name in os.environ}
    env.update(_LATEX_SANDBOX_KPSE_VARS)
    return env


ENGINE_UNAVAILABLE_ERROR = "LaTeX compilation is temporarily unavailable."


def running_in_container() -> bool:
    """Whether this process is itself running inside a container.

    That is the SHIPPED production topology: ``backend/Dockerfile.prod`` bakes
    texlive into the worker image and neither the k8s manifests nor
    ``docker-compose.prod.yml`` give the worker a docker CLI or /var/run/docker.sock.
    "texlive inside my own container" and "pdflatex on a developer's bare host" are
    different threat models — the container is already the isolation boundary — so
    the in-image engine must not be gated as if it were the latter.
    """
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return True
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return True
    try:
        cgroup = Path("/proc/self/cgroup").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(marker in cgroup for marker in ("docker", "kubepods", "containerd", "podman"))


def local_engine_allowed() -> bool:
    """Whether running the LaTeX engine directly in the worker process is permitted.

    Allowed when:
      * ``ALLOW_LOCAL_LATEX_ENGINE`` is set (explicit operator choice, either way); or
      * we are inside a container — the in-image texlive of the production worker
        image, whose blast radius is that ephemeral container; or
      * we are outside production, so ``./scripts/dev.sh app`` keeps working on a
        machine without the Docker image.

    Fails closed only for the case it was written for: a production process on a
    bare host, where pdflatex would share the filesystem with everything else.
    """
    raw = os.environ.get("ALLOW_LOCAL_LATEX_ENGINE")
    if raw is not None:
        return raw.strip().lower() in _TRUTHY
    # Modal runs each worker in an isolated gVisor container with texlive baked
    # into the image, but its /proc/self/cgroup does not carry the
    # docker/kubepods/containerd markers running_in_container() looks for, so
    # detect the Modal target explicitly — the in-image engine is exactly the
    # intended, sandboxed production path there.
    if (settings.DEPLOY_TARGET or "").lower() == "modal":
        return True
    if running_in_container():
        return True
    return settings.normalized_environment != "production"


def assert_local_engine_allowed(job_id: str) -> None:
    """Gate + log the non-Docker local-engine path.

    Raises RuntimeError only when the fallback is genuinely unsafe (production, on a
    bare host, not opted in) so that case surfaces as a failed compile instead of
    silently downgrading every job to an unsandboxed host process.
    """
    if not local_engine_allowed():
        # The remedy is an ops decision, so it goes to the logs; the caller only ever
        # sees the generic message (str(exc) is echoed back to the API client).
        logger.error(
            "[%s] Docker LaTeX engine unavailable and the local engine fallback is "
            "disabled (production, not containerised). Install/expose the docker CLI "
            "or set ALLOW_LOCAL_LATEX_ENGINE=true to run the engine in-process.",
            job_id,
        )
        raise RuntimeError(ENGINE_UNAVAILABLE_ERROR)
    logger.warning(
        "[%s] Docker unavailable — running the LaTeX engine in-process. The engine "
        "shares this process's filesystem (containerised=%s); reads outside the job "
        "directory are detected and fail the job, but this is weaker than the "
        "Docker sandbox.",
        job_id,
        running_in_container(),
    )


# ── Read confinement ────────────────────────────────────────────────────────
# openin_any is a no-op on current TeX Live, and no source-level denylist can stop a
# read: \csname input\endcsname, \newcommand{\zz}{\input}\zz{...}, \catcode games and
# ^^-notation all rebuild the primitive without ever spelling it. So the read control
# is applied to GROUND TRUTH instead, in two layers:
#
#   1. find_engine_read_escape() — \input-style reads are announced in the transcript
#      as "(<path>". Watching that stream kills the compile BEFORE the offending line
#      (and therefore the file's contents) is streamed to the client.
#   2. find_recorder_read_escape() — \openin/\read announces NOTHING in the transcript,
#      so layer 1 never fires for it. ``-recorder`` makes kpathsea write every open to
#      <jobname>.fls, which does list it ("INPUT /etc/hostname"). That file only exists
#      once the run finishes, so this layer is a post-run gate: it runs before the PDF,
#      the extracted text or the log are published, and fails the whole job.
#
# Detection, not prevention: the bytes were read by the engine. What both layers remove
# is the exfiltration channel, which is what actually matters to the caller.
_ENGINE_TEXMF_ROOTS: tuple[str, ...] = (
    "/usr/local/texlive/", "/usr/share/texlive/", "/usr/share/texmf",
    "/usr/local/share/texmf", "/usr/local/texmf/", "/opt/texlive/",
    "/etc/texmf/", "/var/lib/texmf/", "/usr/share/fonts/", "/usr/local/share/fonts/",
)

# TeX announces an opened file as "(name" (optionally quoted when it contains spaces).
# Only tokens that look like a path are considered: absolute, or containing a
# parent-directory hop.
_ENGINE_OPEN_RE = re.compile(r'\(\s*(?:"([^"\n]+)"|([^\s()"]+))')


def _engine_jail(workspace: str) -> set[str]:
    """Directories an engine open is allowed to resolve inside.

    macOS resolves TMPDIR through a symlink (/var → /private/var) and the engine
    prints the resolved form, so accept both spellings of the job directory.
    """
    workspace = os.path.normpath(workspace)
    return {workspace, os.path.realpath(workspace)}


def _escapes_jail(resolved: str, jail: set[str]) -> bool:
    """Whether *resolved* is outside the job directory and outside the TeX tree."""
    if any(resolved == root or resolved.startswith(root + "/") for root in jail):
        return False
    return not resolved.startswith(_ENGINE_TEXMF_ROOTS)


def find_engine_read_escape(line: str, workspace: str) -> Optional[str]:
    """Return the first path in *line* the engine opened outside its jail, else None.

    *workspace* is the directory the engine was pointed at (``/workspace`` in the
    Docker path, the job directory locally).
    """
    workspace = os.path.normpath(workspace)
    jail = _engine_jail(workspace)
    for match in _ENGINE_OPEN_RE.finditer(line):
        raw = match.group(1) or match.group(2)
        if "/" not in raw and "\\" not in raw:
            continue  # "(1 page, 100 bytes)" and friends
        if not raw.startswith("/") and ".." not in raw.split("/"):
            continue  # ordinary relative include inside the job dir
        resolved = os.path.normpath(
            raw if raw.startswith("/") else os.path.join(workspace, raw)
        )
        if _escapes_jail(resolved, jail):
            return resolved
    return None


# ``<jobname>.fls`` is written by kpathsea itself when ``-recorder`` is passed. Format:
# a ``PWD <dir>`` header followed by one ``INPUT <path>`` / ``OUTPUT <path>`` line per
# open. Paths are absolute or relative to PWD.
RECORDER_SUFFIX = ".fls"


def find_recorder_read_escape(
    fls_file: Path,
    workspace: str,
    *,
    require_recorder: bool = True,
) -> Optional[str]:
    """Return the first recorder-file violation for this run, else None.

    Called after the engine exits and BEFORE the PDF / extracted text / log are
    published, because ``\\openin``-style reads leave no trace in the transcript that
    :func:`find_engine_read_escape` could catch mid-stream.

    Fails CLOSED: a missing or tampered recorder file is itself a violation. A document
    can ``\\openout`` over ``<jobname>.fls`` (openout_any=p allows same-directory
    writes) to hide its own reads, which leaves the file NUL-padded and self-referential
    — both are rejected here, and neither can happen in an honest compile.

    *require_recorder* should be False when the engine never produced output anyway
    (``docker run`` itself failed, image missing): there is nothing to leak, and the
    real error is more useful to the caller than a spurious confinement failure.
    """
    try:
        raw = fls_file.read_bytes()
    except OSError:
        return f"<no recorder file at {fls_file}>" if require_recorder else None

    if b"\x00" in raw:
        return f"<recorder file {fls_file.name} was overwritten by the document>"

    jail = _engine_jail(workspace)
    recorder_names = {fls_file.name, os.path.join(workspace, fls_file.name)}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        verb, _, target = line.partition(" ")
        if verb not in ("INPUT", "OUTPUT"):
            continue
        target = target.strip()
        if not target:
            continue
        if verb == "OUTPUT":
            # The engine never records itself opening its own recorder file; only a
            # \openout from the document does, and that is a tampering attempt.
            if target in recorder_names or os.path.basename(target) == fls_file.name:
                return f"<recorder file {fls_file.name} was overwritten by the document>"
            continue
        resolved = os.path.normpath(
            target if target.startswith("/") else os.path.join(workspace, target)
        )
        if _escapes_jail(resolved, jail):
            return resolved
    return None


ENGINE_READ_ESCAPE_ERROR = (
    "Compilation blocked: the document tried to read a file outside its own "
    "directory."
)


# ── LaTeX injection guards (defence in depth) ───────────────────────────────
# TeX comments can hide anything from a naive scan, and \csname input\endcsname
# builds \input without the literal token ever appearing, so normalise before matching.
_COMMENT_RE = re.compile(r"(?<!\\)%[^\n]*")
_CSNAME_RE = re.compile(r"\\csname\s*([A-Za-z@\s]*?)\s*\\endcsname")

# \write18 and \openout/\openin enable shell-escape / arbitrary file IO and have no
# legitimate use in a resume — reject outright regardless of argument. \directlua and
# \latelua give lualatex (an allowed compiler) full io.* access. A TeX control word ends
# at the first non-letter, so \openin1=… is \openin followed by a stream number: match
# on (?![A-Za-z]) rather than \b, which a trailing digit would defeat. Whitespace
# between a control word and its argument is likewise tolerated by TeX (\write 18).
_SHELL_ESCAPE_RE = re.compile(
    r"\\(?:write\s*18|input18|openout|openin|closein|ShellEscape|shellescape"
    r"|directlua|latelua)(?![A-Za-z])"
)

# File-reading primitives (\input, \include, \InputIfFileExists, \lstinputlisting,
# \verbatiminput, the \@@input / \@input internals used by \makeatletter tricks, …)
# can slurp arbitrary host files into the rendered PDF. Relative includes are
# legitimate for multi-file resumes, so only reject arguments that reference an
# ABSOLUTE path or a parent-directory traversal. Whitespace between the command and
# its argument (with or without a brace) is tolerated by TeX, so we match it here too.
# Home-dir (~) and Windows drive (C:) prefixes are also blocked.
#
# This catches the LITERAL spellings only, and that is all it is claimed to do: one
# \newcommand (\newcommand{\zz}{\input}\zz{../../etc/hostname}) or one \csname built
# from \string (\csname openi\string n\endcsname, which _normalize_for_scanning cannot
# fold) walks straight past it. find_engine_read_escape() and, for \openin,
# find_recorder_read_escape() are what actually stop the read reaching the caller.
_ABS_FILE_READ_RE = re.compile(
    r"\\(?:@@input|@input|@iinput|input|include|subfile|subfileinclude|"
    r"InputIfFileExists|lstinputlisting|verbatiminput|import|subimport)(?![A-Za-z])"
    r"\s*(?:\[[^\]]*\])?\s*\{?\s*"
    r"(?:/|~|\.\.[\\/]|[A-Za-z]:[\\/])"
)


def _normalize_for_scanning(content: str) -> str:
    """Strip TeX comments and resolve literal \\csname…\\endcsname control words.

    ``\\csname input\\endcsname{/etc/passwd}`` becomes ``\\input{/etc/passwd}`` so the
    denylist below sees the same token the engine would build.
    """
    content = _COMMENT_RE.sub("", content)

    def _resolve(match: re.Match) -> str:
        name = re.sub(r"\s+", "", match.group(1))
        return "\\" + name if name else match.group(0)

    return _CSNAME_RE.sub(_resolve, content)


class LaTeXService:
    """Service for LaTeX compilation operations."""

    def __init__(self):
        """Initialize the LaTeX service."""
        # Ensure temp directory exists
        settings.TEMP_DIR.mkdir(exist_ok=True)

    def validate_latex_content(self, content: str) -> bool:
        """Basic validation of LaTeX content."""
        if not content.strip():
            return False

        # Check for basic LaTeX structure
        has_document_class = "\\documentclass" in content
        has_begin_document = "\\begin{document}" in content
        has_end_document = "\\end{document}" in content

        if not (has_document_class and has_begin_document and has_end_document):
            return False

        # Scan a comment-stripped, \csname-resolved copy so obfuscated variants
        # (\csname input\endcsname{…}) hit the same rules as the plain spelling.
        scannable = _normalize_for_scanning(content)

        # Reject shell-escape / file-write attack vectors regardless of whether
        # --shell-escape is active. These directives have no legitimate use in a
        # resume template and are the primary LaTeX code-execution paths.
        if _SHELL_ESCAPE_RE.search(scannable):
            return False

        # Reject file-read primitives that target an absolute path or traversal
        # (e.g. \input{/etc/passwd}, \input {/etc/passwd}, \include{../../secret}).
        # Relative includes for multi-file resumes remain allowed.
        if _ABS_FILE_READ_RE.search(scannable):
            return False

        return True

    def check_latex_installation(self) -> bool:
        """Check if Docker and LaTeX Docker image are available."""
        try:
            # Check if Docker is available
            docker_result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if docker_result.returncode != 0:
                return False

            # Check if LaTeX Docker image is available
            image_result = subprocess.run(
                ["docker", "image", "inspect", settings.LATEX_DOCKER_IMAGE],
                capture_output=True,
                text=True,
                timeout=5
            )
            return image_result.returncode == 0
        except Exception:
            return False

    async def compile_latex(self, latex_content: str, job_id: Optional[str] = None, user_plan: str = "free") -> CompilationResponse:
        """Compile LaTeX content to PDF.

        Reachable unauthenticated through ``POST /public/compile``, so it applies the
        same controls as the Celery path: Docker when available, the gated local engine
        otherwise, and the recorder-file read confinement before anything is published.
        The engine transcript is only returned on FAILURE (where it is the error
        message); a successful compile has no reason to hand the caller a transcript.
        """
        if job_id is None:
            job_id = str(uuid.uuid4())

        start_time = time.time()

        # Create job-specific directory
        job_dir = settings.TEMP_DIR / job_id
        job_dir.mkdir(exist_ok=True)

        tex_file = job_dir / "resume.tex"
        pdf_file = job_dir / "resume.pdf"
        log_file = job_dir / "resume.log"

        try:
            # Write LaTeX content to file
            tex_file.write_text(latex_content, encoding='utf-8')
            logger.info(f"Created LaTeX file for job {job_id}")

            # Docker when it is there, the gated in-process engine otherwise — the
            # production image bakes texlive in and ships no docker CLI, so a
            # Docker-only path would hard-fail every request there.
            if docker_engine_available():
                compile_cmd = [
                    "docker", "run", "--rm",
                    *docker_sandbox_args(),
                    "-v", f"{job_dir}:/workspace",
                    "-w", "/workspace",
                    settings.LATEX_DOCKER_IMAGE,
                    "pdflatex",
                    *LATEX_SANDBOX_FLAGS,
                    "-interaction=nonstopmode",
                    "-output-directory", "/workspace",
                    "-jobname", "resume",
                    "resume.tex"
                ]
                compile_cwd = None
                workspace = "/workspace"
            else:
                assert_local_engine_allowed(job_id)
                compile_cmd = [
                    "pdflatex",
                    *LATEX_SANDBOX_FLAGS,
                    "-interaction=nonstopmode",
                    "-output-directory", str(job_dir),
                    "-jobname", "resume",
                    "resume.tex"
                ]
                compile_cwd = str(job_dir)
                workspace = str(job_dir)

            logger.info(f"Starting LaTeX compilation for job {job_id}")

            # Run compilation with timeout
            process = await asyncio.create_subprocess_exec(
                *compile_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=compile_cwd,
                env=engine_env(),
            )

            timeout = get_compile_timeout(user_plan)
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise HTTPException(
                    status_code=408,
                    detail=f"LaTeX compilation timed out after {timeout} seconds"
                )

            compilation_time = time.time() - start_time

            # Read log output
            log_output = ""
            if log_file.exists():
                log_output = log_file.read_text(encoding='utf-8', errors='ignore')
            else:
                # If no log file, use stdout/stderr
                log_output = stdout.decode('utf-8', errors='ignore')
                if stderr:
                    log_output += "\n" + stderr.decode('utf-8', errors='ignore')

            # Read confinement, before the PDF or the transcript is handed back: the
            # recorder file lists every file the engine opened, including the \openin
            # reads the transcript stays silent about.
            recorder_escape = find_recorder_read_escape(
                job_dir / f"resume{RECORDER_SUFFIX}",
                workspace,
                require_recorder=process.returncode == 0,
            )
            if recorder_escape:
                logger.warning(
                    "[%s] engine read outside the job directory (recorder): %s",
                    job_id,
                    recorder_escape,
                )
                # The PDF renders whatever was read, and GET /download would serve it.
                self.cleanup_temp_files(job_dir)
                return CompilationResponse(
                    success=False,
                    job_id=job_id,
                    message=ENGINE_READ_ESCAPE_ERROR,
                    compilation_time=compilation_time,
                )

            # Check if compilation was successful
            if process.returncode == 0 and pdf_file.exists():
                pdf_size = pdf_file.stat().st_size
                logger.info(f"Compilation successful for job {job_id}. PDF size: {pdf_size} bytes")

                return CompilationResponse(
                    success=True,
                    job_id=job_id,
                    message="LaTeX compiled successfully",
                    compilation_time=compilation_time,
                    pdf_size=pdf_size,
                )
            else:
                error_msg = f"LaTeX compilation failed. Return code: {process.returncode}"
                if stderr:
                    error_msg += f"\nStderr: {stderr.decode('utf-8', errors='ignore')}"

                logger.error(f"Compilation failed for job {job_id}: {error_msg}")

                return CompilationResponse(
                    success=False,
                    job_id=job_id,
                    message="LaTeX compilation failed",
                    compilation_time=compilation_time,
                    log_output=log_output
                )

        except Exception as e:
            logger.error(f"Error during compilation for job {job_id}: {e}")
            return CompilationResponse(
                success=False,
                job_id=job_id,
                message=f"Compilation error: {str(e)}"
            )

    def cleanup_temp_files(self, job_dir: Path) -> None:
        """Clean up temporary files after compilation."""
        try:
            if job_dir.exists():
                shutil.rmtree(job_dir)
                logger.info(f"Cleaned up temporary directory: {job_dir}")
        except Exception as e:
            logger.error(f"Error cleaning up {job_dir}: {e}")

    async def cleanup_temp_files_delayed(self, job_dir: Path, delay: int = 5):
        """Clean up temporary files after a delay."""
        await asyncio.sleep(delay)
        self.cleanup_temp_files(job_dir)


# Global service instance
latex_service = LaTeXService()


def run_latex_subprocess(
    job_id: str,
    latex_content: str,
    timeout: Optional[float] = None,
) -> tuple[bool, float, str]:
    """
    Shared synchronous LaTeX compilation helper used by both
    ``latex_worker.py`` and ``orchestrator.py``.

    Writes *latex_content* to ``{TEMP_DIR}/{job_id}/resume.tex``,
    runs pdflatex (Docker if available, else local texlive),
    streams every log line via ``publish_event``, honours
    cancellation flags and an optional *timeout*, then returns
    ``(success, compilation_time, error_message)``.

    Callers are responsible for publishing ``job.failed`` so they
    can include any extra payload (e.g. ``optimized_latex``).
    """
    # Lazy import to avoid circular imports (workers → services → workers)
    from ..workers.event_publisher import is_cancelled, publish_event  # noqa: PLC0415

    job_dir = settings.TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    tex_file = job_dir / "resume.tex"
    pdf_file = job_dir / "resume.pdf"
    tex_file.write_text(latex_content, encoding="utf-8")

    if docker_engine_available():
        compile_cmd = [
            "docker", "run", "--rm",
            *docker_sandbox_args(),
            "-v", f"{job_dir}:/workspace",
            "-w", "/workspace",
            settings.LATEX_DOCKER_IMAGE,
            "pdflatex",
            *LATEX_SANDBOX_FLAGS,
            "-interaction=nonstopmode",
            "-synctex=1",
            "-output-directory", "/workspace",
            "-jobname", "resume",
            "resume.tex",
        ]
        compile_cwd = None
        workspace = "/workspace"
    else:
        assert_local_engine_allowed(job_id)
        compile_cmd = [
            "pdflatex",
            *LATEX_SANDBOX_FLAGS,
            "-interaction=nonstopmode",
            "-synctex=1",
            "-output-directory", str(job_dir),
            "-jobname", "resume",
            "resume.tex",
        ]
        compile_cwd = str(job_dir)
        workspace = str(job_dir)

    start_time = time.time()
    proc = subprocess.Popen(
        compile_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=compile_cwd,
        env=engine_env(),
    )

    for raw_line in proc.stdout:  # type: ignore[union-attr]
        line = raw_line.rstrip("\n")
        if not line:
            continue
        escaped = find_engine_read_escape(line, workspace)
        if escaped:
            # Kill before publishing: the next lines would carry the file's contents.
            proc.kill()
            proc.wait()
            logger.warning("[%s] engine read outside the job directory: %s", job_id, escaped)
            return False, time.time() - start_time, ENGINE_READ_ESCAPE_ERROR

        line_lower = line.lower()
        is_error = any(kw in line_lower for kw in ("error", "fatal", "undefined control"))
        publish_event(job_id, "log.line", {
            "source": "pdflatex",
            "line": line,
            "is_error": is_error,
        })

        if timeout is not None and time.time() - start_time > timeout:
            proc.kill()
            proc.wait()
            return False, time.time() - start_time, f"pdflatex timed out after {timeout:.0f}s"

        if is_cancelled(job_id):
            proc.kill()
            proc.wait()
            raise RuntimeError("Job cancelled during LaTeX compilation")

    proc.wait()
    compilation_time = time.time() - start_time

    # Post-run gate: \openin reads never reach the transcript, so the recorder file is
    # the only place they show up. Checked before anything is reported as successful.
    recorder_escape = find_recorder_read_escape(
        job_dir / f"resume{RECORDER_SUFFIX}",
        workspace,
        require_recorder=proc.returncode == 0,
    )
    if recorder_escape:
        logger.warning(
            "[%s] engine read outside the job directory (recorder): %s", job_id, recorder_escape
        )
        return False, compilation_time, ENGINE_READ_ESCAPE_ERROR

    if proc.returncode == 0 and pdf_file.exists():
        return True, compilation_time, ""

    return False, compilation_time, (
        f"pdflatex exited with code {proc.returncode}. "
        "See log.line events for details."
    )
