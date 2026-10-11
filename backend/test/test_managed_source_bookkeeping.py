"""Managed writes share builder save tokens without persisting projection defaults."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm.attributes import set_committed_value

from app.database.models import Resume
from app.services.resume_managed_source_service import apply_managed_document_change


def saved_resume():
    resume = Resume()
    values = {
        "latex_content": "original source",
        "structured_content": {"basics": {"name": "Jane"}, "section_titles": {}},
        "structured_version": 7,
        "content_revision": 3,
        "builder_status": "active",
        "content_source": "builder",
        "selected_template_id": "template",
        "resume_settings": {"compiler": "lualatex", "share_anonymous_job_id": "cached", "share_anonymous_pending": True},
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    for key, value in values.items():
        set_committed_value(resume, key, value)
    return resume


def test_noop_does_not_store_materialized_defaults_or_write_any_resume_attribute():
    resume = saved_resume()
    projected = deepcopy(resume.structured_content)
    projected["section_titles"] = {"experience": "Experience"}

    assert not apply_managed_document_change(
        resume, resume.latex_content, deepcopy(projected), previous_structured=projected
    )
    assert resume.structured_content["section_titles"] == {}
    assert not any(attribute.history.has_changes() for attribute in inspect(resume).attrs)


@pytest.mark.parametrize("source_changed,structured_changed", [(True, False), (False, True), (True, True)])
def test_real_mutation_advances_builder_token_once_and_only_invalidates_changed_source(
    source_changed, structured_changed,
):
    resume = saved_resume()
    before = deepcopy(resume.structured_content)
    after = deepcopy(before)
    if structured_changed:
        after["basics"]["name"] = "Jane Doe"
    source = "new source" if source_changed else resume.latex_content

    assert apply_managed_document_change(resume, source, after, previous_structured=before)
    assert resume.structured_version == 8
    assert resume.content_revision == 3  # the existing database trigger owns the engine revision
    assert resume.latex_content == source
    assert resume.structured_content == after
    assert resume.builder_status == "active" and resume.content_source == "builder"
    assert resume.selected_template_id == "template"
    assert resume.updated_at > datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert ("share_anonymous_job_id" in resume.resume_settings) is not source_changed
    assert ("share_anonymous_pending" in resume.resume_settings) is not source_changed
    assert resume.resume_settings["compiler"] == "lualatex"

    # Retrying the already-applied semantic result against its current snapshot
    # is a no-op, including the timestamp and share-cache state.
    updated_at = resume.updated_at
    assert not apply_managed_document_change(resume, source, deepcopy(after), previous_structured=after)
    assert resume.structured_version == 8 and resume.updated_at == updated_at
