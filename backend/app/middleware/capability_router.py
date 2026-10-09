"""Audited, operation-level product gates, installed when routes are registered.

Policies deliberately name handlers rather than matching URL prefixes: an
existing artifact's read/delete/revoke route must survive a downgrade. These
dependencies complement, and never replace, the handler's authentication, ACL,
CSRF, provider validation, and quota checks. Optional authentication here keeps
the same policy effective on anonymous Studio entry points.

Client-only capabilities have no HTTP policy. Protocol clients (CLI/MCP/Action)
inherit the policy of the operation they call. Multiplexed operations are
checked from their payload before a handler can charge quota or dispatch work.
Gates stop new admissions. Already admitted jobs keep their original execution,
finalization, and exactly-once refund rules; a toggle is not job cancellation.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, Request

from ..services.entitlement_service import entitlement_service
from .auth_middleware import get_current_user_optional
from .entitlements import _denied

# A value is a tuple because some operations require more than one capability.
ROUTE_CAPABILITIES: dict[str, dict[str, tuple[str, ...]]] = {
    "ai_routes": {
        "generate_bullets": ("d09",), "generate_phrase_library": ("d09",),
        "generate_summary": ("d11",), "proofread_resume": ("d12",),
        "explain_latex_error": ("d13",), "generate_bullet_variants": ("d10",),
        "generate_latex": ("d14",), "generate_table_from_text": ("d14",),
        "generate_table_from_image": ("d14",), "generate_math_from_text": ("d14",),
        "generate_math_from_image": ("d14",), "rewrite_text": ("d06",),
        "document_assistant": ("d08",), "suggest_synonyms": ("d07",),
        "spell_check": ("c16",), "get_confidence_score": ("d17",),
        "standardize_dates": ("d16",), "salary_estimate": ("d26",),
        "age_analysis": ("d16",), "format_contacts": ("d16",),
        "translate_resume": ("d15",), "reorder_sections_endpoint": ("d16",),
        "generate_publications": ("g10",),
    },
    "ats_routes": {
        "score_resume_ats": ("d18",), "analyze_job_description_ats": ("d18",),
        "get_ats_recommendations": ("d18",), "quick_score_ats": ("d18",),
        "deep_analyze_resume": ("d20",), "semantic_match_resumes": ("d21",),
        "simulate_ats": ("d22",), "keyword_density": ("d23",),
        "get_ats_benchmark": ("d24",),
    },
    "format_routes": {
        "detect_file_format": ("b06",), "validate_file_format": ("b06",),
        "parse_for_preview": ("b06",), "upload_for_conversion": ("b06",),
    },
    "resume_routes": {
        "list_builder_templates": ("b08", "b04"),
        "seed_builder_from_upload": ("b06", "b08"),
        "create_builder_resume": ("b08",), "update_builder_resume": ("b08",),
        "search_resumes": ("b03",),
        "pin_resume": ("b02",), "archive_resume": ("b02",),
        "update_resume_settings": ("c07",), "update_variant_visibility": ("b12",),
        "fork_resume": ("b11",), "quick_tailor_resume": ("d04", "d01", "d18"),
        "get_academic_cv_report": ("b14",), "convert_academic_cv": ("b14", "d01", "d18"),
        "create_checkpoint": ("c22",), "invite_collaborator": ("f04",),
        "generate_references": ("g11",),
        "merge_resumes": ("b13",), "generate_portfolio": ("g12",),
        "get_resume_analytics": ("h07",),
    },
    "job_routes": {
        "compile_watermarked": ("c13",), "create_batch_tailor": ("d05", "d01", "d18"),
    },
    "routes": {
        "optimize_resume": ("d01", "d18"), "optimize_and_compile_resume": ("d01", "d18"),
    },
    "optimize_routes": {
        "segment_changes_endpoint": ("d03",), "apply_changes_endpoint": ("d03",),
    },
    "export_routes": {"export_canva": ("h03",), "export_figma": ("h03",)},
    "document_delivery_routes": {
        "email_compiled_document": ("h05",), "retry_email_compiled_document": ("h05",),
    },
    "cover_letter_routes": {
        "generate_cover_letter": ("e01",), "update_cover_letter": ("e01",),
    },
    "interview_routes": {
        "generate_interview_prep": ("e02",), "evaluate_interview_simulation": ("e03",),
    },
    "career_routes": {"analyze_career_path": ("e04",)},
    "tracker_routes": {
        "create_application": ("e05",), "update_application": ("e05",),
        "update_application_status": ("e05",),
    },
    "tracker_workflow_routes": {
        "create_saved_job": ("e06",), "update_saved_job": ("e06",),
        "track_saved_job": ("e05", "e06"), "create_alert": ("e06",),
        "create_reminder": ("e07",), "update_reminder": ("e07",),
        "create_interview": ("e07",), "update_interview": ("e07",),
        "create_company": ("e08",), "update_company": ("e08",),
        "create_contact": ("e08",), "update_contact": ("e08",),
    },
    "outreach_routes": {"generate_outreach_draft": ("e09",)},
    "email_status_routes": {"parse_email_status": ("e10",)},
    "scraper_routes": {"scrape_job_description": ("e11",)},
    "application_routes": {
        "detect_platform": ("e12",), "preview_greenhouse_job": ("e12",),
        "preview_lever_job": ("e12",), "apply_greenhouse": ("e12",),
        "apply_lever": ("e12",),
    },
    "workspace_routes": {
        "create_workspace": ("f08",), "update_workspace": ("f08",),
        "invite_member": ("f08",),
        "add_resume_to_workspace": ("f08",),
        "create_recruiter_note": ("f09",), "update_recruiter_note": ("f09",),
    },
    "comment_routes": {"add_comment": ("f06",), "update_comment": ("f06",)},
    "suggestion_routes": {"decide_suggestion": ("f07",)},
    "element_version_routes": {
        "create_element_version": ("c23",), "fork_element_version": ("c23", "b11"),
    },
    "snippet_routes": {
        "create_snippet": ("c20",), "update_snippet": ("c20",),
        "install_snippet": ("c20",), "toggle_upvote": ("c20",),
    },
    "macro_routes": {
        "create_macro": ("c21",), "update_macro": ("c21",), "execute_macro": ("c21",),
    },
    "template_routes": {
        "list_categories": ("b04",), "list_templates": ("b04",),
        "get_template": ("b04",), "use_template": ("b04",),
        "head_template_thumbnail": ("b04",), "get_template_thumbnail": ("b04",),
        "head_template_pdf": ("b04",), "get_template_pdf": ("b04",),
    },
    "github_routes": {
        "github_connect": ("g01",),
        "github_complete": ("g01",), "enable_github_sync": ("g01",),
        "push_to_github": ("g01",), "pull_from_github": ("g01",),
        "import_github_projects": ("g02",),
    },
    "dropbox_routes": {
        "dropbox_connect": ("g05",),
        "dropbox_complete": ("g05",), "enable_dropbox_sync": ("g05",),
        "push_to_dropbox": ("g05",), "pull_from_dropbox": ("g05",),
    },
    "google_drive_routes": {
        "google_drive_connect": ("g06",),
        "google_drive_complete": ("g06",), "export_resume_to_google_drive": ("g06",),
    },
    "zotero_routes": {
        "zotero_connect": ("g07",),
        "zotero_complete": ("g07",), "zotero_collections": ("g07",),
        "zotero_import": ("g07",),
    },
    "mendeley_routes": {
        "mendeley_connect": ("g08",),
        "mendeley_complete": ("g08",), "mendeley_import": ("g08",),
    },
    "sources_routes": {"import_from_url": ("g03",), "import_linkedin": ("g04",)},
    "reference_routes": {
        "fetch_references": ("g09",), "verify_citations": ("g09",),
        "fetch_orcid_publications": ("g09",), "detect_references": ("g09",),
    },
    "portfolio_routes": {"verify_domain": ("g13",)},
    "developer_routes": {"create_developer_key": ("h08",), "rename_developer_key": ("h08",)},
    "byok_routes": {
        "add_api_key": ("d25",), "validate_api_key": ("d25",),
        "test_provider_connection": ("d25",), "generate_with_provider": ("d25",),
        "load_user_providers": ("d25",),
    },
    "analytics_routes": {
        "get_my_analytics": ("h06",), "get_my_analytics_timeseries": ("h06",),
    },
    "referral_routes": {"claim_referral": ("i03",)},
    "team_routes": {"invite_team_member": ("i02",), "join_team_seat": ("i02",)},
}

DYNAMIC_ENDPOINTS = frozenset({
    ("job_routes", "submit_job"),
    ("resume_routes", "create_resume"), ("resume_routes", "update_resume"),
    ("resume_routes", "update_builder_resume"), ("resume_routes", "create_share_link"),
    ("resume_routes", "bulk_export"),
    ("export_routes", "export_resume"), ("export_routes", "export_content"),
    ("tracker_workflow_routes", "update_alert"),
    ("ws_routes", "create_websocket_ticket"),
    ("ats_routes", "score_resume_ats"), ("ats_routes", "quick_score_ats"),
    ("routes", "optimize_resume"), ("routes", "optimize_and_compile_resume"),
    ("routes", "compile_latex_anonymous"),
    ("portfolio_routes", "setup_portfolio"),
    ("resume_routes", "update_resume_tags"), ("resume_routes", "update_collaborator_role"),
    ("workspace_routes", "update_member_role"),
})


def payload_capabilities(module: str, name: str, body: dict, params: dict, query: dict) -> tuple[str, ...]:
    """Pure selector: easy to audit and test without invoking a provider."""
    keys: list[str] = []
    if (module, name) == ("job_routes", "submit_job"):
        job_type = body.get("job_type")
        if not isinstance(job_type, str):
            job_type = None  # Leave malformed values to Pydantic's 422 response.
        keys.extend({"llm_optimization": ("d01",), "combined": ("d01", "d18"),
                     "ats_scoring": ("d18",), "auto_fit": ("c12",)}.get(job_type, ()))
        if job_type in {"llm_optimization", "combined"} and any(
            body.get(field) for field in ("industry", "seniority", "tone", "emphasize", "downplay")
        ):
            keys.append("d02")
        if job_type == "ats_scoring" and body.get("industry"):
            keys.append("d19")
    if module == "routes" and name in {"optimize_resume", "optimize_and_compile_resume"}:
        if any(body.get(field) for field in ("industry", "seniority", "tone", "emphasize", "downplay")):
            keys.append("d02")
    if module == "ats_routes" and (
        body.get("industry") or body.get("industry_override") or body.get("locale_profile")
        or body.get("locale") not in (None, "global")
    ):
        keys.append("d19")
    if module == "resume_routes" and name in {"create_resume", "update_resume"}:
        if body.get("document_type") == "presentation":
            keys.append("c14")
        if body.get("portfolio_visible") is True:
            keys.append("g12")
        if body.get("tags"):
            keys.append("b02")
    if (module, name) == ("resume_routes", "create_share_link"):
        # Revocation has its own DELETE route and is deliberately always-on.
        keys.append("f01")
        if body.get("anonymous") or body.get("regenerate_anonymous"):
            keys.append("f02")
        if body.get("review_comments") is True:
            keys.append("f03")
    if module == "export_routes" and name in {"export_resume", "export_content"}:
        fmt = params.get("fmt")
        if fmt in {"svg", "jpeg"}:
            keys.append("h02")
        elif fmt not in {"tex", "pdf"}:
            keys.append("h01")
    if (module, name) == ("resume_routes", "bulk_export"):
        keys.append("h04")
        if query.get("format", "tex") not in {"tex", "pdf"}:
            keys.append("h01")
    if (module, name) == ("tracker_workflow_routes", "update_alert"):
        # A paused alert is a revocation; changing/activating it is paid use.
        if body != {"active": False}:
            keys.append("e06")
    if (module, name) == ("ws_routes", "create_websocket_ticket") and body.get("purpose") == "collab":
        keys.append("f05")
    if (module, name) == ("portfolio_routes", "setup_portfolio") and body.get("portfolio_enabled") is not False:
        keys.append("g12")
    if (module, name) == ("resume_routes", "update_resume_tags") and body.get("tags") != []:
        keys.append("b02")
    if (module, name) == ("resume_routes", "update_collaborator_role") and body.get("role") != "viewer":
        keys.append("f04")
    if (module, name) == ("workspace_routes", "update_member_role") and body.get("role") != "viewer":
        keys.append("f08")
    return tuple(dict.fromkeys(keys))


async def enforce_capabilities(keys: tuple[str, ...], user: Any) -> None:
    for key in keys:
        if not await entitlement_service.has_feature(key, user=user):
            raise _denied(key)


@lru_cache(maxsize=None)
def _route_gate(module: str, name: str):
    async def gate(request: Request, user=Depends(get_current_user_optional)) -> None:
        keys = ROUTE_CAPABILITIES.get(module, {}).get(name, ())
        if user is None and (
            module in {"ai_routes", "ats_routes", "reference_routes", "format_routes"}
            or (module, name) in {
                ("routes", "compile_latex_anonymous"), ("job_routes", "submit_job"),
                ("job_routes", "compile_watermarked"),
            }
            or ((module, name) == ("export_routes", "export_content") and request.path_params.get("fmt") != "tex")
        ):
            keys += ("a09",)
        if (module, name) in DYNAMIC_ENDPOINTS:
            body = {}
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
            if not content_type or content_type == "application/json" or content_type.endswith("+json"):
                try:
                    parsed = await request.json()
                    if isinstance(parsed, dict):
                        body = parsed
                except (ValueError, UnicodeDecodeError):
                    pass  # The endpoint's existing validation reports malformed input.
            keys += payload_capabilities(module, name, body, request.path_params, dict(request.query_params))
        await enforce_capabilities(tuple(dict.fromkeys(keys)), user)

    gate.__name__ = f"capability_{module}_{name}"
    return gate


class CapabilityRouter(APIRouter):
    """APIRouter with additive, registration-time capability dependencies."""

    def add_api_route(self, path: str, endpoint, **kwargs) -> None:
        module, name = endpoint.__module__.rsplit(".", 1)[-1], endpoint.__name__
        if name in ROUTE_CAPABILITIES.get(module, {}) or (module, name) in DYNAMIC_ENDPOINTS:
            gate = _route_gate(module, name)
            dependencies = list(kwargs.pop("dependencies", None) or [])
            if not any(dependency.dependency is gate for dependency in dependencies):
                dependencies.insert(0, Depends(gate))
            kwargs["dependencies"] = dependencies
        super().add_api_route(path, endpoint, **kwargs)
