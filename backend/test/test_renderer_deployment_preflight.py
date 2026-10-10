"""Configuration-only rollout guard; no cloud, provider, database or TeX calls."""
import ast
import builtins
import io
import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services.render_engine import backend, deployment_preflight

BACKEND = Path(__file__).resolve().parents[1]
VM_KEYS = ("MODAL_ENGINE_VM_CERTIFIED", "MODAL_ENGINE_VM_IMAGE_ID", "MODAL_ENGINE_VM_ASSETS_FINGERPRINT")


@pytest.fixture(autouse=True)
def bound_configuration(monkeypatch):
    monkeypatch.setenv("DEPLOY_TARGET", "modal")
    monkeypatch.setenv("LATEXY_RENDER_BACKEND", "native")
    for key in VM_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(deployment_preflight.settings, "ALLOWED_LATEX_COMPILERS", ["pdflatex", "xelatex", "lualatex"])
    monkeypatch.setattr(deployment_preflight.settings, "DEFAULT_LATEX_COMPILER", "pdflatex")
    monkeypatch.setattr(deployment_preflight.settings, "DEFAULT_NEW_RESUME_COMPILER", "lualatex")
    monkeypatch.setattr(backend, "renderer_fingerprint", lambda: "local-test-assets")
    create = MagicMock(side_effect=AssertionError("Preflight cannot create a VM"))
    monkeypatch.setattr(backend, "create_modal_engine", create)
    yield
    create.assert_not_called()


def valid_tuple(monkeypatch):
    monkeypatch.setenv(VM_KEYS[0], "true")
    monkeypatch.setenv(VM_KEYS[1], "im-SyntheticPrivateImage")
    monkeypatch.setenv(VM_KEYS[2], "a" * 64)


def test_default_configuration_without_vm_tuple_blocks_rollout():
    report = deployment_preflight.renderer_configuration_report()
    assert report["configuration_ready"] is False
    assert report["certification_verified"] is False
    assert report["checks"]["required_vm_configuration_valid"] is False
    assert report["reasons"] == ["lua_vm_configuration_missing_or_invalid"]


@pytest.mark.parametrize("key,value", [
    (VM_KEYS[0], None), (VM_KEYS[0], "false"), (VM_KEYS[0], "TRUE"),
    (VM_KEYS[1], None), (VM_KEYS[1], "unrecognized-image"),
    (VM_KEYS[2], None), (VM_KEYS[2], "a" * 63), (VM_KEYS[2], "g" * 64),
])
def test_partial_or_invalid_vm_tuple_blocks_rollout(monkeypatch, key, value):
    valid_tuple(monkeypatch)
    if value is None:
        monkeypatch.delenv(key)
    else:
        monkeypatch.setenv(key, value)
    report = deployment_preflight.renderer_configuration_report()
    assert report["configuration_ready"] is False
    assert report["reasons"] == ["lua_vm_configuration_missing_or_invalid"]


def test_well_formed_tuple_is_configuration_ready_only(monkeypatch):
    valid_tuple(monkeypatch)
    resolve = MagicMock(wraps=deployment_preflight.resolve_backend)
    monkeypatch.setattr(deployment_preflight, "resolve_backend", resolve)
    report = deployment_preflight.renderer_configuration_report()
    assert report["configuration_ready"] is True
    assert report["certification_verified"] is False
    assert all(report["checks"].values())
    assert report["reasons"] == []
    assert [call.args[0] for call in resolve.call_args_list] == ["lualatex", "pdflatex", "xelatex"]
    encoded = json.dumps(report)
    assert "SyntheticPrivateImage" not in encoded
    assert "a" * 64 not in encoded
    assert "local-test-assets" not in encoded


def test_accepted_lua_requires_tuple_even_with_non_lua_defaults(monkeypatch):
    monkeypatch.setattr(deployment_preflight.settings, "DEFAULT_NEW_RESUME_COMPILER", "pdflatex")
    assert deployment_preflight.renderer_configuration_report()["configuration_ready"] is False


def test_explicit_non_lua_profile_uses_existing_resolver_without_vm_tuple(monkeypatch):
    monkeypatch.setattr(deployment_preflight.settings, "ALLOWED_LATEX_COMPILERS", ["pdflatex", "xelatex"])
    monkeypatch.setattr(deployment_preflight.settings, "DEFAULT_NEW_RESUME_COMPILER", "pdflatex")
    report = deployment_preflight.renderer_configuration_report()
    assert report["configuration_ready"] is True
    assert report["certification_verified"] is False


@pytest.mark.parametrize("field,value", [
    ("ALLOWED_LATEX_COMPILERS", []),
    ("ALLOWED_LATEX_COMPILERS", ["pdflatex", "unsupported-private-value"]),
    ("DEFAULT_LATEX_COMPILER", "unsupported-private-value"),
    ("DEFAULT_NEW_RESUME_COMPILER", "unsupported-private-value"),
])
def test_invalid_compiler_profile_blocks_without_echoing_values(monkeypatch, field, value):
    valid_tuple(monkeypatch)
    monkeypatch.setattr(deployment_preflight.settings, field, value)
    report = deployment_preflight.renderer_configuration_report()
    assert report["configuration_ready"] is False
    assert "compiler_configuration_invalid" in report["reasons"]
    assert "unsupported-private-value" not in json.dumps(report)


def test_non_modal_runtime_cannot_attest_modal_configuration(monkeypatch):
    valid_tuple(monkeypatch)
    monkeypatch.setenv("DEPLOY_TARGET", "local")
    report = deployment_preflight.renderer_configuration_report()
    assert report["configuration_ready"] is False
    assert report["reasons"] == ["modal_runtime_required"]


def test_resolver_failure_is_a_fixed_reason_without_exception_text(monkeypatch):
    valid_tuple(monkeypatch)
    monkeypatch.setattr(deployment_preflight, "resolve_backend", MagicMock(side_effect=RuntimeError("private-input-sentinel")))
    report = deployment_preflight.renderer_configuration_report()
    assert report["configuration_ready"] is False
    assert report["reasons"] == ["renderer_configuration_unavailable"]
    assert "private-input-sentinel" not in json.dumps(report)


def extracted_wrapper():
    tree = ast.parse((BACKEND / "modal_app.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "renderer_preflight")
    function.decorator_list = []
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), "renderer_preflight", "exec"), namespace)
    return namespace["renderer_preflight"]


def test_modal_wrapper_blocks_and_reports_only_safe_diagnostics(capsys):
    with pytest.raises(RuntimeError, match="blocked deployment"):
        extracted_wrapper()()
    report = json.loads(capsys.readouterr().out)
    assert report["configuration_ready"] is False
    assert report["certification_verified"] is False


def test_modal_wrapper_reports_configuration_success_without_certification(monkeypatch, capsys):
    valid_tuple(monkeypatch)
    report = extracted_wrapper()()
    assert report["configuration_ready"] is True
    assert report["certification_verified"] is False
    assert json.loads(capsys.readouterr().out) == report


def test_modal_wrapper_sanitizes_unexpected_configuration_failures(monkeypatch, capsys):
    monkeypatch.setattr(deployment_preflight, "renderer_configuration_report",
                        MagicMock(side_effect=ValueError("private-input-sentinel")))
    with pytest.raises(RuntimeError, match="preflight failed") as error:
        extracted_wrapper()()
    assert error.value.__suppress_context__ is True
    report = json.loads(capsys.readouterr().out)
    assert report == {"configuration_ready": False, "certification_verified": False,
                      "reasons": ["configuration_check_failed"]}


@pytest.mark.parametrize("phase", ["import", "report"])
@pytest.mark.parametrize("fails", [False, True])
def test_modal_wrapper_contains_startup_output_and_restores_state(monkeypatch, capsys, phase, fails):
    valid_tuple(monkeypatch)
    wrapper = extracted_wrapper()
    original_import = builtins.__import__
    original_report = deployment_preflight.renderer_configuration_report
    original_stdout, original_stderr = sys.stdout, sys.stderr
    original_logging_disable = logging.root.manager.disable
    previous_disable = logging.ERROR
    logger = logging.getLogger("preflight.synthetic.startup")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    retained_stream = io.StringIO()
    handlers = [logging.StreamHandler(original_stderr), logging.StreamHandler(retained_stream)]
    for handler in handlers:
        logger.addHandler(handler)

    def startup_output():
        print("synthetic-private-stdout")
        print("synthetic-private-stderr", file=sys.stderr)
        # Existing handlers hold their old stream references. Include a custom
        # level above CRITICAL so suppression does not depend on usual levels.
        logger.log(logging.CRITICAL + 10, "synthetic-private-log")
        if fails:
            raise ValueError("synthetic-private-exception")

    def checked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if phase == "import" and name == "app.services.render_engine.deployment_preflight":
            startup_output()
        return original_import(name, globals, locals, fromlist, level)

    def noisy_report():
        if phase == "report":
            startup_output()
        return original_report()

    monkeypatch.setattr(builtins, "__import__", checked_import)
    monkeypatch.setattr(deployment_preflight, "renderer_configuration_report", noisy_report)
    try:
        logging.disable(previous_disable)
        if fails:
            with pytest.raises(RuntimeError, match="preflight failed") as error:
                wrapper()
            assert error.value.__suppress_context__ is True
        else:
            assert wrapper()["configuration_ready"] is True
        assert sys.stdout is original_stdout
        assert sys.stderr is original_stderr
        assert logging.root.manager.disable == previous_disable
    finally:
        logging.disable(original_logging_disable)
        for handler in handlers:
            logger.removeHandler(handler)
            handler.close()
    captured = capsys.readouterr()
    assert captured.err == ""
    assert retained_stream.getvalue() == ""
    assert "synthetic-private" not in captured.out
    report = json.loads(captured.out)
    assert report["configuration_ready"] is (not fails)
    assert report["certification_verified"] is False


def test_workflow_checks_existing_api_binding_before_migrations_and_deployment():
    workflow = (BACKEND.parent / ".github/workflows/deploy-modal.yml").read_text(encoding="utf-8")
    preflight = workflow.index("modal run --env main modal_app.py::renderer_preflight")
    migration = workflow.index("modal run --env main modal_app.py::migrate")
    deploy = workflow.index('modal deploy --env main --strategy rolling --tag "$DEPLOY_SHA" modal_app.py')
    assert preflight < migration < deploy
    step = workflow[workflow.rfind("      - name:", 0, preflight):preflight]
    assert "if: steps.freshness.outputs.current == 'true'" in step
    assert "working-directory: backend" in step
    assert "continue-on-error" not in step
    tree = ast.parse((BACKEND / "modal_app.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "renderer_preflight")
    decorator = function.decorator_list[0]
    assert isinstance(decorator, ast.Call)
    keywords = {item.arg: item.value for item in decorator.keywords}
    assert isinstance(keywords["image"], ast.Name) and keywords["image"].id == "api_image"
    assert isinstance(keywords["secrets"], ast.Name) and keywords["secrets"].id == "_secrets"
    assert ast.literal_eval(keywords["timeout"]) == 60
