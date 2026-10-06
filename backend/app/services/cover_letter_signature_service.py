"""Validate and materialize self-contained cover-letter signature images."""

import base64
import binascii
import io
import re
from pathlib import Path

from PIL import Image, UnidentifiedImageError

SIGNATURE_START = "% LATEXY_SIGNATURE_START"
SIGNATURE_END = "% LATEXY_SIGNATURE_END"
SIGNATURE_DATA_PREFIX = "% LATEXY_SIGNATURE_DATA:"
SIGNATURE_FILENAME = "latexy-signature.png"
MAX_SIGNATURE_BYTES = 512_000
MAX_SIGNATURE_PIXELS = 4_000_000

_BLOCK_RE = re.compile(
    rf"{re.escape(SIGNATURE_START)}(?P<body>.*?){re.escape(SIGNATURE_END)}",
    re.DOTALL,
)


class InvalidSignatureImage(ValueError):
    """Raised when an embedded signature is malformed or unsafe."""


def _embedded_payload(latex_content: str) -> str | None:
    start_count = latex_content.count(SIGNATURE_START)
    end_count = latex_content.count(SIGNATURE_END)
    data_count = latex_content.count(SIGNATURE_DATA_PREFIX)
    references_asset = SIGNATURE_FILENAME in latex_content
    if start_count == end_count == 0:
        if data_count or references_asset:
            raise InvalidSignatureImage("Signature image data must be inside one complete signature block")
        return None
    if start_count != 1 or end_count != 1:
        raise InvalidSignatureImage("Cover letters may contain only one complete signature block")
    match = _BLOCK_RE.search(latex_content)
    if match is None:
        raise InvalidSignatureImage("Signature block markers are incomplete")
    chunks = []
    for line in match.group("body").splitlines():
        stripped = line.strip()
        if stripped.startswith(SIGNATURE_DATA_PREFIX):
            chunks.append(stripped.removeprefix(SIGNATURE_DATA_PREFIX).strip())
    payload = "".join(chunks) or None
    block_references_asset = SIGNATURE_FILENAME in match.group("body")
    if data_count != match.group("body").count(SIGNATURE_DATA_PREFIX) or (
        references_asset and not block_references_asset
    ):
        raise InvalidSignatureImage("Signature image data must remain inside the signature block")
    if block_references_asset and payload is None:
        raise InvalidSignatureImage("Signature image data is missing")
    if payload is not None and not block_references_asset:
        raise InvalidSignatureImage("Signature image is not referenced by the signature block")
    return payload


def normalize_embedded_signature(latex_content: str) -> bytes | None:
    """Return a metadata-free PNG for the optional embedded signature block."""
    payload = _embedded_payload(latex_content)
    if payload is None:
        return None
    if len(payload) > ((MAX_SIGNATURE_BYTES + 2) // 3) * 4 + 8:
        raise InvalidSignatureImage("Embedded signature image is too large")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidSignatureImage("Embedded signature image is not valid base64") from exc
    if not raw or len(raw) > MAX_SIGNATURE_BYTES:
        raise InvalidSignatureImage("Embedded signature image is empty or too large")

    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise InvalidSignatureImage("Signature must be a PNG, JPEG, or WebP image")
            width, height = image.size
            if width < 2 or height < 2 or width * height > MAX_SIGNATURE_PIXELS:
                raise InvalidSignatureImage("Signature image dimensions are invalid")
            if getattr(image, "n_frames", 1) != 1:
                raise InvalidSignatureImage("Animated signature images are not supported")
            image.load()
            normalized = image.convert("RGBA")
            output = io.BytesIO()
            normalized.save(output, format="PNG", optimize=True)
    except InvalidSignatureImage:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidSignatureImage("Embedded signature is not a valid image") from exc

    result = output.getvalue()
    if len(result) > MAX_SIGNATURE_BYTES:
        raise InvalidSignatureImage("Normalized signature image is too large")
    return result


def validate_embedded_signature(latex_content: str) -> None:
    """Validate a signature marker, when present, before a job is charged."""
    normalize_embedded_signature(latex_content)


def materialize_embedded_signature(latex_content: str, work_dir: Path) -> bool:
    """Write the validated image beside the TeX source for ``includegraphics``."""
    image = normalize_embedded_signature(latex_content)
    if image is None:
        return False
    (work_dir / SIGNATURE_FILENAME).write_bytes(image)
    return True
