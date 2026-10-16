"""Static guards for the Modal cutover traffic hold and explicit release path."""

from __future__ import annotations

import ast
import functools
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
MODAL_APP = BACKEND / "modal_app.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-modal.yml"


def _source_tree() -> tuple[str, ast.Module]:
    source = MODAL_APP.read_text(encoding="utf-8")
    return source, ast.parse(source)


def _decorator_name(decorator: ast.expr) -> str | None:
    if isinstance(decorator, ast.Name):
        return decorator.id
    if isinstance(decorator, ast.Call):
        if isinstance(decorator.func, ast.Attribute):
            base = decorator.func.value
            if isinstance(base, ast.Name):
                return f"{base.id}.{decorator.func.attr}"
        if isinstance(decorator.func, ast.Name):
            return decorator.func.id
    return None


def test_traffic_hold_is_baked_into_all_four_modal_images() -> None:
    _, tree = _source_tree()
    image_envs = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "env":
            continue
        if not node.args or not isinstance(node.args[0], ast.Dict):
            continue
        keys = [key.value for key in node.args[0].keys if isinstance(key, ast.Constant)]
        if "MODAL_DEPLOYMENT_TRAFFIC_HOLD" in keys:
            image_envs.append(keys)
    assert len(image_envs) == 4  # API, LaTeX, worker and migration images.
    assert all(keys.count("MODAL_DEPLOYMENT_TRAFFIC_HOLD") == 1 for keys in image_envs)


def test_every_modal_worker_and_scheduler_entrypoint_has_the_outer_guard() -> None:
    _, tree = _source_tree()
    app_functions = []
    operation_functions = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = {_decorator_name(decorator) for decorator in node.decorator_list}
        if "app.function" in decorators:
            app_functions.append(node)
        if "operations_app.function" in decorators:
            operation_functions.append(node)

    workers = [node for node in app_functions if node.name != "fastapi_app"]
    assert len(workers) >= 20
    assert all(any(_decorator_name(decorator) == "_require_worker_dispatch" for decorator in node.decorator_list)
               for node in workers)
    assert not any(any(_decorator_name(decorator) == "_require_worker_dispatch" for decorator in node.decorator_list)
                   for node in operation_functions)
    assert {node.name for node in operation_functions} >= {
        "renderer_preflight", "migrate", "billing_preflight", "sync_templates",
    }


def test_worker_guard_rejects_held_calls_before_business_code() -> None:
    _, tree = _source_tree()
    decorator = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_require_worker_dispatch"
    )
    isolated = ast.Module(body=[decorator], type_ignores=[])
    namespace = {"wraps": functools.wraps, "_DEPLOYMENT_TRAFFIC_HELD": True}
    exec(compile(ast.fix_missing_locations(isolated), str(MODAL_APP), "exec"), namespace)
    business_calls = []

    @namespace["_require_worker_dispatch"]
    def fake_worker():
        business_calls.append("ran")

    try:
        fake_worker()
    except RuntimeError as exc:
        assert str(exc) == "Modal deployment traffic is held; worker execution is paused"
    else:
        raise AssertionError("held worker call was admitted")
    assert business_calls == []

    namespace["_DEPLOYMENT_TRAFFIC_HELD"] = False
    @namespace["_require_worker_dispatch"]
    def released_worker():
        business_calls.append("ran")

    released_worker()
    assert business_calls == ["ran"]


def test_scheduled_functions_suppress_registration_in_held_mode() -> None:
    _, tree = _source_tree()
    scheduled = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "function":
            continue
        for keyword in node.keywords:
            if keyword.arg == "schedule":
                scheduled.append(keyword.value)
    assert len(scheduled) == 5
    assert all(
        isinstance(value, ast.IfExp)
        and isinstance(value.test, ast.Name)
        and value.test.id == "_DEPLOYMENT_TRAFFIC_HELD"
        and isinstance(value.body, ast.Constant)
        and value.body.value is None
        for value in scheduled
    )


def test_workflow_defaults_to_held_and_only_manual_release_can_open_traffic() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "traffic_mode:" in source
    assert "default: held" in source
    assert "- held\n          - release" in source
    assert "github.event_name != 'workflow_dispatch' || inputs.traffic_mode != 'release'" in source
    assert "MODAL_TRAFFIC_RELEASE_APPROVED_SHA: ${{ vars.MODAL_TRAFFIC_RELEASE_APPROVED_SHA }}" in source
    assert "github.event_name == 'workflow_run'" in source
    assert "Automatic held deployment skipped because this exact SHA is approved" in source


def test_release_requires_same_sha_and_healthy_held_deployment_before_migration() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    release_guard = source.index("Require approved SHA and healthy held candidate before release")
    migration = source.index("Apply production database migrations")
    deploy = source.index("modal deploy --env main --strategy rolling --tag")
    assert release_guard < migration < deploy
    guard = source[release_guard:migration]
    assert "inputs.traffic_mode == 'release'" in guard
    assert '"${MODAL_TRAFFIC_RELEASE_APPROVED_SHA:-}" != "$DEPLOY_SHA"' in guard
    assert "verify_modal_deployment_identity.py --environment main --expected-sha \"$DEPLOY_SHA\"" in guard
    assert "x-latexy-deployment-hold" in guard
    assert "true[[:space:]]*$" in guard
    assert "check_health /health healthy" in guard
    assert "check_health /readyz ready" in guard
    assert "check_health /jobs/health healthy" in guard


def test_postdeploy_health_checks_verify_the_selected_hold_header() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    health = source[source.index("Verify production backend health"):]
    assert 'local expected_hold="$MODAL_DEPLOYMENT_TRAFFIC_HOLD"' in health
    assert "x-latexy-deployment-hold" in health
    assert "check_health /health healthy" in health
    assert "check_health /readyz ready" in health
    assert "check_health /jobs/health healthy" in health
