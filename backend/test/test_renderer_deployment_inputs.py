"""Offline proof of durable, non-secret renderer inputs in automatic rollout."""

import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/deploy-modal.yml"
KEYS = ("MODAL_ENGINE_VM_CERTIFIED", "MODAL_ENGINE_VM_IMAGE_ID", "MODAL_ENGINE_VM_ASSETS_FINGERPRINT")
VALID = dict(zip(KEYS, ("true", "im-SyntheticRenderer", "a" * 64)))


def input_script():
    source = WORKFLOW.read_text(encoding="utf-8")
    marker = source.index("      - name: Validate renderer deployment inputs")
    start = source.index("        run: |\n", marker) + len("        run: |\n")
    end = source.index("\n      - name:", start)
    return textwrap.dedent(source[start:end])


def run_inputs(tmp_path, values):
    # Only run the workflow's pure input check; never import Modal or contact it.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python").symlink_to(sys.executable)
    env = {"PATH": f"{bin_dir}:{os.defpath}", **values}
    return subprocess.run(["bash", "-c", input_script() + '\nprintf "continued\\n"'],
                          env=env, capture_output=True, text=True, timeout=5)


def test_workflow_maps_all_inputs_to_every_modal_command_before_cloud_work():
    source = WORKFLOW.read_text(encoding="utf-8")
    job_env = source[source.index("    env:\n"):source.index("    steps:\n")]
    for key in KEYS:
        assert f"      {key}: ${{{{ vars.{key} }}}}" in job_env
        # A step-level override must not silently split preflight/deploy identity.
        assert source.count(f"{key}:") == 1
    check = source.index("- name: Validate renderer deployment inputs")
    install = source.index("- name: Install pinned Modal CLI")
    billing = source.index("modal run --env main modal_app.py::billing_preflight")
    renderer = source.index("modal run --env main modal_app.py::renderer_preflight")
    migration = source.index("modal run --env main modal_app.py::migrate")
    deploy = source.index('modal deploy --env main --strategy rolling --tag "$DEPLOY_SHA" modal_app.py::app')
    assert check < install < billing < renderer < migration < deploy
    step = source[check:install]
    assert "if: steps.freshness.outputs.current == 'true'" in step
    assert "continue-on-error" not in step and "always()" not in step
    for bypass in ("continue-on-error", "always()", "failure()", "cancelled()"):
        assert bypass not in source[check:]
    assert "secrets." not in step and "modal " not in step
    assert "secrets." not in "\n".join(line for line in job_env.splitlines() if "MODAL_ENGINE_VM_" in line)


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("value", [None, "", " ", "synthetic-private-invalid-input"])
def test_missing_or_invalid_inputs_fail_closed_without_echo(tmp_path, key, value):
    values = {**VALID}
    if value is None:
        del values[key]
    else:
        values[key] = value
    result = run_inputs(tmp_path, values)
    assert result.returncode == 1
    assert "continued" not in result.stdout
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["configuration_inputs_valid"] is False
    assert report["certification_verified"] is False
    assert "SyntheticRenderer" not in result.stdout
    assert "synthetic-private-invalid-input" not in result.stdout
    assert "a" * 64 not in result.stdout


@pytest.mark.parametrize("key,value", [
    (KEYS[0], "True"), (KEYS[0], "false"), (KEYS[0], "1"),
    (KEYS[1], "im-"), (KEYS[1], "im-" + "a" * 129), (KEYS[1], "im-valid\n"),
    (KEYS[2], "a" * 63), (KEYS[2], "a" * 65), (KEYS[2], "A" * 64),
    (KEYS[2], "g" * 64), (KEYS[2], "a" * 64 + "\n"),
])
def test_tuple_syntax_matches_runtime_fail_closed_contract(tmp_path, key, value):
    result = run_inputs(tmp_path, {**VALID, key: value})
    assert result.returncode == 1
    assert json.loads(result.stdout)["configuration_inputs_valid"] is False
    assert "continued" not in result.stdout


def test_well_formed_inputs_continue_without_claiming_certification(tmp_path):
    result = run_inputs(tmp_path, VALID)
    assert result.returncode == 0
    report, continued = result.stdout.splitlines()
    assert continued == "continued"
    assert json.loads(report) == {
        "configuration_inputs_valid": True,
        "certification_verified": False,
        "checks": {"operator_certification_asserted": True, "immutable_image_id_valid": True,
                   "asset_fingerprint_valid": True},
    }
    assert result.stderr == ""


def test_invoking_tuple_reaches_both_api_and_compile_worker_images(monkeypatch):
    for key, value in VALID.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("MODAL_BILLING_SECRET_NAME", "synthetic-billing-secret")
    tree = ast.parse((ROOT / "backend/modal_app.py").read_text(encoding="utf-8"))
    names = {"_billing_secret_name", "_billing_secret_binding_env", "_renderer_capability_env", "api_image", "latex_image"}
    nodes = [node for node in tree.body
             if (isinstance(node, ast.FunctionDef) and node.name == "_validated_optional_billing_secret_name")
             or (isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id in names for target in node.targets))]
    assert len(nodes) == 6

    class Image:
        def pip_install_from_requirements(self, *args, **kwargs):
            return Image()

        def add_local_dir(self, *args, **kwargs):
            return self

        def env(self, values):
            self.values = values
            return self

    namespace = {"os": os, "re": __import__("re"), "texlive_image": Image(),
                 "_BACKEND_DIR": ROOT / "backend", "_IGNORE": []}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "image_inputs", "exec"), namespace)
    for image_name in ("api_image", "latex_image"):
        assert namespace[image_name].values == {
            "PYTHONPATH": "/backend", "DEPLOY_TARGET": "modal",
            "MODAL_BILLING_SECRET_NAME": "synthetic-billing-secret", **VALID,
        }
    for function_name in ("run_latex_task", "run_orchestrator_task"):
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function_name)
        decorator = function.decorator_list[0]
        assert isinstance(decorator, ast.Call)
        image = next(keyword.value for keyword in decorator.keywords if keyword.arg == "image")
        assert isinstance(image, ast.Name) and image.id == "latex_image"
