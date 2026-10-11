# Extracted unchanged from main317b9b3 _run_latex_stage for reproducible benchmark.
def _run_latex_stage(
    job_id: str,
    latex_content: str,
    compiler: str = "pdflatex",
    timeout_seconds: Optional[int] = None,
    bibtex: object = None,
    halt_on_error: bool = True,
    draft_mode: bool = False,
    main_file: Optional[str] = None,
    extra_packages: Optional[List[str]] = None,
    latexmk_flags: Optional[List[str]] = None,
) -> tuple[bool, float, str, Optional[int], Optional[bytes]]:
    """
    Write LaTeX, run the requested compiler (sandboxed Docker engine if available,
    else the opt-in local engine) with line-by-line log streaming.

    The LLM-produced LaTeX goes through the same latex_service.validate_latex_content
    gate as the direct compile path — the combined path used to skip it entirely, so a
    prompt-injected \\input{/etc/passwd} would have been compiled and its contents
    streamed back over the job's log.line events.

    Returns (success, compilation_time, error_message, page_count, pdf_bytes).
    The log and (on success) the PDF + SyncTeX data are cached in Redis before
    job_dir is removed, so GET /download/{job_id}, /logs/{job_id} and
    /download/{job_id}/synctex keep working — same artifacts as latex_worker.
    Does NOT publish job.failed — caller is responsible so it can
    include optimized_latex in the failure payload.
    """
    # Validate compiler
    if compiler not in settings.ALLOWED_LATEX_COMPILERS:
        compiler = settings.DEFAULT_LATEX_COMPILER
    # Even worker payloads must respect the same filename/flag/package boundary
    # as the direct compile path. Keep artifact names stable independently of
    # the user's input filename.
    main_file = main_file if isinstance(main_file, str) and _MAIN_FILE_RE.fullmatch(main_file) else "resume.tex"
    custom_flags = [flag for flag in (latexmk_flags or []) if isinstance(flag, str) and flag in _ALLOWED_EXTRA_FLAGS]
    if isinstance(extra_packages, list):
        latex_content = _inject_packages(latex_content, extra_packages)
    if draft_mode:
        latex_content = _inject_draft_graphics(latex_content)

    # Shared content gate (same call the latex_compilation path makes)
    if not latex_service.validate_latex_content(latex_content):
        error_msg = (
            r"Invalid LaTeX: missing \documentclass, \begin{document}, "
            r"\end{document}, or disallowed file/shell primitives"
        )
        # This gate runs BEFORE the compiler ever starts, so there is no
        # pdflatex stdout to stream — without this, the Live Logs panel stays
        # completely empty on failure (the caller publishes job.failed from
        # the returned error_msg alone). Publish it as a log line too, so it
        # shows up the same way a real compiler failure's output would.
        publish_event(
            job_id,
            "log.line",
            {
                "line": f"! {error_msg}",
                "source": compiler,
                "is_error": True,
            },
        )
        return False, 0.0, error_msg, None, None

    job_dir = Path(settings.TEMP_DIR) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    try:
        tex_file = job_dir / main_file
        tex_file.write_text(latex_content, encoding="utf-8")
        materialize_embedded_signature(latex_content, job_dir)
        write_reference_library(job_dir, bibtex)
        error_mode_flags = ["-interaction=nonstopmode"]
        if halt_on_error:
            error_mode_flags.append("-halt-on-error")

        use_docker = docker_engine_available()
        container_name = docker_container_name(job_id, "orchestrator") if use_docker else None
        if use_docker:
            cmd = [
                "docker",
                "run",
                "--rm",
                "--name",
                container_name,
                *docker_sandbox_args(),
                "-v",
                f"{job_dir}:/workdir",
                "-w",
                "/workdir",
                settings.LATEX_DOCKER_IMAGE,
                compiler,
                *LATEX_SANDBOX_FLAGS,
                *error_mode_flags,
                "-synctex=1",
                "-jobname",
                "resume",
                *custom_flags,
                main_file,
            ]
            cwd = None
            workspace = "/workdir"
        else:
            assert_local_engine_allowed(job_id)
            # Relative paths + cwd=job_dir: the sandbox sets openin_any/openout_any=p
            # (paranoid), under which kpathsea refuses ABSOLUTE read/write paths, so
            # an absolute /tmp/.../resume.tex fails with "Not reading … (openin_any=p)".
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
            cwd = str(job_dir)
            workspace = str(job_dir)

        timeout = float(timeout_seconds) if timeout_seconds else float(settings.COMPILE_TIMEOUT)
        _perf_start = time.perf_counter()
        with traced("latex.compile", compiler=compiler, docker=(cmd[0] == "docker")):
            start_time = time.time()
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                env=engine_env(),
            )

            page_count: Optional[int] = None
            transcript = BoundedTranscript()
            watchdog = ProcessWatchdog(
                proc,
                timeout=timeout,
                is_cancelled=lambda: is_cancelled(job_id),
            ).start()
            try:
                for stripped in iter_bounded_lines(proc.stdout):
                    if stripped:
                        # Read confinement (see latex_service.find_engine_read_escape):
                        # kill before the line is streamed, because what follows it is
                        # the contents of whatever file was opened. \openin reads are
                        # invisible here — the recorder check after the run covers those.
                        escaped = find_engine_read_escape(stripped, workspace)
                        if escaped:
                            proc.kill()
                            cleanup_docker_container(container_name)
                            proc.wait()
                            logger.warning(f"[{job_id}] engine read outside the job directory: {escaped}")
                            return (
                                False,
                                time.time() - start_time,
                                ENGINE_READ_ESCAPE_ERROR,
                                None,
                                None,
                            )

                        bounded_line = transcript.append(stripped)

                        # Extract page count from pdflatex summary line
                        m = _PAGE_COUNT_RE.search(stripped)
                        if m:
                            page_count = int(m.group(1))

                        is_error = "error" in stripped.lower() or stripped.startswith("!")
                        if "fatal" in stripped.lower():
                            is_error = True
                        publish_event(
                            job_id,
                            "log.line",
                            {
                                "line": bounded_line,
                                "source": compiler,
                                "is_error": is_error,
                            },
                        )

                    if is_cancelled(job_id):
                        proc.kill()
                        cleanup_docker_container(container_name)
                        proc.wait()
                        return False, time.time() - start_time, "cancelled", None, None

                    if time.time() - start_time > timeout:
                        proc.kill()
                        cleanup_docker_container(container_name)
                        proc.wait()
                        record_compile("error", duration_seconds=time.perf_counter() - _perf_start)
                        return (
                            False,
                            time.time() - start_time,
                            f"Compilation timed out after {int(timeout)}s",
                            None,
                            None,
                        )
            except SoftTimeLimitExceeded:
                # Kill the subprocess before the exception propagates to the task handler
                try:
                    proc.kill()
                    cleanup_docker_container(container_name)
                    proc.wait()
                except Exception:
                    pass
                raise
            except BaseException:
                # Any parser/publisher/read failure must not strand a named
                # daemon container.  The cleanup helper validates the exact name.
                try:
                    proc.kill()
                except (ProcessLookupError, AttributeError):
                    pass
                try:
                    proc.wait()
                except (ProcessLookupError, AttributeError):
                    pass
                cleanup_docker_container(container_name)
                raise
            finally:
                watchdog_reason = watchdog.stop()

            if watchdog_reason == "cancelled":
                cleanup_docker_container(container_name)
                proc.wait()
                return False, time.time() - start_time, "cancelled", None, None
            if watchdog_reason == "timeout":
                cleanup_docker_container(container_name)
                proc.wait()
                record_compile("error", duration_seconds=time.perf_counter() - _perf_start)
                return (
                    False,
                    time.time() - start_time,
                    f"Compilation timed out after {int(timeout)}s",
                    None,
                    None,
                )

            proc.wait()
            compilation_time = time.time() - start_time
        _compile_duration = time.perf_counter() - _perf_start

        # Post-run read confinement: the -recorder .fls file lists every file the
        # engine opened, including the \openin reads the transcript never mentions.
        # Checked before the log is cached and before the PDF is published.
        recorder_escape = find_recorder_read_escape(
            job_dir / f"resume{RECORDER_SUFFIX}",
            workspace,
            require_recorder=proc.returncode == 0,
        )
        if recorder_escape:
            logger.warning(f"[{job_id}] engine read outside the job directory: {recorder_escape}")
            return False, compilation_time, ENGINE_READ_ESCAPE_ERROR, None, None

        cache_compile_log(job_id, transcript.text())

        pdf_file = job_dir / "resume.pdf"
        if proc.returncode == 0 and pdf_file.exists():
            try:
                _pdf_bytes = pdf_file.stat().st_size
            except OSError:
                _pdf_bytes = None
            if _pdf_bytes is not None and _pdf_bytes > MAX_COMPILED_PDF_BYTES:
                return (
                    False,
                    compilation_time,
                    f"Compiled PDF exceeds the {MAX_COMPILED_PDF_BYTES} byte limit",
                    None,
                    None,
                )
            record_compile(
                "success",
                duration_seconds=_compile_duration,
                pdf_bytes=_pdf_bytes,
                pages=page_count,
            )
            # cache_compile_output caches the PDF (latexy:job:{id}:pdf) + SyncTeX
            # in Redis before job_dir is rmtree'd, so GET /download/{job_id}
            # works from the API container (Modal has no shared worker/API FS).
            # This supersedes the earlier inline PDF-only cache (same key).
            try:
                cached_pdf = cache_compile_output(job_id, job_dir)
            except BoundedReadError:
                return (
                    False,
                    compilation_time,
                    f"Compiled PDF exceeds the {MAX_COMPILED_PDF_BYTES} byte limit",
                    None,
                    None,
                )
            return True, compilation_time, "", page_count, cached_pdf

        record_compile("error", duration_seconds=_compile_duration)
        return False, compilation_time, f"{compiler} exited with code {proc.returncode}", None, None
    finally:
        # ``--rm`` handles an exited container.  Force-remove only when the
        # client process was interrupted before it reported an exit, avoiding a
        # redundant Docker CLI call on successful/nonzero completion.
        process_obj = locals().get("proc")
        if locals().get("container_name") and (
            process_obj is None or getattr(process_obj, "returncode", None) is None
        ):
            cleanup_docker_container(locals().get("container_name"))
        shutil.rmtree(job_dir, ignore_errors=True)
