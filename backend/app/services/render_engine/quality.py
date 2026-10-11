"""Bounded checks on exact PDF bytes, independent of source-based ATS scores.

These diagnostics cannot prove visual quality or an ATS vendor's reading order.
They run after preview publication and never fetch hyperlink destinations.
"""
from __future__ import annotations

import hashlib
import math
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from ...utils.bounded_io import MAX_COMPILED_PDF_BYTES
from ...utils.process_watchdog import ProcessWatchdog

CheckStatus = Literal["checked", "partial", "unavailable"]


class PDFChecks(BaseModel):
    """Observed diagnostics have narrower scope than visual/ATS certification."""
    model_config = ConfigDict(extra="forbid", strict=True)
    page_count: CheckStatus = "unavailable"
    bounds: CheckStatus = "unavailable"
    text_size: CheckStatus = "unavailable"
    field_presence: CheckStatus = "unavailable"
    font_embedding: CheckStatus = "unavailable"
    links: CheckStatus = "unavailable"
    extraction_order: CheckStatus = "unavailable"
    line_spacing: CheckStatus = "unavailable"


class PDFQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    status: Literal["checked", "unavailable"]
    pdf_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_count: StrictInt | None = Field(default=None, ge=1, le=1000)
    word_count: StrictInt = Field(default=0, ge=0, le=100000)
    missing_field_count: StrictInt = Field(default=0, ge=0, le=400)
    embedded_font_count: StrictInt = Field(default=0, ge=0, le=10000)
    link_count: StrictInt = Field(default=0, ge=0, le=10000)
    checks: PDFChecks = Field(default_factory=PDFChecks)
    warnings: list[Annotated[str, Field(max_length=240)]] = Field(max_length=10)

    @field_validator("warnings")
    @classmethod
    def known_warnings(cls, values):
        if any(value not in MESSAGES.values() for value in values):
            raise ValueError("Unknown PDF review diagnostic")
        return values


MESSAGES = {
    "page_count": "The PDF exceeds two pages. Review its length before accepting changes.",
    "off_page": "Some extracted text extends beyond the page. Check the PDF for clipped content.",
    "small_text": "Some extracted text is unusually small. Check readability in the PDF.",
    "missing_fields": "Some resume fields could not be found exactly in extracted PDF text. Check that they remain readable.",
    "unembedded_fonts": "Some PDF fonts are not embedded. Appearance may vary between viewers.",
    "missing_links": "Some source hyperlinks are missing from PDF annotations. Check your contact links.",
    "extraction_order": "Extracted PDF fields differ from their source order. Check how the PDF reads when copied as text.",
    "line_overlap": "Some extracted text lines overlap vertically. Check line spacing in the PDF.",
    "unavailable": "PDF layout checks were unavailable. Review the displayed PDF before accepting changes.",
}


def inspect_boxes(xml: bytes, document: dict) -> dict:
    """Report observed boxes without guessing fields or certifying reading order."""
    if len(xml) > 16 * 1024 * 1024:
        raise ValueError("PDF text exceeds the review limit")
    root = ET.fromstring(xml)
    pages = root.findall(".//{*}page")
    if not 1 <= len(pages) <= 1000:
        raise ValueError("Invalid PDF page count")
    words, issues = [], []
    checks = PDFChecks(page_count="checked", bounds="checked", text_size="partial", field_presence="partial")
    observed_line_pairs = 0
    if len(pages) > 2:
        issues.append("page_count")
    for page in pages:
        width, height = float(page.attrib["width"]), float(page.attrib["height"])
        if not all(math.isfinite(n) and 0 < n <= 20000 for n in (width, height)):
            raise ValueError("Invalid PDF page size")
        for word in page.findall(".//{*}word"):
            x, y, x2, y2 = (float(word.attrib[key]) for key in ("xMin", "yMin", "xMax", "yMax"))
            if not all(math.isfinite(n) for n in (x, y, x2, y2)) or x2 <= x or y2 <= y:
                raise ValueError("Invalid PDF text box")
            if x < -1 or y < -1 or x2 > width + 1 or y2 > height + 1:
                issues.append("off_page")
            # Bounding-box height is a diagnostic, not the nominal font size.
            if y2 - y < 4:
                issues.append("small_text")
            words.extend(unicodedata.normalize("NFKC", "".join(word.itertext())).split())
            if len(words) > 100000:
                raise ValueError("PDF word budget exceeded")
        # Only independent lines within the same extracted block are compared.
        # Other blocks may intentionally sit side by side or contain decorations.
        for block in page.findall(".//{*}block"):
            line_bounds = []
            for line in block.findall("{*}line"):
                boxes = line.findall("{*}word")
                if boxes:
                    line_bounds.append((min(float(w.attrib["yMin"]) for w in boxes),
                                        max(float(w.attrib["yMax"]) for w in boxes)))
            for before, after in zip(line_bounds, line_bounds[1:]):
                observed_line_pairs += 1
                if before[0] <= after[0] < before[1] - 1:
                    issues.append("line_overlap")
    if observed_line_pairs:
        checks.line_spacing = "partial"  # glyph bounds do not prove nominal spacing/readability
    if not words:
        raise ValueError("PDF text extraction is empty")
    text = " " + " ".join(words) + " "
    nodes = document.get("nodes", [])
    if not isinstance(nodes, list) or len(nodes) > 400:
        raise ValueError("PDF field budget exceeded")
    missing = 0
    ordered_fields = []
    for node in nodes:
        span = node.get("source_span")
        if document.get("source_mode") == "managed" and not isinstance(span, dict):
            # Hidden sections and ambiguous source mappings are not known to be
            # rendered; absence must not masquerade as a lost visible field.
            continue
        field = " ".join(unicodedata.normalize("NFKC", node.get("text", "")).split())
        if len(field) > 4000:
            raise ValueError("PDF field exceeds limit")
        # Template punctuation can sit immediately after a field (degree,
        # company, etc.). Preserve symbol-bearing skills such as C++ while
        # accepting ordinary punctuation delimiters around the exact text.
        if field:
            matches = list(re.finditer(r"(?:^|[\s,;.:()!?])" + re.escape(field) + r"(?=$|[\s,;.:()!?])", text))
            if not matches:
                missing += 1
            if (len(matches) == 1 and document.get("source_mode") == "managed" and isinstance(span, dict)
                    and type(span.get("start")) is int and type(span.get("end")) is int
                    and 0 <= span["start"] < span["end"]):
                ordered_fields.append((span["start"], span["end"], matches[0].start()))
    # Check only unique, non-overlapping managed fields. This compares literal
    # extraction against deterministic source order, not an ATS vendor's order,
    # script-direction correctness, or a reconstructed arbitrary-PDF structure.
    candidates = sorted(ordered_fields)
    unambiguous = [field for index, field in enumerate(candidates)
                   if (index == 0 or candidates[index - 1][1] <= field[0])
                   and (index + 1 == len(candidates) or field[1] <= candidates[index + 1][0])]
    if len(unambiguous) >= 2:
        checks.extraction_order = "partial"
        if any(before[2] > after[2] for before, after in zip(unambiguous, unambiguous[1:])):
            issues.append("extraction_order")
    if missing:
        issues.append("missing_fields")
    return {"page_count": len(pages), "word_count": len(words), "missing_field_count": missing,
            "checks": checks.model_dump(), "warnings": [MESSAGES[key] for key in dict.fromkeys(issues)]}


def review_pdf(pdf: bytes | None, document: dict, source: str, *, timeout: float = 6) -> dict:
    """A shared deadline bounds all Poppler calls; failed checks stay explicit."""
    identity = {
        "pdf_sha256": hashlib.sha256(pdf or b"").hexdigest(),
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }
    unavailable = PDFQualityReport(status="unavailable", **identity, warnings=[MESSAGES["unavailable"]]).model_dump()
    if (not pdf or len(pdf) > MAX_COMPILED_PDF_BYTES or not pdf.startswith(b"%PDF-")
            or document.get("source_sha256") != identity["source_sha256"]
            or not all(shutil.which(tool) for tool in ("pdftotext", "pdffonts", "pdfinfo"))):
        return unavailable
    deadline = time.monotonic() + min(max(timeout, .1), 10)
    try:
        with tempfile.TemporaryDirectory(prefix="latexy-pdf-review-") as directory:
            root = Path(directory)
            path = root / "document.pdf"
            path.write_bytes(pdf)

            def run(arguments, limit):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("PDF review deadline reached")
                process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                watchdog = ProcessWatchdog(process, timeout=remaining, is_cancelled=lambda: False)
                monitoring = False
                output = bytearray()
                try:
                    watchdog.start()
                    monitoring = True
                    while True:
                        chunk = process.stdout.read(65536)
                        if not chunk:
                            break
                        if len(output) + len(chunk) > limit:
                            raise ValueError("PDF inspection output exceeds limit")
                        output.extend(chunk)
                    process.wait()
                    if watchdog.reason or process.returncode:
                        raise ValueError("PDF inspection failed")
                    return bytes(output)
                finally:
                    if monitoring:
                        watchdog.stop()
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    process.stdout.close()

            xml = run(["pdftotext", "-bbox-layout", "-enc", "UTF-8", str(path), "-"], 16 * 1024 * 1024)
            report = inspect_boxes(xml, document)
            fonts = run(["pdffonts", str(path)], 512 * 1024).decode("utf-8", "replace")
            entries = re.findall(r"\s+(yes|no)\s+(?:yes|no)\s+(?:yes|no)\s+\d+\s+\d+\s*$", fonts, re.M)
            if not entries or len(entries) > 10000:
                raise ValueError("PDF font inspection incomplete")
            report["embedded_font_count"] = entries.count("yes")
            report["checks"]["font_embedding"] = "checked"
            if "no" in entries:
                report["warnings"].append(MESSAGES["unembedded_fonts"])
            annotations = run(["pdfinfo", "-url", str(path)], 512 * 1024).decode("utf-8", "replace")
            links = set(re.findall(r"(?:https?://|mailto:)[^\s]+", annotations))
            if len(links) > 10000:
                raise ValueError("PDF link inspection exceeds limit")
            report["link_count"] = len(links)
            report["checks"]["links"] = "partial"  # literal source hrefs; no destination fetch or link health claim
            expected = set()
            for link in re.findall(r"\\href\{([^{}]{1,2048})\}", source):
                link = re.sub(r"\\([%_&#$])", r"\1", link)
                if re.match(r"(?:https?://|mailto:)", link) and not re.search(r"[\s\\]", link):
                    expected.add(link)
            if len(expected) > 64:
                raise ValueError("Source link review exceeds limit")
            if expected - links:
                report["warnings"].append(MESSAGES["missing_links"])
            return PDFQualityReport(status="checked", **identity, **report).model_dump()
    except (OSError, ValueError, ET.ParseError, TimeoutError, RuntimeError, subprocess.TimeoutExpired):
        return unavailable
