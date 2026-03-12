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

from app.database.models import ResumeTemplate
from app.services import storage_service


def _db_url() -> str:
    from app.utils.db_url import normalize_database_url
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return normalize_database_url(url)


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
                    tex_path.write_text(t.latex_content, encoding="utf-8")

                    # Run pdflatex twice for references
                    ok = True
                    for _pass in range(2):
                        result = subprocess.run(
                            ["pdflatex", "-interaction=nonstopmode", "-output-directory", tmpdir, str(tex_path)],
                            capture_output=True,
                            timeout=60,
                        )
                        if result.returncode != 0 and _pass == 1:
                            print(f"FAIL (pdflatex exit {result.returncode})")
                            stderr = result.stderr.decode(errors="replace")[-500:] if result.stderr else ""
                            if stderr:
                                print(f"    stderr: {stderr}")
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
                    storage_service.upload_bytes(pdf_key, pdf_path.read_bytes(), "application/pdf")

                    # Convert first page to PNG
                    try:
                        from pdf2image import convert_from_path

                        images = convert_from_path(str(pdf_path), first_page=1, last_page=1, dpi=150)
                        if images:
                            import io
                            buf = io.BytesIO()
                            images[0].save(buf, format="PNG")
                            storage_service.upload_bytes(png_key, buf.getvalue(), "image/png")
                    except Exception as e:
                        print(f"WARN (PDF ok, PNG failed: {e})")
                        compiled += 1
                        continue

                    print("OK")
                    compiled += 1
            except Exception as e:
                print(f"ERROR ({e})")
                failed += 1
    finally:
        await engine.dispose()

    print(f"\nDone: {compiled} compiled, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    asyncio.run(main())
