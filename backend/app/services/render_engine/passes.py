"""Deadline-bound cross-reference and restricted classic BibTeX convergence."""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any

from ...utils.bounded_io import BoundedTranscript, iter_bounded_lines, read_file_bounded
from ...utils.process_watchdog import ProcessWatchdog
from ..latex_service import (
    ENGINE_READ_ESCAPE_ERROR,
    cleanup_docker_container,
    engine_env,
    find_engine_read_escape,
    find_recorder_read_escape,
    latex_service,
)

_RERUN = re.compile(r"Rerun to get|Label\(s\) may have changed|There were undefined references|rerunfilecheck.*Warning", re.I)
_BIBSTYLE = re.compile(r"\\bibstyle\{(plain|unsrt|abbrv|alpha|apalike|ieeetr)\}")
_CITATION = re.compile(r"\\citation\{([A-Za-z0-9_:.,*+-]{1,4096})\}")
_PAGES = re.compile(r"Output written on .*?\((\d+) pages?", re.I)


class RenderPassError(ValueError):
    pass


def converge(*, job_id: str, job_dir: Path, command: list[str], cwd: str | None,
             workspace: str, compiler: str, timeout: float, started_at: float,
             transcript: BoundedTranscript, is_cancelled: Any, publisher: Any,
             container_name: str | None, force_second_pass: bool = False) -> int | None:
    """First pass already passed confinement. Reuse its isolated auxiliary files.

    Every extra TeX pass keeps synchronous read confinement, bounded transport,
    silent-process watchdog and recorder validation. Three TeX passes maximum;
    classic bibliography permits one explicitly constrained BibTeX invocation.
    """
    def run(cmd: list[str], *, tex: bool) -> tuple[str, int | None]:
        remaining = timeout - (time.time() - started_at)
        if remaining <= 0:
            raise RenderPassError("compile_timeout")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                cwd=cwd, env=engine_env(job_dir, compiler))
        from .process_timing import ProcessTiming

        process_timing = ProcessTiming(proc)
        watchdog = ProcessWatchdog(proc, timeout=remaining, is_cancelled=is_cancelled).start()
        output = BoundedTranscript()
        pages = None
        try:
            # Import only at execution time: workers.__init__ eagerly loads
            # Celery tasks which themselves import RenderPassError.
            from ...workers.buffered_events import BufferedEventPublisher

            with BufferedEventPublisher(job_id, publisher=publisher) as events:
                for line in iter_bounded_lines(proc.stdout):
                    if tex and find_engine_read_escape(line, workspace):
                        raise RenderPassError(ENGINE_READ_ESCAPE_ERROR)
                    bounded = output.append(line)
                    transcript.append(line)
                    if compiler != "lualatex" and tex:
                        events.publish("log.line", {"line": bounded, "source": compiler,
                                                   "is_error": line.startswith("!")})
                    matched = _PAGES.search(line)
                    if matched:
                        pages = int(matched[1])
            proc.wait()
            process_timing.finish()
            if watchdog.reason:
                raise RenderPassError("cancelled" if watchdog.reason == "cancelled" else "compile_timeout")
            if tex and find_recorder_read_escape(job_dir / "resume.fls", workspace, require_recorder=True):
                raise RenderPassError(ENGINE_READ_ESCAPE_ERROR)
            if compiler == "lualatex" and tex:
                from .log_gating import publish_verified_log

                publish_verified_log(job_id, output, compiler, publisher)
            if proc.returncode:
                raise RenderPassError("Auxiliary compiler pass failed")
            return output.text(), pages
        finally:
            watchdog.stop()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
                cleanup_docker_container(container_name)
            if proc.stdout is not None:
                proc.stdout.close()

    log = transcript.text()
    aux_path = job_dir / "resume.aux"
    aux = read_file_bounded(aux_path, 256 * 1024).decode("utf-8", errors="replace") if aux_path.exists() else ""
    if (job_dir / "resume.bcf").exists() or "Please (re)run Biber" in log:
        raise RenderPassError("Biber bibliography requires an unsupported isolated datasource adapter")
    bibliography = "\\bibdata{" in aux
    if bibliography:
        style = _BIBSTYLE.search(aux)
        if (not style or "\\bibdata{references}" not in aux
                or len(re.findall(r"\\bibdata\{", aux)) != 1
                or len(re.findall(r"\\bibstyle\{", aux)) != 1):
            raise RenderPassError("Bibliography uses an unsupported file or style")
        if not (job_dir / "references.bib").is_file():
            raise RenderPassError("Bibliography reference library is missing")
        # BibTeX input is regenerated from a closed grammar rather than reading
        # executable or nested aux paths emitted by arbitrary user macros.
        citations = _CITATION.findall(aux)
        safe_aux = "\\relax\n" + "".join(f"\\citation{{{item}}}\n" for item in citations[:400])
        safe_aux += "\\bibstyle{" + style[1] + "}\n\\bibdata{references}\n"
        aux_path.write_text(safe_aux, encoding="utf-8")
        try:
            index = command.index(compiler)
        except ValueError as exc:
            raise RenderPassError("Invalid bibliography engine command") from exc
        bibliography_log, _ = run(command[:index] + ["bibtex", "-min-crossrefs=999", "resume"], tex=False)
        bbl = read_file_bounded(job_dir / "resume.bbl", 256 * 1024).decode("utf-8", errors="strict")
        wrapped = r"\documentclass{article}\begin{document}" + bbl + r"\end{document}"
        if not latex_service.validate_latex_content(wrapped):
            raise RenderPassError("Bibliography contains unsafe LaTeX")
        from .log_gating import publish_verified_log

        verified_bibtex = BoundedTranscript()
        for line in bibliography_log.splitlines():
            verified_bibtex.append(line)
        publish_verified_log(job_id, verified_bibtex, "bibtex", publisher)
    pages = None
    rerun = bibliography or force_second_pass or bool(_RERUN.search(log))
    for pass_number in (2, 3):
        if not rerun:
            break
        log, pages = run(command, tex=True)
        rerun = bool(_RERUN.search(log)) or (bibliography and pass_number == 2)
    if rerun:
        raise RenderPassError("Cross-references did not converge within three TeX passes")
    return pages
