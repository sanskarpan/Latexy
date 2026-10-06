"""Exact-PDF diagnostics must expose clipping and never certify failed inspection."""
from hashlib import sha256
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.services.render_engine import quality


def xml(word="Readable", *, x=10, x2=70, height=11):
    return (f'<html><page width="100" height="200"><word xMin="{x}" yMin="10" '
            f'xMax="{x2}" yMax="{10 + height}">{word}</word></page></html>').encode()


def test_clipped_text_and_missing_field_are_reported_separately():
    report = quality.inspect_boxes(xml(x2=130), {"nodes": [{"text": "Readable"}, {"text": "Lost label"}]})
    assert report["missing_field_count"] == 1
    assert report["warnings"] == [quality.MESSAGES["off_page"], quality.MESSAGES["missing_fields"]]


@pytest.mark.parametrize("x2", ["nan", "inf", 9])
def test_invalid_pdf_geometry_never_passes(x2):
    with pytest.raises(ValueError):
        quality.inspect_boxes(xml(x2=x2), {"nodes": []})


def test_ligature_normalization_and_readability_diagnostic():
    report = quality.inspect_boxes(xml("ﬁrm", height=3), {"nodes": [{"text": "firm"}]})
    assert report["missing_field_count"] == 0
    assert report["warnings"] == [quality.MESSAGES["small_text"]]


def test_template_punctuation_is_not_a_missing_field_but_skill_symbols_stay_distinct():
    report = quality.inspect_boxes(xml("Engineering,"), {"nodes": [{"text": "Engineering"}]})
    assert report["missing_field_count"] == 0
    report = quality.inspect_boxes(xml("C++"), {"nodes": [{"text": "C"}]})
    assert report["missing_field_count"] == 1


def test_managed_hidden_or_ambiguous_fields_are_not_reported_as_lost():
    report = quality.inspect_boxes(xml(), {"source_mode": "managed", "nodes": [
        {"text": "Readable", "source_span": {"start": 0, "end": 8}},
        {"text": "Hidden field", "source_span": None},
    ]})
    assert report["missing_field_count"] == 0 and not report["warnings"]
    assert report["checks"]["field_presence"] == "partial"


def test_managed_extraction_order_checks_only_unique_source_fields():
    document = {"source_mode": "managed", "nodes": [
        {"text": "First", "source_span": {"start": 10, "end": 15}},
        {"text": "Second", "source_span": {"start": 30, "end": 36}},
    ]}
    report = quality.inspect_boxes(xml("Second First"), document)
    assert report["checks"]["extraction_order"] == "partial"
    assert quality.MESSAGES["extraction_order"] in report["warnings"]
    report = quality.inspect_boxes(xml("First Second"), document)
    assert quality.MESSAGES["extraction_order"] not in report["warnings"]
    report = quality.inspect_boxes(xml("First Second First"), document)
    assert report["checks"]["extraction_order"] == "unavailable"


def test_observed_overlapping_lines_remain_a_partial_spacing_diagnostic():
    value = b'''<html><page width="100" height="200"><block>
    <line><word xMin="10" yMin="10" xMax="30" yMax="20">First</word></line>
    <line><word xMin="10" yMin="17" xMax="30" yMax="27">Second</word></line>
    </block></page></html>'''
    report = quality.inspect_boxes(value, {"nodes": []})
    assert report["checks"]["line_spacing"] == "partial"
    assert quality.MESSAGES["line_overlap"] in report["warnings"]
    assert report["checks"]["extraction_order"] == "unavailable"


def test_missing_inspector_or_source_mismatch_is_explicit_and_spawns_nothing(monkeypatch):
    process = Mock()
    monkeypatch.setattr(quality.subprocess, "Popen", process)
    monkeypatch.setattr(quality.shutil, "which", lambda _: None)
    report = quality.review_pdf(b"%PDF-test", {"source_sha256": sha256(b"source").hexdigest()}, "source")
    assert report["status"] == "unavailable" and report["warnings"]
    assert all(value == "unavailable" for value in report["checks"].values())
    process.assert_not_called()
    monkeypatch.setattr(quality.shutil, "which", lambda tool: "/usr/bin/" + tool)
    report = quality.review_pdf(b"%PDF-test", {"source_sha256": "0" * 64}, "source")
    assert report["status"] == "unavailable"
    process.assert_not_called()


def test_untrusted_warning_text_is_not_a_durable_report():
    with pytest.raises(ValidationError):
        quality.PDFQualityReport(status="checked", pdf_sha256="0" * 64, source_sha256="1" * 64,
                                 warnings=["provider key or arbitrary diagnostics"])


@pytest.mark.parametrize("changed", [None, "pdf_sha256", "source_sha256"])
def test_durable_review_cannot_attach_to_different_artifact(changed):
    from app.workers.finalization_arbiter import bounded_result_payload

    artifact = {"artifact_id": "a" * 64, "source_sha256": "b" * 64,
                "render_source_sha256": "b" * 64, "pdf_sha256": "c" * 64,
                "settings_sha256": "d" * 64, "pdf_size": 123, "owner_epoch": 1,
                "branch": "candidate", "compiler": "pdflatex", "preview_url": "/download/job/preview"}
    report = quality.PDFQualityReport(status="checked", pdf_sha256="c" * 64,
                                     source_sha256="b" * 64, warnings=[]).model_dump()
    if changed:
        report[changed] = "e" * 64
    result = bounded_result_payload("job", {"success": True, "artifact": artifact, "pdf_quality": report})
    assert ("pdf_quality" in result) is (changed is None)
