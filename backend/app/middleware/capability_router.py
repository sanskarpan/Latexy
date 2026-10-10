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
from pydantic import TypeAdapter, ValidationError

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
        "get_industry_keywords": ("d19",),
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
    "comment_routes": {
        "add_comment": ("f06",), "update_comment": ("f06",),
        "list_comment_participants": ("f06",),
    },
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
    ("ats_routes", "deep_analyze_resume"), ("ats_routes", "get_ats_recommendations"),
    ("routes", "optimize_resume"), ("routes", "optimize_and_compile_resume"),
    ("routes", "compile_latex_anonymous"),
    ("portfolio_routes", "setup_portfolio"),
    ("resume_routes", "update_resume_tags"), ("resume_routes", "update_collaborator_role"),
    ("workspace_routes", "update_member_role"),
})


# Explicit exemptions: core operations, data recovery, metadata discovery,
# provider callbacks (which cannot redeem tokens), and separately-authorized
# resource/admin handlers. Any new first-party HTTP handler must be classified
# here or in the gate maps; an omitted policy must never silently allow use.
PASSTHROUGH_ENDPOINTS: dict[str, frozenset[str]] = {
    "admin_routes": frozenset({
        "get_public_feature_flags", "get_admin_feature_flags", "update_feature_flag",
        "get_entitlements", "update_kill_switch", "update_matrix_cell",
        "update_role_matrix_cell", "list_users", "update_user_role",
    }),
    "ai_routes": frozenset({
        "list_bullet_variants", "delete_bullet_variant_set", "list_personas",
    }),
    "analytics_routes": frozenset({
        "track_event", "get_user_analytics", "get_system_analytics",
        "get_conversion_funnel", "track_compilation", "track_optimization",
        "track_page_view", "track_feature_usage", "get_analytics_dashboard",
    }),
    "application_routes": frozenset({
        "list_submissions", "get_submission",
    }),
    "ats_routes": frozenset({
        "get_supported_industries", "get_industry_profiles", "get_locale_profiles",
        "list_ats_profiles",
    }),
    "byok_routes": frozenset({
        "get_user_api_keys", "delete_api_key", "get_supported_providers",
        "get_usage_stats", "get_system_health", "get_provider_models",
        "get_provider_capabilities",
    }),
    "career_routes": frozenset({
        "seed_career_graph",
        "list_career_analyses", "get_career_analysis", "search_career_roles",
        "search_esco_skills",
    }),
    "comment_routes": frozenset({
        "list_comments", "delete_comment", "resolve_comment",
    }),
    "cover_letter_routes": frozenset({
        "list_cover_letters", "get_cover_letter_stats", "get_cover_letter",
        "delete_cover_letter", "list_resume_cover_letters",
    }),
    "developer_routes": frozenset({
        "list_developer_keys", "get_developer_usage", "revoke_developer_key",
    }),
    "document_delivery_routes": frozenset({
        "email_compiled_document_status",
    }),
    "dropbox_routes": frozenset({
        "dropbox_callback", "dropbox_status", "dropbox_disconnect",
        "disable_dropbox_sync", "get_resume_dropbox_status",
    }),
    "element_version_routes": frozenset({
        "list_element_versions", "restore_element_version",
    }),
    "export_routes": frozenset({
        "list_export_formats",
    }),
    "format_routes": frozenset({
        "get_supported_formats", "get_format_info",
    }),
    "github_routes": frozenset({
        "github_callback", "github_status", "github_disconnect",
        "disable_github_sync", "get_github_import_result", "get_resume_github_status",
    }),
    "google_drive_routes": frozenset({
        "google_drive_callback", "google_drive_status", "google_drive_disconnect",
    }),
    "interview_routes": frozenset({
        "list_resume_interview_prep",
        "get_interview_prep", "delete_interview_prep",
    }),
    "job_routes": frozenset({
        "get_batch_status", "get_job_state", "get_job_result",
        "get_job_stream", "cancel_job", "list_jobs",
        "jobs_health", "trigger_cleanup",
    }),
    "macro_routes": frozenset({
        "list_macros", "delete_macro",
    }),
    "mendeley_routes": frozenset({
        "mendeley_callback", "mendeley_status", "mendeley_disconnect",
    }),
    "plan_catalog_routes": frozenset({
        "get_plan_catalog", "update_plan_catalog", "update_plan_quota",
    }),
    "portfolio_routes": frozenset({
        "check_username", "resolve_domain", "contact_portfolio_owner",
        "get_portfolio",
    }),
    "public_api_routes": frozenset({
        "compile_v1", "optimize_v1", "ats_score_v1",
        "get_job_v1", "download_job_pdf_v1",
    }),
    "referral_routes": frozenset({
        "referral_status",
    }),
    "resume_routes": frozenset({
        "get_resume_stats", "list_resumes", "get_error_history",
        "get_builder_resume", "get_resume", "delete_resume",
        "unpin_resume", "unarchive_resume", "get_variant_visibility",
        "list_variants", "diff_with_parent", "record_optimization",
        "get_optimization_history", "get_score_history", "restore_optimization",
        "list_checkpoints", "get_checkpoint_content", "delete_checkpoint",
        "revoke_share_link", "list_collaborators", "remove_collaborator",
    }),
    "review_routes": frozenset({
        "list_public_review_comments", "add_public_review_comment", "list_authenticated_review_comments",
        "resolve_authenticated_review_comment",
    }),
    "routes": frozenset({
        "get_me", "update_me_preferences", "get_entitlements_for_user",
        "health_check", "livez", "readyz",
        "metrics", "compile_latex_endpoint", "download_pdf",
        "download_synctex", "get_compilation_logs", "get_trial_status",
        "track_usage", "get_subscription_plans", "create_subscription",
        "verify_student_subscription", "validate_coupon", "get_current_subscription",
        "cancel_subscription", "razorpay_webhook", "get_shared_resume",
    }),
    "settings_routes": frozenset({
        "get_notification_prefs", "update_notification_prefs",
    }),
    "snippet_routes": frozenset({
        "seed_official_snippets",
        "list_snippets", "get_snippet", "delete_snippet",
        "uninstall_snippet",
    }),
    "suggestion_routes": frozenset({
        "get_suggestion_decision",
    }),
    "team_routes": frozenset({
        "list_team_seats", "preview_team_seat", "remove_team_seat",
    }),
    "telemetry_routes": frozenset({
        "ingest_frontend_telemetry",
    }),
    "template_routes": frozenset({
        "create_template", "update_template", "activate_template",
        "deactivate_template", "delete_template",
    }),
    "tenant_routes": frozenset({
        "current_context", "resolve_tenant_host", "create_tenant",
        "list_my_tenants", "create_cohort", "list_cohorts",
        "list_cohort_submissions", "update_tenant", "list_members",
        "invite_member", "accept_invitation", "remove_member",
        "leave_tenant", "tenant_stats", "verify_domain",
    }),
    "tracker_routes": frozenset({
        "list_applications", "get_tracker_stats", "get_application",
        "delete_application",
    }),
    "tracker_workflow_routes": frozenset({
        "list_saved_jobs", "delete_saved_job", "bulk_delete_saved_jobs",
        "list_alerts", "list_stale_applications", "delete_alert",
        "list_reminders", "delete_reminder", "list_interviews",
        "delete_interview", "export_interview_calendar", "list_companies",
        "delete_company", "list_contacts", "delete_contact",
    }),
    "workspace_routes": frozenset({
        "list_workspaces", "get_workspace", "delete_workspace",
        "remove_member", "remove_resume_from_workspace", "list_workspace_resumes",
        "download_workspace_resume", "list_recruiter_notes", "delete_recruiter_note",
    }),
    "zotero_routes": frozenset({
        "zotero_callback", "zotero_status", "zotero_disconnect",
        "clear_bibtex",
    }),
}

_BOOL_ADAPTER = TypeAdapter(bool)


def _payload_bool(value: Any) -> bool | None:
    """Use the same boolean coercion as the endpoint's Pydantic model.

    JSON strings/numbers accepted by Pydantic must not evade a true-only gate.
    Invalid values remain the endpoint's validation error, never a permission.
    """
    try:
        return _BOOL_ADAPTER.validate_python(value)
    except ValidationError:
        return None


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
        if _payload_bool(body.get("portfolio_visible")) is True:
            keys.append("g12")
        if body.get("tags"):
            keys.append("b02")
    if (module, name) == ("resume_routes", "create_share_link"):
        # Revocation has its own DELETE route and is deliberately always-on.
        if set(body) != {"review_comments"} or _payload_bool(body.get("review_comments")) is not False:
            keys.append("f01")
        if _payload_bool(body.get("anonymous")) is True or _payload_bool(body.get("regenerate_anonymous")) is True:
            keys.append("f02")
        if _payload_bool(body.get("review_comments")) is True:
            keys.append("f03")
    if (module, name) == ("resume_routes", "update_builder_resume") and _payload_bool(body.get("force_reattach")) is True:
        keys.append("b09")
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
        if set(body) != {"active"} or _payload_bool(body.get("active")) is not False:
            keys.append("e06")
    if (module, name) == ("ws_routes", "create_websocket_ticket") and body.get("purpose") == "collab":
        keys.append("f05")
    if (module, name) == ("portfolio_routes", "setup_portfolio") and _payload_bool(body.get("portfolio_enabled")) is not False:
        keys.append("g12")
    if (module, name) == ("resume_routes", "update_resume_tags") and body.get("tags") != []:
        keys.append("b02")
    if (module, name) == ("resume_routes", "update_collaborator_role") and body.get("role") not in ("viewer", "commenter"):
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
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
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
        classified_gate = name in ROUTE_CAPABILITIES.get(module, {}) or (module, name) in DYNAMIC_ENDPOINTS
        if endpoint.__module__.startswith("app.api.") and not classified_gate and name not in PASSTHROUGH_ENDPOINTS.get(module, ()):
            raise RuntimeError(f"Unclassified capability policy for {module}.{name}")
        if classified_gate:
            gate = _route_gate(module, name)
            dependencies = list(kwargs.pop("dependencies", None) or [])
            if not any(dependency.dependency is gate for dependency in dependencies):
                dependencies.insert(0, Depends(gate))
            kwargs["dependencies"] = dependencies
        super().add_api_route(path, endpoint, **kwargs)
