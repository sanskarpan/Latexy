"""Offline checks for the canonical stopped-App -> primary freeze sequence."""

import ast
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/deploy-modal.yml"


def _steps():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["deploy"]["steps"]


def _input_check(environment):
    step = next(item for item in _steps() if item["name"] == "Validate held-only Redis binding before provider operations")
    code = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    with patch.dict(os.environ, environment, clear=True):
        exec(compile(code, "workflow-recovery-inputs", "exec"), {})


def test_recovery_requires_explicit_canonical_identity_before_provider_steps():
    base = {"MODAL_ENVIRONMENT": "main", "MODAL_DEPLOYMENT_TRAFFIC_HOLD": "true"}
    _input_check(base)
    alternate = {**base, "MODAL_REDIS_SECRET_NAME": "synthetic-held-redis"}
    with pytest.raises(SystemExit, match="canonical freeze UUID"):
        _input_check(alternate)
    _input_check({**alternate, "MODAL_REDIS_RECOVERY_FREEZE_ID": str(uuid4())})
    with pytest.raises(ValueError, match="alternate Redis Modal secret"):
        _input_check({
            **alternate, "MODAL_DEPLOYMENT_TRAFFIC_HOLD": "false", "DEPLOY_SHA": "a" * 40,
            "MODAL_TRAFFIC_RELEASE_APPROVED_SHA": "a" * 40,
            "MODAL_REDIS_RECOVERY_FREEZE_ID": str(uuid4()),
        })


def test_freeze_rechecks_drain_after_migration_before_serving_or_template_writes():
    steps = _steps()
    names = [item["name"] for item in steps]
    freeze_name = "Freeze primary authority before held backup qualification"
    freeze = steps[names.index(freeze_name)]
    assert "'held-cutover'" in freeze["if"]
    assert "env.MODAL_REDIS_SECRET_NAME != ''" in freeze["if"]
    assert "env.MODAL_REDIS_SECRET_NAME != 'latexy-redis'" in freeze["if"]
    assert names.index("Apply production database migrations after external drain verification") < names.index(freeze_name)
    assert names.index(freeze_name) < names.index("Deploy backend with a rolling update")
    assert names.index(freeze_name) < names.index("Synchronize source-owned production templates")
    assert freeze["run"].index("verify_modal_drain.py") < freeze["run"].index("modal_app.py::freeze_redis_recovery")
    assert '--expected-deploy-sha "$DEPLOY_SHA" --max-age-seconds 300' in freeze["run"]


def test_operator_wrapper_is_separate_bounded_and_calls_existing_helper():
    tree = ast.parse((ROOT / "backend/modal_app.py").read_text(encoding="utf-8"))
    wrapper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "freeze_redis_recovery")
    decorator = wrapper.decorator_list[0]
    assert ast.unparse(decorator.func) == "operations_app.function"
    assert {keyword.arg: ast.unparse(keyword.value) for keyword in decorator.keywords} == {
        "image": "migrate_image", "secrets": "_secrets", "timeout": "90",
    }
    helper_tree = ast.parse((ROOT / "backend/scripts/redis_recovery_quarantine.py").read_text(encoding="utf-8"))
    defined = {node.name for node in helper_tree.body if isinstance(node, ast.AsyncFunctionDef)}
    imported = next(
        node for node in ast.walk(wrapper)
        if isinstance(node, ast.ImportFrom) and node.module == "scripts.redis_recovery_quarantine"
    )
    assert all(alias.name in defined for alias in imported.names)


def test_unheld_api_checks_frozen_authority_before_admin_or_redis_initialization():
    source = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    assert source.index("await require_primary_authority_active(session)") < source.index("admin_emails =")
    assert source.index("await require_primary_authority_active(session)") < source.index("await redis_manager.init_redis()")
    assert "if not app.state.deployment_traffic_held:" in source
