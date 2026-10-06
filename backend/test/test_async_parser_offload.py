import io
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.parsers.docx_parser import DOCXParser
from app.parsers.image_parser import ImageParser
from app.parsers.pdf_parser import PDFParser


@pytest.mark.asyncio
@pytest.mark.parametrize("parser_type", [DOCXParser, ImageParser, PDFParser])
async def test_cpu_heavy_document_parser_runs_outside_event_loop(parser_type):
    parser = parser_type()
    parsed = MagicMock()

    async def run_inline(function, *args):
        return function(*args)

    with (
        patch.object(parser, "_parse_sync", return_value=parsed) as parse_sync,
        patch("asyncio.to_thread", new=AsyncMock(side_effect=run_inline)) as to_thread,
    ):
        result = await parser.parse(b"document", "resume.bin")

    assert result is parsed
    to_thread.assert_awaited_once()
    parse_sync.assert_called_once_with(b"document", "resume.bin")


def test_docx_parser_rejects_excessive_uncompressed_archive(monkeypatch):
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"123456789")

    monkeypatch.setattr("app.parsers.docx_parser.MAX_DOCX_UNCOMPRESSED_BYTES", 8)

    with pytest.raises(ValueError, match="expands beyond"):
        DOCXParser._validate_archive(archive_bytes.getvalue())
