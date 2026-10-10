"""The actual guest seed must remain editable by the shipped engine protocol."""

import re
from pathlib import Path

import pytest

from app.api.resume_engine_routes import GuestDocument, GuestPatch, patch_guest, project_guest
from app.services.resume_engine.document import digest

ROOT = Path(__file__).resolve().parents[2]


def guest_seed():
    module = (ROOT / "frontend/src/lib/first-use-resume.ts").read_text()
    match = re.search(r"export const FIRST_USE_ENGINE_RESUME_TEMPLATE = String\.raw`([^`]*)`", module)
    assert match, "The engine seed must be a reviewable literal, not an untested conversion"
    page = (ROOT / "frontend/src/app/try/page.tsx").read_text()
    assert "FIRST_USE_ENGINE_RESUME_TEMPLATE as DEMO_RESUME_TEMPLATE" in page
    return match.group(1)


@pytest.mark.asyncio
async def test_actual_guest_seed_projects_core_fields_and_bullets():
    source = guest_seed()
    projected = await project_guest(GuestDocument(latex_content=source))
    nodes = projected["document"]["nodes"]
    texts = {node["text"] for node in nodes if node["editable"]}
    assert "Alex Morgan" in texts
    assert "Customer Success Associate" in texts
    assert "alex@example.com | London | linkedin.com/in/alexmorgan" in texts
    assert any(node["section"] == "summary" and node["editable"] for node in nodes)
    assert any(node["section"] == "skills" and node["editable"] for node in nodes)
    bullets = [node for node in nodes if node["kind"] == "bullet" and node["editable"]]
    assert len(bullets) == 3
    assert all(not node["ai_editable"] for node in nodes)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["name", "contact", "summary", "skills", "bullet"])
async def test_guest_seed_edits_only_the_selected_literal_span(kind):
    source = guest_seed()
    projected = await project_guest(GuestDocument(latex_content=source))
    nodes = projected["document"]["nodes"]
    if kind == "name":
        node = next(node for node in nodes if node["text"] == "Alex Morgan")
    elif kind == "contact":
        node = next(node for node in nodes if node["text"].startswith("alex@example.com"))
    elif kind in {"summary", "skills"}:
        node = next(node for node in nodes if node["section"] == kind)
    else:
        node = next(node for node in nodes if node["kind"] == "bullet")
    replacement = "Updated verified achievement" if kind == "bullet" else "Updated & verified"
    encoded = replacement if kind == "bullet" else r"Updated \& verified"
    result = await patch_guest(GuestPatch(
        latex_content=source,
        expected_source_sha256=digest(source),
        patches=[{"node_id": node["node_id"], "expected_node_revision": node["node_revision"], "text": replacement}],
    ))
    assert result["latex_content"] == source.replace(node["text"], encoded, 1)
    assert any(node["text"] == replacement for node in result["document"]["nodes"])
