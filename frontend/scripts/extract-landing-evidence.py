"""Publish a small set of unchanged landing PNGs from Playwright's HTML report."""

import base64
import hashlib
import io
import json
import os
import re
import shutil
import struct
import sys
import zipfile
from pathlib import Path

report_dir = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2]).resolve()
destination.mkdir(parents=True, exist_ok=True)
html = (report_dir / "index.html").read_text(encoding="utf-8")
match = re.search(
    r'<template id="playwrightReportBase64">data:application/zip;base64,([^<]+)</template>',
    html,
)
if not match:
    raise SystemExit("Embedded Playwright report not found")
report = zipfile.ZipFile(io.BytesIO(base64.b64decode(match.group(1))))
manifest = {
    "sourceCommit": os.environ.get("LANDING_SOURCE_COMMIT"),
    "testedMergeCommit": os.environ.get("GITHUB_SHA"),
    "workflowRun": os.environ.get("GITHUB_RUN_ID"),
    "stats": json.loads(report.read("report.json"))["stats"],
    "files": {},
}
wanted = {
    "landing-page", "landing-page-dark",
    *{f"landing-{theme}-lp-{section}" for theme in ("light", "dark")
      for section in ("hero", "gallery", "footer")},
    *{f"mobile-{width}-{theme}-first-screen" for width in (320, 390, 430)
      for theme in ("light", "dark")},
    # Current Review Desk quality evidence: whole page + hero at representative
    # widths, and the native phone interaction states in both themes.
    *{f"review-{kind}-{width}-{theme}" for kind in ("desk", "hero")
      for width in (1440, 390, 320) for theme in ("light", "dark")},
    *{f"review-phone-{theme}-{stage}" for theme in ("light", "dark")
      for stage in ("write", "review", "tailor", "export")},
}
titles = {
    # Preserve the original evidence contracts for older report shapes.
    "representative public surface produces non-empty visual evidence",
    "mobile landing presents focused demos in both themes and preserves edits",
    # Names in public-quality.spec.ts at the current PR head.
    "landing review desk produces desktop and phone evidence in both themes",
    "landing phone stages retain edits and usable controls in both themes",
}


def walk(value, project=""):
    if isinstance(value, dict):
        project = value.get("projectName", project)
        if value.get("title") in titles and project in {"desktop-chromium", "mobile-chromium"}:
            for result in value.get("results", []):
                if result.get("status") != "passed":
                    continue
                for attachment in result.get("attachments", []):
                    name, path = attachment.get("name"), attachment.get("path")
                    if name not in wanted or not path:
                        continue
                    source = (report_dir / path).resolve()
                    if not source.is_relative_to(report_dir):
                        raise ValueError("Attachment path escapes the report")
                    target = destination / f"{project}-{name}.png"
                    shutil.copyfile(source, target)
                    data = target.read_bytes()
                    if data[:8] != b"\x89PNG\r\n\x1a\n":
                        raise ValueError(f"Expected PNG: {source.name}")
                    manifest["files"][target.name] = {
                        "attachment": name,
                        "project": project,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "pixels": struct.unpack(">II", data[16:24]),
                    }
        for child in value.values():
            walk(child, project)
    elif isinstance(value, list):
        for child in value:
            walk(child, project)


for filename in report.namelist():
    if filename.endswith(".json"):
        walk(json.loads(report.read(filename)))

if not manifest["files"]:
    raise SystemExit("Expected landing screenshots, but no evidence files were extracted")

(destination / "capture.json").write_text(
    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps({"images": len(manifest["files"]), "stats": manifest["stats"]}))
