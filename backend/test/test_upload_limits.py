import io

import pytest
from fastapi import HTTPException, UploadFile

from app.utils.file_utils import read_upload_capped


@pytest.mark.asyncio
async def test_read_upload_capped_accepts_exact_limit_without_size_metadata():
    upload = UploadFile(filename="resume.txt", file=io.BytesIO(b"a" * 8), size=None)

    assert await read_upload_capped(upload, 8) == b"a" * 8


@pytest.mark.asyncio
async def test_read_upload_capped_rejects_stream_over_limit_without_size_metadata():
    upload = UploadFile(filename="resume.txt", file=io.BytesIO(b"a" * 9), size=None)

    with pytest.raises(HTTPException) as exc_info:
        await read_upload_capped(upload, 8)

    assert exc_info.value.status_code == 413
