import base64
import io
import shutil
import subprocess

import pytest
from PIL import Image

from app.services.cover_letter_signature_service import (
    SIGNATURE_DATA_PREFIX,
    SIGNATURE_END,
    SIGNATURE_FILENAME,
    SIGNATURE_START,
    InvalidSignatureImage,
    materialize_embedded_signature,
    normalize_embedded_signature,
)


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (80, 24), (0, 0, 0, 0)).save(output, format="PNG")
    return output.getvalue()


def _source(payload: str) -> str:
    chunks = "\n".join(f"{SIGNATURE_DATA_PREFIX}{payload[i : i + 40]}" for i in range(0, len(payload), 40))
    return (
        f"\\documentclass{{article}}\n{SIGNATURE_START}\n{chunks}\n"
        f"\\includegraphics{{{SIGNATURE_FILENAME}}}\n{SIGNATURE_END}\n"
    )


def test_signature_image_is_normalized_and_materialized(tmp_path):
    source = _source(base64.b64encode(_png()).decode("ascii"))
    normalized = normalize_embedded_signature(source)
    assert normalized is not None and normalized.startswith(b"\x89PNG")
    assert materialize_embedded_signature(source, tmp_path) is True
    assert (tmp_path / SIGNATURE_FILENAME).read_bytes() == normalized


def test_source_without_signature_needs_no_asset(tmp_path):
    assert normalize_embedded_signature("\\documentclass{article}") is None
    assert materialize_embedded_signature("\\documentclass{article}", tmp_path) is False


def test_materialized_signature_compiles_with_pdftex(tmp_path):
    pdflatex = shutil.which("pdflatex")
    if pdflatex is None:
        pytest.skip("pdflatex is not installed")
    payload = base64.b64encode(_png()).decode("ascii")
    chunks = "\n".join(f"{SIGNATURE_DATA_PREFIX}{payload[i : i + 40]}" for i in range(0, len(payload), 40))
    source = (
        "\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\n"
        f"Signed below.\n{SIGNATURE_START}\n{chunks}\n"
        f"\\includegraphics[height=1cm]{{{SIGNATURE_FILENAME}}}\n{SIGNATURE_END}\n"
        "\\end{document}\n"
    )
    (tmp_path / "letter.tex").write_text(source, encoding="utf-8")
    materialize_embedded_signature(source, tmp_path)
    result = subprocess.run(
        [pdflatex, "-interaction=nonstopmode", "-halt-on-error", "letter.tex"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert (tmp_path / "letter.pdf").stat().st_size > 0


@pytest.mark.parametrize("payload", ["not-base64!", base64.b64encode(b"not an image").decode("ascii")])
def test_malformed_signature_is_rejected(payload):
    with pytest.raises(InvalidSignatureImage):
        normalize_embedded_signature(_source(payload))


@pytest.mark.parametrize(
    "source",
    [
        f"{SIGNATURE_START}\n{SIGNATURE_DATA_PREFIX}AAAA",
        f"{SIGNATURE_START}\n{SIGNATURE_END}\n{SIGNATURE_START}\n{SIGNATURE_END}",
        f"{SIGNATURE_START}\n\\includegraphics{{{SIGNATURE_FILENAME}}}\n{SIGNATURE_END}",
        f"\\includegraphics{{{SIGNATURE_FILENAME}}}",
    ],
)
def test_ambiguous_or_incomplete_signature_markers_are_rejected(source):
    with pytest.raises(InvalidSignatureImage):
        normalize_embedded_signature(source)
