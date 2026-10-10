"""Verify actually selected image assets against ordinary native pdflatex.

This is correctness certification, not a latency benchmark. Original sources
retain every line; compare all source-addressed SyncTeX records and rendered
text/page pixels for different managed document bodies.
"""
import argparse
import copy
import json
import tempfile
from pathlib import Path

from app.services.render_engine.trusted_profiles import trusted_format_identity
from app.services.resume_builder_service import resume_builder_service
from scripts.benchmark_trusted_format import FIXTURE, digest, render


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = {"schema_version": 1, "scope": "image-built runtime selected profile correctness; no latency SLO claim", "variants": []}
    try:
        with tempfile.TemporaryDirectory(prefix="latexy-profile-proof-") as temporary:
            root = Path(temporary)
            for number, category in enumerate(("ats_safe", "executive", "graduate")):
                fixture = copy.deepcopy(FIXTURE)
                fixture["basics"]["name"] = "Avery Example " + str(number + 1)
                fixture["basics"]["summary"] += " Tested static profile body variant " + str(number + 1) + "."
                fixture["experience"][0]["bullets"].append("Validated document references and consistent text geometry across revisions.")
                source = resume_builder_service.render(fixture, category).latex_content
                profile = trusted_format_identity(source, "pdflatex")
                if not profile:
                    raise RuntimeError("Runtime did not select verified installed assets")
                default = render(root / f"{number}-ordinary", source, None)
                installed = render(root / f"{number}-installed", source, "installed")
                for key in ("page_count", "text_sha256", "pixel_sha256", "geometry_sha256", "synctex_source_records_sha256", "synctex_view_coordinates"):
                    if default[key] != installed[key]:
                        raise RuntimeError("Installed profile changed " + key)
                evidence["variants"].append({"category": category, "source_sha256": digest(source.encode()),
                    "profile_identity": profile["identity_sha256"], "format_sha256": profile["format_sha256"],
                    "page_count": installed["page_count"], "source_record_count": installed["synctex_source_records"],
                    "text_sha256": installed["text_sha256"], "pixel_sha256": installed["pixel_sha256"],
                    "geometry_sha256": installed["geometry_sha256"],
                    "synctex_source_records_sha256": installed["synctex_source_records_sha256"], "equivalent": True})
            evidence["passed"] = True
    except Exception as exc:
        evidence["passed"] = False
        evidence["error"] = str(exc)
    args.output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if not evidence["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
