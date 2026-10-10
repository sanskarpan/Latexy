"""Generate inspectable coverage evidence without importing application services.

Run from any directory: python backend/scripts/generate_capability_matrix.py.
This describes enforcement/test scope, not manual QA or live-provider success.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "backend/app/middleware/capability_router.py"
OUTPUT = ROOT / "docs/audits/admin-capabilities/feature-matrix.json"

# Resource/payload-sensitive checks cannot be expressed as a whole-route gate.
# Each reference names the actual enforcement function and its condition.
DYNAMIC = {
    "a09": ["middleware/capability_router.py:_route_gate (all anonymous AI/ATS/reference/import admissions, Studio compilation/jobs/watermark and premium raw export)"],
    "b02": ["middleware/capability_router.py:payload_capabilities (nonempty tags in source create/update; explicit tag changes; clearing tags exempt)"],
    "b05": ["api/template_routes.py:list_categories/list_templates (filter specialty catalog)", "api/template_routes.py:_template_asset_access/get_template/use_template (academic/regional/presentation)", "api/resume_routes.py:_get_builder_template (specialty selection)"],
    "b07": ["api/resume_routes.py:seed_builder_from_upload (detected JSON interchange)"],
    "b09": ["middleware/capability_router.py:payload_capabilities (normalized force_reattach; ordinary source edits/detachment remain recovery)"],
    "b12": ["api/resume_routes.py:fork_resume (source-linked builder variant)", "api/resume_routes.py:_sync_linked_variants (new automatic refresh admission)"],
    "c22": ["workers/auto_save_worker.py:submit_auto_save_checkpoint (new automatic checkpoint admission)"],
    "c12": ["middleware/capability_router.py:payload_capabilities (jobs/submit auto_fit)"],
    "c14": ["middleware/capability_router.py:payload_capabilities (presentation document type)", "api/template_routes.py:use_template (presentation template)"],
    "d01": ["middleware/capability_router.py:payload_capabilities (llm_optimization/combined)", "api/public_api_routes.py:require_developer_operation/_authorize (optimize)"],
    "d02": ["middleware/capability_router.py:payload_capabilities (guided industry/seniority/tone/emphasize/downplay)"],
    "d18": ["middleware/capability_router.py:payload_capabilities (ATS and combined jobs)", "api/public_api_routes.py:require_developer_operation/_authorize (ATS)"],
    "d19": ["middleware/capability_router.py:payload_capabilities (explicit industry/locale profile)", "api/public_api_routes.py:ats_score_v1 (industry)", "api/ats_routes.py:score_resume_ats (generic fallback)", "workers/ats_worker.py:submit_ats_scoring (generic admission snapshot)", "workers/orchestrator.py:submit_optimize_and_compile/_run_ats_stage (server-owned generic-only snapshot survives queue delay)"],
    "d21": ["api/resume_routes.py:create_resume/update_resume/fork_resume (only enqueue embeddings when enabled)"],
    "d25": ["services/api_key_service.py:get_user_provider (before decrypting existing key)", "services/api_key_service.py:load_user_providers (before cached provider loading)", "api/ai_routes.py:_resolve_ai_api_key (propagates denial, no platform fallback)"],
    "e06": ["middleware/capability_router.py:payload_capabilities (alert update; pause-only exempt)", "workers/tracker_notification_worker.py:deliver_tracker_notifications (each recurring alert rechecks its owner; disabled alerts retain unsent state)"],
    "f01": ["middleware/capability_router.py:payload_capabilities (share creation)", "api/routes.py:get_shared_resume (owner's current grant)", "api/review_routes.py:_review_resume (owner's current grant)"],
    "f02": ["middleware/capability_router.py:payload_capabilities (anonymous sharing/regeneration)", "api/routes.py:get_shared_resume (anonymous artifact owner)"],
    "f03": ["middleware/capability_router.py:payload_capabilities (enable public reviews)", "api/review_routes.py:_review_resume (public read/write checked against owner)", "api/routes.py:get_shared_resume (expose current review availability)"],
    "f04": ["middleware/capability_router.py:payload_capabilities (collaborator role increase; viewer downgrade exempt)", "api/resume_routes.py:_get_resume_document_access/update_resume (current collaborator and owner grants on reads and writes)"],
    "f05": ["middleware/capability_router.py:payload_capabilities (collaboration ticket)", "api/ws_routes.py:collab_websocket/_collab_live_access_callback (entry, current ACL, every frame and idle heartbeat)", "services/collab_manager.py:CollabRoom.has_access/broadcast/send_to (current recipient authorization before outbound data)", "services/entitlement_service.py:users_have_feature (fresh batched owner/participant grants)"],
    "f08": ["middleware/capability_router.py:payload_capabilities (workspace role increase; viewer downgrade exempt)", "api/workspace_routes.py:_workspace_use_allowed/_require_workspace_use (actor and workspace owner; owned source/removal preserved)"],
    "g12": ["middleware/capability_router.py:payload_capabilities (enable portfolio/source visibility; disable exempt)", "api/portfolio_routes.py:get_portfolio/contact_portfolio_owner/resolve_domain (existing owner's grant)"],
    "g13": ["api/portfolio_routes.py:resolve_domain (custom-domain owner's current grant)"],
    "h01": ["middleware/capability_router.py:payload_capabilities (premium saved/raw format conversion; tex/pdf exempt)"],
    "h02": ["middleware/capability_router.py:payload_capabilities (saved SVG/JPEG conversion)"],
    "h04": ["middleware/capability_router.py:payload_capabilities (bulk ZIP export)"],
    "h07": ["api/routes.py:_record_resume_view (skip collection when disabled)"],
    "h09": ["api/public_api_routes.py:require_developer_operation/_authorize (existing API keys; before job record/quota/dispatch)"],
    "i02": ["services/plan_catalog_service.py:require_new_purchase (target student/team SKU)", "api/routes.py:create_subscription/verify_student_subscription (new checkout only)"],
}

FOCUSED_TESTS = {
    "a09": ["test_capability_route_policy.py::test_anonymous_studio_gate_covers_alternate_guest_admissions"],
    "b05": ["test_capability_route_policy.py::test_specialty_template_asset_rechecks_category_capability"],
    "b07": ["test_capability_route_policy.py::test_structured_import_checks_interchange_capability"],
    "c12": ["test_capability_route_policy.py::test_multiplexed_jobs_cannot_bypass_disabled_feature"],
    "d01": ["test_capability_route_policy.py::test_multiplexed_jobs_cannot_bypass_disabled_feature", "test_capability_job_admission.py::test_admitted_job_survives_toggle_and_worker_failure_refunds_once"],
    "d18": ["test_capability_route_policy.py::test_multiplexed_jobs_cannot_bypass_disabled_feature", "test_capability_route_policy.py::test_public_api_gate_runs_before_job_record_creation"],
    "d25": ["test_capability_route_policy.py::test_stored_byok_key_is_not_decrypted_or_replaced_with_platform_key"],
    "d19": ["test_ats_capability_admission.py (server-owned queued decision, client tamper rejection, generic fallback)"],
    "f01": ["test_capability_route_policy.py::test_disabled_public_share_cannot_issue_another_storage_url"],
    "f03": ["test_capability_route_policy.py::test_public_review_uses_owner_entitlement_and_hides_disabled_link"],
    "f05": ["test_collaboration.py::TestCollabWebSocket::test_active_editor_is_closed_when_capability_changes", "test_capability_resolution.py (batched owner/participant resolution)"],
    "h01": ["test_capability_route_policy.py::test_raw_export_has_same_gate_as_saved_export"],
    "h02": ["test_capability_route_policy.py::test_raw_export_has_same_gate_as_saved_export"],
    "h09": ["test_capability_route_policy.py::test_existing_developer_key_cannot_dispatch_after_downgrade", "test_capability_route_policy.py::test_public_api_gate_runs_before_job_record_creation"],
}


# Historical passing browser evidence is attached only to the interactions
# actually exercised. It is not a substitute for latest-head CI or provider QA.
BROWSER_RUN = "https://github.com/sanskarpan/Latexy/actions/runs/38004341871/job/114069613888"
FULLSTACK_RUN = "https://github.com/sanskarpan/Latexy/actions/runs/38050964761/job/114210546206"
FULLSTACK_COMMIT = "e0881b31db0cd534d7fed4868ebe5fc2a0403ee6"
BROWSER_EVIDENCE = {
    "a02": "Admin inventory displays the immutable authentication baseline and no switch; authentication itself was not exercised.",
    "b03": "Admin inventory displays the search switch and exact-SKU columns; cross-document search itself was not exercised.",
    "c01": "Source remains intact and manual compile stays enabled while optional grants are revoked or unavailable; no compiler provider was invoked.",
    "c03": "Find controls and keyboard search deny/enable according to refreshed grants.",
    "c04": "Editor keybinding selector denies/enables according to refreshed grants.",
    "c06": "Auto-compile control denies/enables with grants, then disappears on policy outage while source and manual compile survive.",
}


def generate() -> dict:
    catalog = json.loads((ROOT / "backend/app/core/capability_catalog.json").read_text())
    policy_ast = ast.parse(POLICY.read_text())
    assignment = next(node for node in policy_ast.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "ROUTE_CAPABILITIES")
    routes = ast.literal_eval(assignment.value)
    ui_text = (ROOT / "frontend/src/lib/capability-ui-policy.ts").read_text()
    client = {}
    for key, paths in re.findall(r"^\s*([a-i]\d\d):\s*\[(.*)\],?$", ui_text, re.MULTILINE):
        client[key] = [str((ROOT / "frontend/src" / relative).resolve().relative_to(ROOT)) for relative in re.findall(r"'([^']+)'", paths)]
    # Find direct component gates and dynamic editor-tool maps too. Test files
    # and the admin catalog are excluded: listing a key is not a user gate.
    for path in (ROOT / "frontend/src").rglob("*.tsx"):
        if "__tests__" in path.parts or "admin" in path.parts:
            continue
        source = path.read_text()
        for key in re.findall(r"(?:can|canUseFeature)\(\s*['\"]([a-i]\d\d)['\"]|feature=['\"]([a-i]\d\d)['\"]", source):
            actual = next(value for value in key if value)
            client.setdefault(actual, []).append(str(path.relative_to(ROOT)))
    features = []
    for feature in catalog:
        key = feature["key"]
        handlers = [f"backend/app/api/{module}.py:{name}" for module, entries in routes.items() for name, keys in entries.items() if key in keys]
        dynamic = ["backend/app/" + ref for ref in DYNAMIC.get(key, [])]
        ui = sorted(set(client.get(key, [])))
        tests = list(FOCUSED_TESTS.get(key, []))
        if handlers:
            tests.append("test_capability_route_policy.py::test_disabled_capability_blocks_every_registered_operation (each listed handler/key)")
        if key in {"b02", "d02", "d19", "e06", "f01", "f02", "f03", "f04", "f05", "f08", "g12"}:
            tests.append("test_capability_route_policy.py::test_dynamic_policy_preserves_recovery_and_checks_requested_operations (selector cases)")
        if not feature["gateable"]:
            status = "deliberate_always_on_baseline"
        elif not (handlers or dynamic or ui):
            status = "MISSING_ENFORCEMENT"
        elif tests:
            status = "automated_backend_policy_coverage"
        elif ui:
            status = "client_control_wiring; per-capability behavior not exhaustively tested"
        else:
            status = "data_dependent_server_wiring; dedicated behavior test incomplete"
        features.append({
            "inventoryId": feature["inventory_id"], "key": key,
            "label": feature["label"], "parentKey": feature["parent_key"],
            "gateable": feature["gateable"], "baselineReason": feature["always_on_reason"],
            "serverHandlers": handlers, "dynamicOrServiceGates": dynamic,
            "clientControls": ui,
            "verification": {
                "status": status,
                "automatedBackendEvidence": ["backend/test/" + test for test in tests],
                "catalogCoverage": "backend/test/test_entitlement_wiring.py",
                "rolePolicyEvidence": "backend/test/test_capability_roles.py::test_role_feature_plan_cross_product (all four account contexts and eleven concrete SKUs; pure policy, not UI/API workflow)",
                "roleCoverage": [{
                    "role": role,
                    "effectivePolicy": "tested_off_on_and_cross_role_isolation" if feature["gateable"] else "tested_immutable_baseline",
                    "ui": ("representative real full-stack B03 OFF/ON passed at " + FULLSTACK_COMMIT + "; latest-head CI remains required" if key == "b03" and role != "anonymous" else "anonymous Studio Recompile/Auto OFF/ON and SyncTeX OFF passed at " + FULLSTACK_COMMIT + "; empty ATS badge assertion requires latest-head CI" if key == "a09" and role == "anonymous" else "not individually browser-tested for this role"),
                    "api": ("real PostgreSQL/Redis ASGI and local TCP HTTP OFF/ON denial verified" if key == "b03" and role != "anonymous" else "policy and registered-route denial tested separately; not exhaustive role-by-endpoint execution" if handlers or dynamic else "client-only or baseline; ordinary endpoint ACLs remain"),
                    "authorization": "Restricts product use only; authentication, document/workspace/tenant ACLs, quotas and provider constraints remain independent.",
                } for role in ["anonymous", "user", "support", "admin"]],
                "representativeRealFullStackEvidence": ([{
                    "status": "passed_prior_head_real_next_fastapi_postgresql_redis",
                    "commit": FULLSTACK_COMMIT,
                    "run": FULLSTACK_RUN,
                    "testFile": "frontend/e2e/capability-fullstack.spec.ts",
                    "scope": ("user/support/admin B03 OFF/ON UI and direct API; support mobile; owner source and admin recovery; user cross-tab refresh without navigation" if key == "b03" else "anonymous A09 OFF hides Recompile/Auto/SyncTeX, retains source and denies jobs API; ON restores Recompile/Auto; screenshot inspection found an empty ATS indicator, corrected and requiring latest-head rerun"),
                    "latestHeadResult": "Check the PR exact-head CI and review summary; this historical result does not verify later changes.",
                }] if key in {"a09", "b03"} else []),
                "automatedBrowserEvidence": ([{
                    "status": "passed_api_mocked_chromium",
                    "commit": "328acae82a918e5145e716db324679fe34673ab3",
                    "run": BROWSER_RUN,
                    "testFile": "frontend/e2e/capability-controls.spec.ts",
                    "scope": BROWSER_EVIDENCE[key],
                }] if key in BROWSER_EVIDENCE else []),
                "liveProviderOrManualEndToEnd": "not verified by this change",
                "notes": "Policy denial tests verify real registered ASGI dependencies and no handler DB writes; they do not prove complete successful provider workflows.",
            },
        })
    missing = [feature["inventoryId"] for feature in features if feature["verification"]["status"] == "MISSING_ENFORCEMENT"]
    if missing:
        raise RuntimeError(f"Missing enforcement: {missing}")
    return {
        "schemaVersion": 2,
        "accountContexts": ["anonymous", "user", "support", "admin"],
        "rolePolicy": "global AND account role AND plan family AND exact SKU AND all ancestors; missing/unknown optional grants deny",
        "inventorySource": "backend/app/core/capability_catalog.json",
        "generator": "backend/scripts/generate_capability_matrix.py",
        "inventoryCount": len(features),
        "gateableCount": sum(feature["gateable"] for feature in features),
        "alwaysOnCount": sum(not feature["gateable"] for feature in features),
        "semantics": "Stop new admissions and external actions. Already admitted jobs retain existing completion/finalization/refund behavior; owners retain source/results/recovery/deletion/revocation. Previously issued presigned URLs last until expiry.",
        "verificationScope": "Automated policy, selected real-infrastructure admission/refund and existing regression coverage. Not a claim that all 129 features were manually QA-tested or that live providers/payments were exercised.",
        "features": features,
    }


if __name__ == "__main__":
    result = generate()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote {result['inventoryCount']} capabilities to {OUTPUT.relative_to(ROOT)}")
