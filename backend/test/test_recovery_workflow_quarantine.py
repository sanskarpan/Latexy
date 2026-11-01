"""Offline checks for the canonical stopped-App -> primary freeze sequence."""

import ast
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
import yaml

from scripts.modal_operation_authorization import KEY_ENV, mint_proof

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
    assert "scripts.modal_operation_authorization" in freeze["run"]
    assert freeze["run"].index("verify_modal_drain.py") < freeze["run"].index("scripts.modal_operation_authorization")
    assert freeze["env"]["MODAL_RECOVERY_OPERATION_SIGNING_KEY"] == "${{ secrets.MODAL_RECOVERY_OPERATION_SIGNING_KEY }}"
    assert "::add-mask::$token" in freeze["run"]
    assert "--authorization-token \"$token\"" in freeze["run"]
    assert '--expected-deploy-sha "$DEPLOY_SHA" --max-age-seconds 300' in freeze["run"]


@pytest.mark.parametrize(("operation", "operation_id_kwarg", "helper"), [
    ("freeze_redis_recovery", "freeze_id", "freeze_primary_for_recovery"),
    ("handover_redis_recovery", "handover_id", "handover_spare_for_recovery"),
])
def test_operator_wrapper_is_separate_bounded_and_calls_existing_helper(operation, operation_id_kwarg, helper):
    tree = ast.parse((ROOT / "backend/modal_app.py").read_text(encoding="utf-8"))
    source = (ROOT / "backend/modal_app.py").read_text(encoding="utf-8")
    wrapper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == operation)
    decorator = wrapper.decorator_list[0]
    assert ast.unparse(decorator.func) == "operations_app.function"
    assert {keyword.arg: ast.unparse(keyword.value) for keyword in decorator.keywords} == {
        "image": "migrate_image", "secrets": "_operations_secrets", "timeout": "90",
    }
    migrate = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "migrate")
    migrate_decorator = migrate.decorator_list[0]
    assert {keyword.arg: ast.unparse(keyword.value) for keyword in migrate_decorator.keywords} == {
        "image": "migrate_image", "secrets": "_operations_secrets", "timeout": "900",
    }
    verifier = next(node for node in ast.walk(migrate) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == "verify_proof")
    assert ast.unparse(verifier.args[0]) == "authorization_token"
    assert "verify_proof" in ast.unparse(wrapper)
    verify_call = next(node for node in ast.walk(wrapper) if isinstance(node, ast.Call)
                       and isinstance(node.func, ast.Name) and node.func.id == "verify_proof")
    assert ast.unparse(verify_call.keywords[1].value) == operation_id_kwarg
    assert source.index("verify_proof(authorization_token", source.index(f"def {operation}")) < source.index(
        "from app.database.connection", source.index(f"def {operation}")
    )
    helper_import = next(node for node in ast.walk(wrapper)
                        if isinstance(node, ast.ImportFrom) and node.module == "scripts.redis_recovery_quarantine")
    assert [alias.name for alias in helper_import.names] == [helper]
    migrate = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "migrate")
    migrate_verify = next(node for node in ast.walk(migrate) if isinstance(node, ast.Call)
                          and isinstance(node.func, ast.Name) and node.func.id == "verify_proof")
    migrate_run = next(node for node in ast.walk(migrate) if isinstance(node, ast.Call)
                       and isinstance(node.func, ast.Attribute) and node.func.attr == "run")
    assert migrate_verify.lineno < migrate_run.lineno
    assert "source_revision != os.environ.get(\"DEPLOY_SHA\")" in source
    operations_secrets = next(node for node in tree.body if isinstance(node, ast.Assign)
                              and any(isinstance(target, ast.Name) and target.id == "_operations_secrets"
                                      for target in node.targets))
    assert [name for name in ast.walk(operations_secrets) if isinstance(name, ast.Name)]
    assert "latexy-recovery-ops-20261027" in source
    assert "_operations_secrets" in ast.unparse(operations_secrets)
    helper_tree = ast.parse((ROOT / "backend/scripts/redis_recovery_quarantine.py").read_text(encoding="utf-8"))
    defined = {node.name for node in helper_tree.body if isinstance(node, ast.AsyncFunctionDef)}
    imported = next(
        node for node in ast.walk(wrapper)
        if isinstance(node, ast.ImportFrom) and node.module == "scripts.redis_recovery_quarantine"
    )
    assert all(alias.name in defined for alias in imported.names)


def test_unheld_api_checks_frozen_authority_before_admin_or_redis_initialization():
    source = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    assert source.index("await require_active_authority(session)") < source.index("admin_emails =")
    assert source.index("await require_active_authority(session)") < source.index("await redis_manager.init_redis()")
    assert "if not app.state.deployment_traffic_held:" in source


@pytest.mark.parametrize("operation", ["migrate", "freeze_redis_recovery", "handover_redis_recovery"])
def test_remote_operation_rejects_unsigned_call_before_database_or_subprocess(operation):
    tree = ast.parse((ROOT / "backend/modal_app.py").read_text(encoding="utf-8"))
    wrapper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == operation)
    wrapper.decorator_list = []
    namespace = {}
    exec(compile(ast.Module(body=[wrapper], type_ignores=[]), "isolated-modal-operation", "exec"), namespace)
    environment = {
        "MODAL_ENVIRONMENT": "main", "MODAL_DEPLOYMENT_TRAFFIC_HOLD": "true",
        "DEPLOY_SHA": "a" * 40, "MODAL_REDIS_SECRET_NAME": "synthetic-held-redis",
        KEY_ENV: "b" * 64,
    }
    arguments = {"source_revision": "a" * 40, "authorization_token": "unsigned"}
    if operation == "freeze_redis_recovery":
        arguments["freeze_id"] = str(uuid4())
    if operation == "handover_redis_recovery":
        arguments["handover_id"] = str(uuid4())
    fake_modal = types.SimpleNamespace(is_local=lambda: False)
    with patch.dict(os.environ, environment, clear=True), patch.dict(sys.modules, {"modal": fake_modal}), patch("subprocess.run") as run:
        with pytest.raises(RuntimeError, match="authorization was not verified"):
            namespace[operation](**arguments)
        run.assert_not_called()


def test_remote_freeze_rejects_signed_proof_for_a_different_operation_uuid():
    tree = ast.parse((ROOT / "backend/modal_app.py").read_text(encoding="utf-8"))
    wrapper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "freeze_redis_recovery")
    wrapper.decorator_list = []
    namespace = {}
    exec(compile(ast.Module(body=[wrapper], type_ignores=[]), "isolated-modal-operation", "exec"), namespace)
    environment = {
        "MODAL_ENVIRONMENT": "main", "MODAL_DEPLOYMENT_TRAFFIC_HOLD": "true",
        "DEPLOY_SHA": "a" * 40, "MODAL_REDIS_SECRET_NAME": "synthetic-held-redis",
        KEY_ENV: "b" * 64,
    }
    signed_id = str(uuid4())
    proof = mint_proof(action="freeze", sha="a" * 40, app_id="ap-abcdefghijklmnopqrstuv",
                       redis_secret_name="synthetic-held-redis", freeze_id=signed_id, environ=environment)
    with patch.dict(os.environ, environment, clear=True), patch.dict(sys.modules, {"modal": types.SimpleNamespace(is_local=lambda: False)}):
        with pytest.raises(RuntimeError, match="authorization was not verified"):
            namespace["freeze_redis_recovery"](source_revision="a" * 40, freeze_id=str(uuid4()), authorization_token=proof)


def test_remote_handover_rejects_signed_proof_for_a_different_operation_uuid():
    tree = ast.parse((ROOT / "backend/modal_app.py").read_text(encoding="utf-8"))
    wrapper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "handover_redis_recovery")
    wrapper.decorator_list = []
    namespace = {}
    exec(compile(ast.Module(body=[wrapper], type_ignores=[]), "isolated-modal-operation", "exec"), namespace)
    environment = {
        "MODAL_ENVIRONMENT": "main", "MODAL_DEPLOYMENT_TRAFFIC_HOLD": "true",
        "DEPLOY_SHA": "a" * 40, "MODAL_REDIS_SECRET_NAME": "synthetic-held-redis",
        KEY_ENV: "b" * 64,
    }
    signed_id = str(uuid4())
    proof = mint_proof(action="handover", sha="a" * 40, app_id="ap-abcdefghijklmnopqrstuv",
                       redis_secret_name="synthetic-held-redis", handover_id=signed_id, environ=environment)
    with patch.dict(os.environ, environment, clear=True), patch.dict(sys.modules, {"modal": types.SimpleNamespace(is_local=lambda: False)}):
        with pytest.raises(RuntimeError, match="authorization was not verified"):
            namespace["handover_redis_recovery"](source_revision="a" * 40, handover_id=str(uuid4()), authorization_token=proof)
