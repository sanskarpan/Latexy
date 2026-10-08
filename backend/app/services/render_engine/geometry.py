"""Conservative semantic geometry from the actual rendered PDF.

Only a uniquely matched literal semantic node with a verified source span is
editable. Ambiguous text, rotations, missing extraction and opaque TeX remain
read-only. SyncTeX is not used as guessed semantic geometry.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ...utils.bounded_io import MAX_COMPILED_PDF_BYTES, read_file_bounded
from ...utils.process_watchdog import ProcessWatchdog

MAX_BBOX_BYTES = 16 * 1024 * 1024
MAX_WORDS = 100_000
MAX_NODES = 400


def _text(value: str) -> list[str]:
    return unicodedata.normalize("NFKC", value).split()


def project_boxes(xml: bytes, document: dict[str, Any], *, pdf_sha256: str, branch: str) -> dict[str, Any]:
    if len(xml) > MAX_BBOX_BYTES:
        raise ValueError("PDF geometry extraction exceeds limit")
    root = ET.fromstring(xml)
    pages = []
    blocks = []
    word_count = 0
    for number, page in enumerate(root.findall(".//{*}page"), start=1):
        width, height = float(page.attrib["width"]), float(page.attrib["height"])
        if not (0 < width <= 20_000 and 0 < height <= 20_000):
            raise ValueError("invalid PDF page geometry")
        pages.append({"page": number, "width": width, "height": height, "rotation": 0})
        if len(pages) > 1000:
            raise ValueError("PDF page count exceeds limit")
        for block in page.findall(".//{*}block"):
            words = []
            for line_number, line in enumerate(block.findall(".//{*}line")):
                for word in line.findall("{*}word"):
                    text = "".join(word.itertext())
                    tokens = _text(text)
                    # A single extracted glyph box must correspond to one token;
                    # splitting it into guessed character geometry is unsupported.
                    if len(tokens) != 1:
                        continue
                    x, y = float(word.attrib["xMin"]), float(word.attrib["yMin"])
                    x2, y2 = float(word.attrib["xMax"]), float(word.attrib["yMax"])
                    if not (0 <= x < x2 <= width + 1 and 0 <= y < y2 <= height + 1):
                        raise ValueError("invalid PDF word geometry")
                    words.append({"text": tokens[0], "page": number, "line": line_number, "x": x, "y": y, "x2": x2, "y2": y2})
                    word_count += 1
                    if word_count > MAX_WORDS:
                        raise ValueError("PDF word count exceeds limit")
            blocks.append(words)
    boxes, omissions = [], []
    nodes = document.get("nodes", [])
    if not isinstance(nodes, list) or len(nodes) > MAX_NODES:
        raise ValueError("semantic geometry node count exceeds limit")
    positions = {}
    for block_number, words in enumerate(blocks):
        for offset, word in enumerate(words):
            positions.setdefault(word["text"], []).append((block_number, offset))
    comparisons = 0
    deadline = time.monotonic() + 0.25
    for node in nodes:
        identity = node.get("node_id")
        span = node.get("source_span")
        if not node.get("editable") or not isinstance(span, dict):
            omissions.append({"node_id": identity, "reason": "opaque_or_unverified_source_span"})
            continue
        tokens = _text(node.get("text", ""))
        if not tokens:
            omissions.append({"node_id": identity, "reason": "empty_text"})
            continue
        matches = []
        exhausted = False
        for block_number, offset in positions.get(tokens[0], []):
            if comparisons >= 250_000 or time.monotonic() > deadline:
                exhausted = True
                break
            words = blocks[block_number]
            if offset + len(tokens) > len(words):
                continue
            matched = True
            for token_number, token in enumerate(tokens):
                comparisons += 1
                if comparisons >= 250_000:
                    exhausted = True
                    matched = False
                    break
                if words[offset + token_number]["text"] != token:
                    matched = False
                    break
            if matched:
                matches.append(words[offset:offset + len(tokens)])
                if len(matches) == 2:
                    break
        if exhausted:
            omissions.append({"node_id": identity, "reason": "geometry_budget_exceeded"})
            continue
        if len(matches) != 1:
            omissions.append({"node_id": identity, "reason": "ambiguous_pdf_text" if matches else "text_not_exactly_located"})
            continue
        grouped = {}
        for word in matches[0]:
            grouped.setdefault((word["page"], word["line"]), []).append(word)
        for words in grouped.values():
            x, y = min(word["x"] for word in words), min(word["y"] for word in words)
            x2, y2 = max(word["x2"] for word in words), max(word["y2"] for word in words)
            boxes.append({"node_id": identity, "node_revision": node["node_revision"], "kind": node.get("kind"), "text": node["text"], "source_span": span, "page": words[0]["page"], "x": x, "y": y, "width": x2 - x, "height": y2 - y})
    return {
        "schema_version": 1, "coordinate_system": "pdf_points_top_left",
        "source_sha256": document["source_sha256"], "pdf_sha256": pdf_sha256,
        "document_id": document.get("document_id"), "content_revision": document.get("content_revision"),
        "branch": branch, "pages": pages, "boxes": boxes, "omissions": omissions,
    }


def _capture(arguments: list[str], limit: int, deadline: float) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Geometry inspection deadline reached")
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    watchdog = ProcessWatchdog(process, timeout=remaining, is_cancelled=lambda: False)
    started = False
    output = bytearray()
    try:
        watchdog.start()
        started = True
        while True:
            chunk = process.stdout.read(65536)
            if not chunk:
                break
            if len(output) + len(chunk) > limit:
                raise ValueError("Geometry inspection output exceeds limit")
            output.extend(chunk)
        process.wait()
        if watchdog.reason or process.returncode:
            raise ValueError("Geometry inspection failed")
        return bytes(output)
    finally:
        if started:
            watchdog.stop()
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()


def extract_geometry(pdf_file: Path, document: dict[str, Any], *, pdf_sha256: str, branch: str) -> dict[str, Any] | None:
    if not shutil.which("pdftotext") or not shutil.which("pdfinfo"):
        return None
    pdf = read_file_bounded(pdf_file, MAX_COMPILED_PDF_BYTES)
    if hashlib.sha256(pdf).hexdigest() != pdf_sha256:
        return None
    # Poppler receives a private copy from the already validated no-follow
    # handle, so path replacement cannot redirect its subsequent reads.
    with tempfile.TemporaryDirectory(prefix="latexy-geometry-") as directory:
        pdf_file = Path(directory) / "document.pdf"
        pdf_file.write_bytes(pdf)
        deadline = time.monotonic() + 6
        # Poppler clamps a last-page request beyond the end of the document.
        # One bounded probe supplies both total count and every allowed page's
        # rotation; documents over the page cap still fail before text parsing.
        information = _capture(["pdfinfo", "-f", "1", "-l", "1000", str(pdf_file)],
                               256 * 1024, deadline).decode("utf-8", errors="replace")
        count_match = re.search(r"^Pages:\s*(\d+)", information, re.MULTILINE)
        if not count_match or not 0 < int(count_match[1]) <= 1000:
            return None
        page_count = int(count_match[1])
        rotations = re.findall(r"(?:Page(?:\s+\d+)?\s+rot|Page rot):\s*(-?\d+)", information)
        # Rotated documents require an engine-specific verified coordinate adapter.
        if len(rotations) != page_count or any(int(rotation) % 360 for rotation in rotations):
            return None
        xml = _capture(["pdftotext", "-bbox-layout", "-enc", "UTF-8", str(pdf_file), "-"], MAX_BBOX_BYTES, deadline)
        return project_boxes(xml, document, pdf_sha256=pdf_sha256, branch=branch)
