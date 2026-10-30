"""Pure tests for the held-only Modal Redis secret selector."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.deployment_hold import (
    DEFAULT_MODAL_REDIS_SECRET_NAME,
    MODAL_REDIS_SECRET_NAME_ENV,
    deployment_traffic_held,
    modal_redis_secret_name,
)


def test_redis_secret_label_defaults_and_validates_without_normalizing_or_echoing() -> None:
    assert modal_redis_secret_name() == DEFAULT_MODAL_REDIS_SECRET_NAME
    assert modal_redis_secret_name("") == DEFAULT_MODAL_REDIS_SECRET_NAME
    assert modal_redis_secret_name("latexy-recovery_20261027") == "latexy-recovery_20261027"
    for invalid in (" ", " leading", "trailing ", "../redis", "bad/name", "x" * 65, "bad\nname"):
        with pytest.raises(ValueError) as exc:
            modal_redis_secret_name(invalid)
        assert str(exc.value) == "MODAL_REDIS_SECRET_NAME must be a valid Modal secret label"


@pytest.mark.parametrize("source_deployment", [False, True])
def test_alternate_redis_secret_requires_explicit_hold_even_with_release_approval(source_deployment: bool) -> None:
    env = {
        MODAL_REDIS_SECRET_NAME_ENV: "latexy-recovery",
        "MODAL_ENVIRONMENT": "main",
        "MODAL_DEPLOYMENT_TRAFFIC_HOLD": "false",
        "DEPLOY_SHA": "a" * 40,
        "MODAL_TRAFFIC_RELEASE_APPROVED_SHA": "a" * 40,
    }
    with pytest.raises(ValueError, match="alternate Redis Modal secret requires MODAL_DEPLOYMENT_TRAFFIC_HOLD=true"):
        deployment_traffic_held(env, source_deployment=source_deployment)


def test_alternate_redis_secret_requires_explicit_true_not_missing_or_unknown_hold() -> None:
    for hold in (None, "", "unknown"):
        env = {MODAL_REDIS_SECRET_NAME_ENV: "latexy-recovery"}
        if hold is not None:
            env["MODAL_DEPLOYMENT_TRAFFIC_HOLD"] = hold
        with pytest.raises(ValueError, match="alternate Redis Modal secret requires MODAL_DEPLOYMENT_TRAFFIC_HOLD=true"):
            deployment_traffic_held(env)
    assert deployment_traffic_held({
        MODAL_REDIS_SECRET_NAME_ENV: "latexy-recovery",
        "MODAL_DEPLOYMENT_TRAFFIC_HOLD": "true",
    }) is True


def test_all_modal_images_bake_the_validated_selector_label() -> None:
    source = Path(__file__).resolve().parents[1] / "modal_app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    images = {"api_image", "latex_image", "worker_image", "migrate_image"}
    found: dict[str, ast.AST] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if not images.intersection(names):
            continue
        for call in ast.walk(node.value):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute) or call.func.attr != "env":
                continue
            if not call.args or not isinstance(call.args[0], ast.Dict):
                continue
            entries = list(zip(call.args[0].keys, call.args[0].values))
            has_selector = any(
                (isinstance(key, ast.Constant) and key.value == "MODAL_REDIS_SECRET_NAME")
                or (key is None and isinstance(value, ast.Name)
                    and value.id == "_redis_secret_binding_env")
                for key, value in entries
            )
            assert has_selector
            found.update({name: node for name in images.intersection(names)})
    assert found.keys() == images


def test_held_api_startup_skips_admin_bootstrap_write() -> None:
    main_source = Path(__file__).resolve().parents[1] / "app" / "main.py"
    tree = ast.parse(main_source.read_text(encoding="utf-8"))
    bootstrap = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "admin_emails" for target in node.targets)
    )
    assert isinstance(bootstrap.value, ast.IfExp)
    assert isinstance(bootstrap.value.test, ast.Attribute)
    assert isinstance(bootstrap.value.test.value, ast.Attribute)
    assert bootstrap.value.test.value.attr == "state"
    assert bootstrap.value.test.attr == "deployment_traffic_held"
    assert isinstance(bootstrap.value.body, ast.Call)
    assert isinstance(bootstrap.value.body.func, ast.Name) and bootstrap.value.body.func.id == "set"
