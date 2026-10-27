"""Proposed static and synthetic tests for Modal hold-secret precedence.

The test parses modal_app.py and models opaque secrets with fake mappings. It
does not import Modal, access configured secrets, or contact a provider.
"""
from __future__ import annotations

import ast
from pathlib import Path

MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"


def _source_tree() -> tuple[str, ast.Module]:
    source = MODAL_APP.read_text(encoding="utf-8")
    return source, ast.parse(source)


def _assignment(tree: ast.Module, name: str) -> ast.Assign:
    return next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    )


def _modal_secret_call(node: ast.AST, method: str) -> ast.Call | None:
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == method
            and isinstance(child.func.value, ast.Attribute)
            and isinstance(child.func.value.value, ast.Name)
            and child.func.value.value.id == "modal"
            and child.func.value.attr == "Secret"
        ):
            return child
    return None


def _secret_names(node: ast.AST) -> list[str]:
    names = []
    for child in ast.walk(node):
        if not (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "from_name"
            and isinstance(child.func.value, ast.Attribute)
            and isinstance(child.func.value.value, ast.Name)
            and child.func.value.value.id == "modal"
            and child.func.value.attr == "Secret"
        ):
            continue
        assert len(child.args) == 1 and isinstance(child.args[0], ast.Constant)
        names.append(child.args[0].value)
    return names


def _hold_append_targets(tree: ast.Module) -> list[str]:
    targets = []
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "append"
            and isinstance(call.func.value, ast.Name)
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id == "_deployment_hold_secret"
        ):
            targets.append(call.func.value.id)
    return targets


class FakeSecret:
    def __init__(self, name: str, env_dict: dict[str, str]):
        self.name = name
        self.env_dict = dict(env_dict)


class FakeModalSecretFactory:
    def __init__(self, opaque_secrets: dict[str, dict[str, str]]):
        self.opaque_secrets = opaque_secrets
        self.captured_dicts: list[dict[str, str]] = []

    def from_name(self, name: str) -> FakeSecret:
        return FakeSecret(name, self.opaque_secrets.get(name, {}))

    def from_dict(self, env_dict: dict[str, str]) -> FakeSecret:
        self.captured_dicts.append(dict(env_dict))
        return FakeSecret("deployment-hold-override", env_dict)


def _merged_env(secrets: list[FakeSecret]) -> dict[str, str]:
    result: dict[str, str] = {}
    for secret in secrets:
        result.update(secret.env_dict)
    return result


def _execute_secret_assembly(tree: ast.Module, opaque: dict[str, dict[str, str]], hold: str) -> dict[str, object]:
    """Execute the actual top-level list assembly with synthetic Modal secrets."""
    assembly_names = {"_base_secrets", "_api_secrets", "_redis_secret", "_secrets", "_deployment_hold_secret"}
    nodes: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in assembly_names for target in node.targets
        ):
            nodes.append(node)
        elif isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "_billing_secret_name":
            nodes.append(node)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if (isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
                    and call.func.value.id in {"_secrets", "_api_secrets"}):
                nodes.append(node)

    fake_modal = FakeModalSecretFactory(opaque)
    namespace: dict[str, object] = {
        "ast": ast,
        "modal": type("FakeModal", (), {"Secret": fake_modal})(),
        "_billing_secret_name": "qa-billing-overlay",
        "_redis_secret_name": "backup-redis",
        "_DEPLOYMENT_TRAFFIC_HOLD_VALUE": hold,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "secret_assembly", "exec"), namespace)
    namespace["_fake_modal"] = fake_modal
    return namespace


def test_hold_binding_is_a_single_canonical_override_after_every_other_secret() -> None:
    _, tree = _source_tree()
    hold_assignment = _assignment(tree, "_deployment_hold_secret")
    call = _modal_secret_call(hold_assignment, "from_dict")
    assert call is not None and len(call.args) == 1
    binding = call.args[0]
    assert isinstance(binding, ast.Dict) and len(binding.keys) == 2
    bindings = {key.value: value for key, value in zip(binding.keys, binding.values)}
    assert set(bindings) == {"MODAL_DEPLOYMENT_TRAFFIC_HOLD", "MODAL_REDIS_SECRET_NAME"}
    assert isinstance(bindings["MODAL_DEPLOYMENT_TRAFFIC_HOLD"], ast.Name)
    assert bindings["MODAL_DEPLOYMENT_TRAFFIC_HOLD"].id == "_DEPLOYMENT_TRAFFIC_HOLD_VALUE"
    assert isinstance(bindings["MODAL_REDIS_SECRET_NAME"], ast.Name)
    assert bindings["MODAL_REDIS_SECRET_NAME"].id == "_redis_secret_name"
    assert _hold_append_targets(tree) == ["_secrets", "_api_secrets"]

    api_assignment = _assignment(tree, "_api_secrets")
    assert isinstance(api_assignment.value, ast.List)
    assert len(api_assignment.value.elts) == 1
    assert isinstance(api_assignment.value.elts[0], ast.Starred)
    assert isinstance(api_assignment.value.elts[0].value, ast.Name)
    assert api_assignment.value.elts[0].value.id == "_base_secrets"
    billing_overlay = next(
        node for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "_billing_secret_name"
    )
    api_hold_append = next(
        node for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "_api_secrets"
        and node.value.func.attr == "append"
        and node.value.args
        and isinstance(node.value.args[0], ast.Name)
        and node.value.args[0].id == "_deployment_hold_secret"
    )
    assert billing_overlay.lineno < api_hold_append.lineno


def test_fake_conflicting_secrets_cannot_override_held_or_released_choice() -> None:
    _, tree = _source_tree()
    base_names = _secret_names(_assignment(tree, "_base_secrets"))
    assert base_names == [
        "latexy-backend-secrets", "latexy-storage",
    ]

    # Fake opaque values deliberately conflict with both possible deployment
    # choices. These mappings are test fixtures, not reads of Modal secrets.
    for chosen in ("true", "false"):
        opaque = {
            "latexy-backend-secrets": {
                "MODAL_DEPLOYMENT_TRAFFIC_HOLD": "false" if chosen == "true" else "true",
                "MODAL_REDIS_SECRET_NAME": "wrong-base-label",
                "REDIS_URL": "redis://legacy-primary", "REDIS_PASSWORD": "legacy-pass",
            },
            "latexy-storage": {"STORAGE_FIXTURE": "value"},
            "backup-redis": {
                "MODAL_REDIS_SECRET_NAME": "wrong-redis-label",
                "REDIS_URL": "redis://backup", "REDIS_PASSWORD": "backup-pass",
            },
            "qa-billing-overlay": {
                "MODAL_DEPLOYMENT_TRAFFIC_HOLD": "false" if chosen == "true" else "true",
                "MODAL_REDIS_SECRET_NAME": "wrong-billing-label",
                "REDIS_URL": "redis://billing-override", "REDIS_PASSWORD": "billing-pass",
            },
        }
        namespace = _execute_secret_assembly(tree, opaque, chosen)
        fake_modal = namespace["_fake_modal"]
        assert fake_modal.captured_dicts == [{
            "MODAL_DEPLOYMENT_TRAFFIC_HOLD": chosen,
            "MODAL_REDIS_SECRET_NAME": "backup-redis",
        }]
        worker_env = _merged_env(namespace["_secrets"])
        api_env = _merged_env(namespace["_api_secrets"])
        assert worker_env["MODAL_DEPLOYMENT_TRAFFIC_HOLD"] == chosen
        assert api_env["MODAL_DEPLOYMENT_TRAFFIC_HOLD"] == chosen
        assert worker_env["REDIS_URL"] == api_env["REDIS_URL"] == "redis://backup"
        assert worker_env["REDIS_PASSWORD"] == api_env["REDIS_PASSWORD"] == "backup-pass"
        assert api_env["MODAL_REDIS_SECRET_NAME"] == "backup-redis"

    secrets_assignment = _assignment(tree, "_secrets")
    assert isinstance(secrets_assignment.value, ast.List)
    assert [item.value.id for item in secrets_assignment.value.elts if isinstance(item, ast.Starred)] == [
        "_base_secrets",
    ]
    assert isinstance(secrets_assignment.value.elts[-1], ast.Name)
    assert secrets_assignment.value.elts[-1].id == "_redis_secret"
    redis_assignment = _assignment(tree, "_redis_secret")
    assert isinstance(redis_assignment.value, ast.Call)
    assert isinstance(redis_assignment.value.func, ast.Attribute)
    assert redis_assignment.value.func.attr == "from_name"
    assert len(redis_assignment.value.args) == 1
    assert isinstance(redis_assignment.value.args[0], ast.Name)
    assert redis_assignment.value.args[0].id == "_redis_secret_name"


def test_every_modal_function_gets_a_secret_list_with_no_later_env_override() -> None:
    _, tree = _source_tree()
    function_count = 0
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id in {"app", "operations_app"}
                and decorator.func.attr == "function"
            ):
                continue
            function_count += 1
            secrets = [keyword.value for keyword in decorator.keywords if keyword.arg == "secrets"]
            assert len(secrets) == 1, node.name
            assert isinstance(secrets[0], ast.Name)
            assert secrets[0].id in {"_secrets", "_api_secrets"}, node.name
            # Modal appends function env after secrets; none may shadow the hold.
            assert not any(keyword.arg == "env" for keyword in decorator.keywords), node.name
    assert function_count >= 25


def test_hold_secret_and_both_appends_precede_modal_registration_with_no_later_mutation() -> None:
    _, tree = _source_tree()
    registrations = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id in {"app", "operations_app"}
                and decorator.func.attr == "function"
            ):
                registrations.append((decorator.lineno, node.name))
    assert registrations
    first_registration_line = min(line for line, _ in registrations)

    hold_line = _assignment(tree, "_deployment_hold_secret").lineno
    append_lines = {}
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "append"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in {"_secrets", "_api_secrets"}
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id == "_deployment_hold_secret"
        ):
            append_lines[call.func.value.id] = node.lineno
    assert set(append_lines) == {"_secrets", "_api_secrets"}
    assert hold_line < first_registration_line
    assert all(line < first_registration_line for line in append_lines.values())

    mutators = {"append", "extend", "insert", "clear", "pop", "remove", "reverse", "sort"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            target = node.func.value
            if (isinstance(target, ast.Name) and target.id in {"_secrets", "_api_secrets"}
                    and node.func.attr in mutators):
                assert node.lineno < first_registration_line, (
                    "secret list mutation after Modal function registration", node.lineno,
                )
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {"_secrets", "_api_secrets"}:
                    assert node.lineno < first_registration_line, (
                        "secret list rebound after Modal function registration", node.lineno,
                    )


def test_images_schedules_and_runtime_share_the_canonical_hold_selection() -> None:
    _, tree = _source_tree()
    hold_assignments = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_DEPLOYMENT_TRAFFIC_HOLD_VALUE"
                for target in node.targets)
    ]
    assert len(hold_assignments) == 1
    value = hold_assignments[0].value
    assert isinstance(value, ast.IfExp)
    assert isinstance(value.test, ast.Name) and value.test.id == "_DEPLOYMENT_TRAFFIC_HELD"
    assert isinstance(value.body, ast.Constant) and value.body.value == "true"
    assert isinstance(value.orelse, ast.Constant) and value.orelse.value == "false"

    image_envs = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "env":
            continue
        if not node.args or not isinstance(node.args[0], ast.Dict):
            continue
        entries = {
            key.value: item
            for key, item in zip(node.args[0].keys, node.args[0].values)
            if isinstance(key, ast.Constant)
        }
        if "MODAL_DEPLOYMENT_TRAFFIC_HOLD" in entries:
            image_envs.append(entries["MODAL_DEPLOYMENT_TRAFFIC_HOLD"])
    assert len(image_envs) == 4
    assert all(isinstance(item, ast.Name) and item.id == "_DEPLOYMENT_TRAFFIC_HOLD_VALUE"
               for item in image_envs)

    held_assignment = _assignment(tree, "_DEPLOYMENT_TRAFFIC_HELD")
    assert isinstance(held_assignment.value, ast.Call)
    assert isinstance(held_assignment.value.func, ast.Name)
    assert held_assignment.value.func.id == "deployment_traffic_held"
    assert len(held_assignment.value.args) == 1
    assert isinstance(held_assignment.value.args[0], ast.Attribute)
    assert isinstance(held_assignment.value.args[0].value, ast.Name)
    assert held_assignment.value.args[0].value.id == "os"
    assert held_assignment.value.args[0].attr == "environ"

    schedules = [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "schedule"
    ]
    assert len(schedules) == 5
    assert all(
        isinstance(schedule, ast.IfExp)
        and isinstance(schedule.test, ast.Name)
        and schedule.test.id == "_DEPLOYMENT_TRAFFIC_HELD"
        and isinstance(schedule.body, ast.Constant)
        and schedule.body.value is None
        for schedule in schedules
    )


if __name__ == "__main__":
    import unittest

    class ProposedModalHoldSecretOrderTests(unittest.TestCase):
        def test_binding_order(self):
            test_hold_binding_is_a_single_canonical_override_after_every_other_secret()

        def test_conflicting_fake_secrets(self):
            test_fake_conflicting_secrets_cannot_override_held_or_released_choice()

        def test_all_modal_functions_receive_override(self):
            test_every_modal_function_gets_a_secret_list_with_no_later_env_override()

        def test_override_precedes_registration(self):
            test_hold_secret_and_both_appends_precede_modal_registration_with_no_later_mutation()

        def test_canonical_hold_selection(self):
            test_images_schedules_and_runtime_share_the_canonical_hold_selection()

    unittest.main()
