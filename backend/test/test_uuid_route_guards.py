from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.application_routes import _get_resume_pdf, get_submission
from app.api.career_routes import (
    AnalyzeRequest,
    analyze_career_path,
    get_career_analysis,
    list_career_analyses,
)
from app.api.comment_routes import CommentUpdate, update_comment
from app.api.dropbox_routes import (
    disable_dropbox_sync,
    enable_dropbox_sync,
    get_resume_dropbox_status,
    pull_from_dropbox,
    push_to_dropbox,
)
from app.api.github_routes import (
    GitHubEnableRequest,
    disable_github_sync,
    enable_github_sync,
    get_resume_github_status,
    pull_from_github,
    push_to_github,
)
from app.api.interview_routes import (
    GenerateInterviewPrepRequest,
    generate_interview_prep,
    list_resume_interview_prep,
)
from app.api.macro_routes import MacroUpdate, delete_macro, update_macro
from app.api.mendeley_routes import MendeleyImportRequest, mendeley_import
from app.api.snippet_routes import (
    SnippetUpdate,
    delete_snippet,
    get_snippet,
    install_snippet,
    toggle_upvote,
    uninstall_snippet,
    update_snippet,
)
from app.api.team_routes import remove_team_seat
from app.api.tenant_routes import _require_tenant_owner_or_admin, list_members
from app.api.tracker_routes import (
    StatusUpdateRequest,
    UpdateApplicationRequest,
    delete_application,
    get_application,
    update_application,
    update_application_status,
)
from app.api.workspace_routes import _get_workspace_or_404, add_resume_to_workspace
from app.api.zotero_routes import ZoteroImportRequest, clear_bibtex, zotero_import


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        lambda db: analyze_career_path(
            AnalyzeRequest(resume_id="not-a-uuid", target_role_title="Engineer"),
            db=db,
            user_id="user",
        ),
        lambda db: list_career_analyses("not-a-uuid", db=db, user_id="user"),
        lambda db: get_career_analysis("not-a-uuid", db=db, user_id="user"),
        lambda db: generate_interview_prep(
            GenerateInterviewPrepRequest(resume_id="not-a-uuid"),
            db=db,
            user_id="user",
        ),
        lambda db: list_resume_interview_prep("not-a-uuid", db=db, user_id="user"),
        lambda db: _get_resume_pdf("not-a-uuid", "user", db),
        lambda db: get_submission("not-a-uuid", db=db, user_id="user"),
        lambda db: enable_github_sync(
            "not-a-uuid", GitHubEnableRequest(repo_name="resume"), db=db, user_id="user"
        ),
        lambda db: disable_github_sync("not-a-uuid", db=db, user_id="user"),
        lambda db: push_to_github("not-a-uuid", db=db, user_id="user"),
        lambda db: pull_from_github("not-a-uuid", db=db, user_id="user"),
        lambda db: get_resume_github_status("not-a-uuid", db=db, user_id="user"),
        lambda db: enable_dropbox_sync("not-a-uuid", db=db, user_id="user"),
        lambda db: disable_dropbox_sync("not-a-uuid", db=db, user_id="user"),
        lambda db: push_to_dropbox("not-a-uuid", db=db, user_id="user"),
        lambda db: pull_from_dropbox("not-a-uuid", db=db, user_id="user"),
        lambda db: get_resume_dropbox_status("not-a-uuid", db=db, user_id="user"),
        lambda db: zotero_import(ZoteroImportRequest(resume_id="not-a-uuid"), db=db, user_id="user"),
        lambda db: clear_bibtex("not-a-uuid", db=db, user_id="user"),
        lambda db: mendeley_import(MendeleyImportRequest(resume_id="not-a-uuid"), db=db, user_id="user"),
        lambda db: _get_workspace_or_404("not-a-uuid", db),
        lambda db: add_resume_to_workspace("workspace", "not-a-uuid", db=db, user_id="user"),
        lambda db: update_comment(
            "not-a-uuid", "also-not-a-uuid", CommentUpdate(content="updated"), db=db, user_id="user"
        ),
        lambda db: update_macro("not-a-uuid", MacroUpdate(name="Macro"), db=db, user_id="user"),
        lambda db: delete_macro("not-a-uuid", db=db, user_id="user"),
        lambda db: get_snippet("not-a-uuid", db=db, user_id=None),
        lambda db: update_snippet("not-a-uuid", SnippetUpdate(title="Valid title"), db=db, user_id="user"),
        lambda db: delete_snippet("not-a-uuid", db=db, user_id="user"),
        lambda db: install_snippet("not-a-uuid", db=db, user_id="user"),
        lambda db: uninstall_snippet("not-a-uuid", db=db, user_id="user"),
        lambda db: toggle_upvote("not-a-uuid", db=db, user_id="user"),
        lambda db: _require_tenant_owner_or_admin("not-a-uuid", "user", db),
        lambda db: list_members("not-a-uuid", db=db, user_id="user"),
        lambda db: get_application("not-a-uuid", db=db, user_id="user"),
        lambda db: update_application(
            "not-a-uuid", UpdateApplicationRequest(), db=db, user_id="user"
        ),
        lambda db: delete_application("not-a-uuid", db=db, user_id="user"),
        lambda db: update_application_status(
            "not-a-uuid", StatusUpdateRequest(status="applied"), db=db, user_id="user"
        ),
        lambda db: remove_team_seat("not-a-uuid", db=db, user_id="user"),
    ],
)
async def test_malformed_uuid_is_404_before_database_access(call):
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await call(db)

    assert exc_info.value.status_code == 404
    db.execute.assert_not_awaited()
