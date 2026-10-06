"""Conservative semantic geometry from the actual rendered PDF.

Only a uniquely matched literal semantic node with a verified source span is
editable. Ambiguous text, rotations, missing extraction and opaque TeX remain
read-only. SyncTeX is not used as guessed semantic geometry.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ...utils.bounded_io import read_file_bounded

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


def extract_geometry(pdf_file: Path, document: dict[str, Any], *, pdf_sha256: str, branch: str) -> dict[str, Any] | None:
    if not shutil.which("pdftotext") or not shutil.which("pdfinfo"):
        return None
    with tempfile.TemporaryDirectory(prefix="latexy-geometry-") as directory:
        info_path = Path(directory) / "info.txt"
        # File-backed bounded diagnostics avoid retaining untrusted subprocess
        # stdout in an unlimited PIPE. No extraction output enters logs.
        with info_path.open("wb") as info:
            result = subprocess.run(["pdfinfo", str(pdf_file)], stdout=info, stderr=subprocess.DEVNULL, timeout=3, check=False)
        if result.returncode:
            return None
        information = read_file_bounded(info_path, 64 * 1024).decode("utf-8", errors="replace")
        count_match = re.search(r"^Pages:\s*(\d+)", information, re.MULTILINE)
        if not count_match or not 0 < int(count_match[1]) <= 1000:
            return None
        page_count = int(count_match[1])
        with info_path.open("wb") as info:
            result = subprocess.run(["pdfinfo", "-f", "1", "-l", str(page_count), str(pdf_file)], stdout=info, stderr=subprocess.DEVNULL, timeout=3, check=False)
        if result.returncode:
            return None
        information = read_file_bounded(info_path, 256 * 1024).decode("utf-8", errors="replace")
        rotations = re.findall(r"(?:Page(?:\s+\d+)?\s+rot|Page rot):\s*(-?\d+)", information)
        # Rotated documents require an engine-specific verified coordinate adapter.
        if len(rotations) != page_count or any(int(rotation) % 360 for rotation in rotations):
            return None
        xml_path = Path(directory) / "geometry.xhtml"
        result = subprocess.run(["pdftotext", "-bbox-layout", "-enc", "UTF-8", str(pdf_file), str(xml_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
        if result.returncode or not xml_path.exists():
            return None
        return project_boxes(read_file_bounded(xml_path, MAX_BBOX_BYTES), document, pdf_sha256=pdf_sha256, branch=branch)
