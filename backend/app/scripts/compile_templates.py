"""
Batch-compile all active templates to PDF + PNG thumbnails, then upload to MinIO.

Idempotent: skips templates that already have both files in MinIO.

Usage (inside the backend container):
    python -m app.scripts.compile_templates

Or from the host:
    docker exec latexy-backend python -m app.scripts.compile_templates
"""

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Ensure backend/ is on sys.path
_backend = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend / ".env")
load_dotenv(_backend.parent / ".env")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.database.models import ResumeTemplate
from app.services import storage_service
from app.services.europecv import configure_europecv_latex, is_europecv_source
from app.services.latex_service import (
    engine_env,
    engine_output_error,
    engine_sandbox_flags,
    find_recorder_read_escape,
    native_engine_command,
)
from app.utils.bounded_io import MAX_COMPILED_PDF_BYTES, read_file_bounded


def _raise_if_failed(failed: int) -> None:
    """Make batch failures visible to Modal and CI callers."""
    if failed:
        raise RuntimeError(f"template asset generation failed for {failed} template(s)")


def _db_url() -> str:
    from app.utils.db_url import normalize_database_url
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return normalize_database_url(url)


def _prepare_template(latex_content: str) -> tuple[str, str]:
    """Return the source and engine used for a template asset.

    Template assets must follow the same default compiler contract as newly
    created resumes.  The real ``europecv`` class additionally needs its
    closed locale rewrite; using that helper avoids trying to infer Unicode
    support from arbitrary source text and keeps the asset source identical to
    the source users receive from the template route.
    """

    if is_europecv_source(latex_content):
        return configure_europecv_latex(latex_content, "en")
    return latex_content, settings.DEFAULT_NEW_RESUME_COMPILER


async def main():
    engine = create_async_engine(_db_url(), echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        templates = (
            await session.execute(
                select(ResumeTemplate).where(ResumeTemplate.is_active.is_(True))
            )
        ).scalars().all()

    print(f"Found {len(templates)} active templates")

    compiled = 0
    skipped = 0
    failed = 0

    try:
        for t in templates:
            try:
                png_key = f"templates/{t.id}.png"
                pdf_key = f"templates/{t.id}.pdf"

                if storage_service.file_exists(png_key) and storage_service.file_exists(pdf_key):
                    print(f"  SKIP  {t.name} (already compiled)")
                    skipped += 1
                    continue

                print(f"  COMPILE  {t.name} ... ", end="", flush=True)

                with tempfile.TemporaryDirectory() as tmpdir:
                    tex_path = Path(tmpdir) / "template.tex"
                    source, compiler = _prepare_template(t.latex_content)
                    tex_path.write_text(source, encoding="utf-8")

                    # Run the configured engine twice for references.
                    ok = True
                    for _pass in range(2):
                        result = subprocess.run(
                            native_engine_command(compiler, [
                                "-interaction=nonstopmode",
                                "-output-directory",
                                tmpdir,
                                *engine_sandbox_flags(compiler),
                                str(tex_path),
                            ], tmpdir),
                            # Diagnostics are read from the bounded .log below;
                            # never retain arbitrary compiler pipes in memory.
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=60,
                            cwd=tmpdir,
                            env=engine_env(tmpdir, compiler),
                        )
                        violation = find_recorder_read_escape(Path(tmpdir) / "template.fls", tmpdir, require_recorder=True)
                        if violation:
                            print(f"FAIL ({engine_output_error(violation)})")
                            ok = False
                            break
                        if result.returncode != 0 and _pass == 1:
                            print(f"FAIL ({compiler} exit {result.returncode})")
                            log_path = Path(tmpdir) / "template.log"
                            diagnostic = ""
                            if log_path.is_file():
                                bounded_log = read_file_bounded(log_path, 256 * 1024).decode(
                                    errors="replace"
                                )
                                diagnostic = "\n".join(
                                    line for line in bounded_log.splitlines()
                                    if line.startswith("!") or line.startswith("l.")
                                )[-1000:]
                            if diagnostic:
                                print(f"    diagnostics:\n{diagnostic}")
                            ok = False

                    if not ok:
                        failed += 1
                        continue

                    pdf_path = Path(tmpdir) / "template.pdf"
                    if not pdf_path.exists():
                        print("FAIL (no PDF produced)")
                        failed += 1
                        continue

                    # Upload PDF
                    storage_service.upload_bytes(
                        pdf_key,
                        read_file_bounded(pdf_path, MAX_COMPILED_PDF_BYTES),
                        "application/pdf",
                    )

                    # Convert first page to PNG
                    try:
                        from pdf2image import convert_from_path

                        images = convert_from_path(str(pdf_path), first_page=1, last_page=1, dpi=150)
                        if not images:
                            raise RuntimeError("PNG conversion returned no images")
                        import io
                        buf = io.BytesIO()
                        images[0].save(buf, format="PNG")
                        storage_service.upload_bytes(png_key, buf.getvalue(), "image/png")
                    except Exception as e:
                        print(f"FAIL (PDF ok, PNG failed: {e})")
                        failed += 1
                        continue

                    print("OK")
                    compiled += 1
            except Exception as e:
                print(f"ERROR ({e})")
                failed += 1
    finally:
        await engine.dispose()

    print(f"\nDone: {compiled} compiled, {skipped} skipped, {failed} failed")
    _raise_if_failed(failed)


if __name__ == "__main__":
    asyncio.run(main())
