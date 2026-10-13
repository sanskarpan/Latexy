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
    "b01": ["middleware/capability_router.py:ROUTE_CAPABILITIES (source/builder/fork/merge creation and batch/conversion admission)", "api/template_routes.py:use_template (before creating a resume)"],
    "c01": ["middleware/capability_router.py:ROUTE_CAPABILITIES (source/metadata/builder writes, optimization history recording, accepted suggestions, GitHub pull)", "services/collab_manager.py:handle_collab_message (before Yjs source persistence and relay)"],
    "c05": ["middleware/capability_router.py:payload_capabilities (generic compile, combined, auto-fit and anonymous share)", "api/resume_routes.py:create_share_link (before redacted PDF submission)", "api/public_api_routes.py:require_developer_operation (compile admission)"],
    "i01": ["services/plan_catalog_service.py:require_new_purchase (new target-SKU checkout and token-owner Student verification)"],
    "a09": ["middleware/capability_router.py:_route_gate (all anonymous AI/ATS/reference/import admissions, Studio compilation/jobs/watermark, semantic projection/field editing and premium raw export)"],
    "b02": ["middleware/capability_router.py:payload_capabilities (nonempty tags in source create/update; explicit tag changes; clearing tags exempt)"],
    "b05": ["api/template_routes.py:list_categories/list_templates (filter specialty catalog)", "api/template_routes.py:_template_asset_access/get_template/use_template (academic/regional/presentation)", "api/resume_routes.py:_get_builder_template (specialty selection)"],
    "b07": ["api/resume_routes.py:seed_builder_from_upload (detected JSON interchange)"],
    "b09": ["middleware/capability_router.py:payload_capabilities (normalized force_reattach; content changes also require c01)"],
    "b12": ["api/resume_routes.py:fork_resume (source-linked builder variant)", "api/resume_routes.py:_sync_linked_variants (new automatic refresh admission)"],
    "c22": ["workers/auto_save_worker.py:submit_auto_save_checkpoint (new automatic checkpoint admission)"],
    "c12": ["middleware/capability_router.py:payload_capabilities (jobs/submit auto_fit)"],
    "c14": ["middleware/capability_router.py:payload_capabilities (presentation document type)", "api/template_routes.py:use_template (presentation template)"],
    "c16": ["api/routes.py:update_me_preferences (normalized dictionary additions require current owner policy; unchanged words and removals remain available)"],
    "d01": ["middleware/capability_router.py:payload_capabilities (llm_optimization/combined)", "api/public_api_routes.py:require_developer_operation/_authorize (optimize)"],
    "d02": ["middleware/capability_router.py:payload_capabilities (guided industry/seniority/tone/emphasize/downplay)"],
    "d03": ["middleware/capability_router.py:payload_capabilities (semantic candidate acceptance; reject-only recovery exempt)"],
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
    "f08": ["middleware/capability_router.py:payload_capabilities (workspace role increase; viewer downgrade exempt)", "api/workspace_routes.py:_require_workspace_use (actor and workspace owner; owned source/removal preserved)"],
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
    "b01": ["test_capability_route_policy.py::test_disabled_capability_blocks_every_registered_operation"],
    "b10": ["test_engine_capability_admission.py::test_denied_engine_admission_precedes_database_and_dispatch (guest/saved fields and structure)"],
    "d03": ["test_engine_capability_admission.py::test_candidate_rejection_is_recovery_but_acceptance_is_a_source_write", "test_engine_capability_admission.py::test_candidate_rejection_does_not_query_capabilities"],
    "c01": ["test_capability_route_policy.py::test_optimization_history_write_is_gated_but_restore_remains_recovery", "test_capability_route_policy.py::test_existing_optimization_restore_succeeds_while_source_edit_is_disabled"],
    "c05": ["test_capability_route_policy.py::test_global_compile_off_blocks_every_new_compile_admission", "test_capability_route_policy.py::test_developer_api_compile_uses_owner_capability_gate"],
    "i01": ["test_plan_catalog.py::test_purchase_capability_disables_new_checkout_without_hiding_billing_recovery"],
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
    "c01": "Historical pre-core-gating evidence only: source remained intact when unrelated optional tools were disabled. It does not verify the newly gateable c01/c05 controls.",
    "c03": "Find controls and keyboard search deny/enable according to refreshed grants.",
    "c04": "Editor keybinding selector denies/enables according to refreshed grants.",
    "c06": "Auto-compile control denies/enables with grants, then disappears on policy outage while source and manual compile survive.",
}


def client_grants(source: str, known_keys: set[str]) -> set[str]:
    """Recognize grant calls/gates, not arbitrary mentions in a source file."""
    candidates = re.findall(
        r"(?:can|canUseFeature|allows)\(\s*['\"]([a-z][a-z0-9_]*)['\"]|feature=['\"]([a-z][a-z0-9_]*)['\"]",
        source,
    )
    return {value for match in candidates for value in match if value in known_keys}


def declared_client_controls(known_keys: set[str], subfeature_keys: set[str]) -> dict[str, list[str]]:
    ui_text = (ROOT / "frontend/src/lib/capability-ui-policy.ts").read_text(encoding="utf-8")
    client: dict[str, list[str]] = {}
    for key, paths in re.findall(r"^\s*([a-z][a-z0-9_]*):\s*\[(.*)\],?$", ui_text, re.MULTILINE):
        if key not in known_keys:
            raise RuntimeError(f"Unknown declared client capability: {key}")
        relatives = re.findall(r"'([^']+)'", paths)
        if not relatives:
            raise RuntimeError(f"No declared client enforcement files: {key}")
        client[key] = []
        for relative in relatives:
            path = (ROOT / "frontend/src" / relative).resolve()
            if not path.is_file():
                raise RuntimeError(f"Missing client enforcement file: {key}: {relative}")
            # Child declarations must name a real grant call in their component.
            # Merely listing a leaf in this catalog is never enforcement proof.
            if key in subfeature_keys and key not in client_grants(path.read_text(encoding="utf-8"), known_keys):
                raise RuntimeError(f"Missing child client grant: {key}: {relative}")
            client[key].append(path.relative_to(ROOT).as_posix())
    for path in (ROOT / "frontend/src").rglob("*.tsx"):
        if "__tests__" in path.parts or "admin" in path.parts:
            continue
        for key in client_grants(path.read_text(encoding="utf-8"), known_keys):
            client.setdefault(key, []).append(path.relative_to(ROOT).as_posix())
    return {key: sorted(set(paths)) for key, paths in client.items()}


def generate() -> dict:
    catalog = json.loads((ROOT / "backend/app/core/capability_catalog.json").read_text(encoding="utf-8"))
    subfeatures = json.loads((ROOT / "backend/app/core/capability_subfeature_catalog.json").read_text(encoding="utf-8"))
    registry_ast = ast.parse((ROOT / "backend/app/core/feature_registry.py").read_text(encoding="utf-8"))
    parent_keys = {node.args[0].value for node in ast.walk(registry_ast)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == "FeatureDef" and node.args and isinstance(node.args[0], ast.Constant)}
    known_keys = parent_keys | {row["key"] for row in [*catalog, *subfeatures]}
    definitions = {row["key"]: row for row in [*catalog, *subfeatures]}
    def descendant_keys(key: str) -> set[str]:
        descendants = {key}
        for row in subfeatures:
            ancestor = row["parent_key"]
            seen = {row["key"]}
            while ancestor:
                if ancestor in seen or ancestor not in known_keys:
                    raise RuntimeError(f"Invalid subfeature ancestry: {row['key']}")
                seen.add(ancestor)
                if ancestor == key:
                    descendants.add(row["key"])
                ancestor = definitions.get(ancestor, {}).get("parent_key")
        return descendants
    policy_ast = ast.parse(POLICY.read_text(encoding="utf-8"))
    assignment = next(node for node in policy_ast.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "ROUTE_CAPABILITIES")
    routes = ast.literal_eval(assignment.value)
    for entries in routes.values():
        for keys in entries.values():
            unknown = set(keys) - known_keys
            if unknown:
                raise RuntimeError(f"Unknown route capabilities: {sorted(unknown)}")
    client = declared_client_controls(known_keys, {row["key"] for row in subfeatures})
    for key, refs in DYNAMIC.items():
        if key not in known_keys:
            raise RuntimeError(f"Unknown dynamic capability: {key}")
        for ref in refs:
            path, symbol = ref.split(":", 1)
            source = (ROOT / "backend/app" / path).read_text(encoding="utf-8")
            # References are inspectable wiring declarations; verify the actual
            # enforcement symbol still exists rather than counting quoted keys.
            names = symbol.split(" (", 1)[0].split("/")
            if not all(name.rsplit(".", 1)[-1] in source for name in names):
                raise RuntimeError(f"Missing dynamic enforcement symbol: {key}: {ref}")
    features = []
    for feature in [*catalog, *subfeatures]:
        key = feature["key"]
        operations = descendant_keys(key)
        handlers = [f"backend/app/api/{module}.py:{name}" for module, entries in routes.items() for name, keys in entries.items() if operations.intersection(keys)]
        dynamic = ["backend/app/" + ref for ref in DYNAMIC.get(key, [])]
        ui = sorted({path for operation in operations for path in client.get(operation, [])})
        tests = list(FOCUSED_TESTS.get(key, []))
        if key in {row["key"] for row in subfeatures}:
            tests.extend(["test_d14_capability_policy.py (leaf/ancestor axis intersection and sibling isolation)",
                          "test_d14_capability_routes.py (valid registered JSON/multipart admission and fail-on-use side-effect doubles)"])
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
            "controlKind": feature.get("control_kind", "product"),
            "productInventoryId": feature.get("product_inventory_id", feature["inventory_id"]),
            "operationCapabilities": sorted(operations),
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
    missing = [feature["key"] for feature in features if feature["verification"]["status"] == "MISSING_ENFORCEMENT"]
    if missing:
        raise RuntimeError(f"Missing enforcement: {missing}")
    products = [feature for feature in features if feature["controlKind"] == "product"]
    children = [feature for feature in features if feature["controlKind"] == "subfeature"]
    for feature in products:
        feature["subfeatures"] = [child for child in children if child["productInventoryId"] == feature["inventoryId"]]
    return {
        "schemaVersion": 3,
        "accountContexts": ["anonymous", "user", "support", "admin"],
        "rolePolicy": "global AND account role AND plan family AND exact SKU AND all ancestors; missing/unknown optional grants deny",
        "inventorySource": "backend/app/core/capability_catalog.json",
        "generator": "backend/scripts/generate_capability_matrix.py",
        "inventoryCount": len(products),
        "subfeatureSource": "backend/app/core/capability_subfeature_catalog.json",
        "subfeatureCount": len(children),
        "gateableCount": sum(feature["gateable"] for feature in products),
        "alwaysOnCount": sum(not feature["gateable"] for feature in products),
        "runtimeRegistryCount": len(known_keys),
        "runtimeGateableCount": len(parent_keys) + sum(feature["gateable"] for feature in features),
        "semantics": "Stop new admissions and external actions. Already admitted jobs retain existing completion/finalization/refund behavior; owners retain source/results/recovery/deletion/revocation. Previously issued presigned URLs last until expiry.",
        "verificationScope": "Automated policy, selected real-infrastructure admission/refund and existing regression coverage. Not a claim that all 129 features were manually QA-tested or that live providers/payments were exercised.",
        "features": products,
    }


if __name__ == "__main__":
    result = generate()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote {result['inventoryCount']} capabilities to {OUTPUT.relative_to(ROOT)}")
