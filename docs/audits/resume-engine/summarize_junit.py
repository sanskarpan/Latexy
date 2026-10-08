"""Record counts, failed/skipped node IDs and hashes without captured private logs.

Usage: python summarize_junit.py --output report.json path/to/report.xml ...
Source provenance and harness boundaries must be supplied in the companion audit.
Overlapping suite counts must not be added into a unique-test total.
"""
import argparse
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree


def summarize(path: Path) -> dict:
    raw = path.read_bytes()
    root = ElementTree.fromstring(raw)
    cases = list(root.iter("testcase"))
    failed, errors, skipped = [], [], []
    for case in cases:
        node = case.get("classname", "") + "::" + case.get("name", "")
        if case.find("failure") is not None:
            failed.append(node)
        if case.find("error") is not None:
            errors.append(node)
        if case.find("skipped") is not None:
            skipped.append(node)
    suites = list(root.iter("testsuite"))
    return {"file": path.name, "sha256": hashlib.sha256(raw).hexdigest(),
            "tests": len(cases), "passed": len(cases) - len(failed) - len(errors) - len(skipped),
            "failed": failed, "errors": errors, "skipped": skipped,
            "suite_seconds": sum(float(suite.get("time", "0")) for suite in suites)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("reports", type=Path, nargs="+")
    args = parser.parse_args()
    args.output.write_text(json.dumps({"schema_version": 1,
        "scope": "Overlapping isolated local suites; source and exclusions in release-audit-2026-10-08.md",
        "reports": [summarize(path) for path in args.reports]}, indent=2) + "\n", encoding="utf-8")
