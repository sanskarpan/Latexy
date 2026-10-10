"""Exercise the diagnostic wrapper without importing Modal or contacting services."""

import ast
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"


class SyntheticPath:
    def __init__(self, path):
        self.path = path

    def relative_to(self, root):
        return self.path.removeprefix(root + "/")

    def read_bytes(self):
        return b"synthetic source"

    def glob(self, pattern):
        assert pattern == "*.py"
        return []


def wrapper():
    tree = ast.parse(MODAL_APP.read_text())
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "billing_preflight")
    decorator = fn.decorator_list[0]
    assert {kw.arg: ast.unparse(kw.value) for kw in decorator.keywords} == {
        "image": "migrate_image", "secrets": "_secrets", "timeout": "120",
    }
    fn.decorator_list = []
    namespace = {"_APP_NAME": "latexy-backend", "Path": SyntheticPath}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(MODAL_APP), "exec"), namespace)
    return namespace["billing_preflight"]


@pytest.fixture(autouse=True)
def modal_context(monkeypatch):
    monkeypatch.setenv("MODAL_ENVIRONMENT", "main")
    monkeypatch.setenv("MODAL_IMAGE_ID", "im-synthetic")


def test_preflight_wrapper_reports_context_without_deploy_or_mutation(monkeypatch, capsys):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"status":"ready","production_like":true}', stderr="secret must stay hidden")

    monkeypatch.setattr(subprocess, "run", run)
    wrapper()("a" * 40)
    out = capsys.readouterr()
    report = json.loads(out.out)
    assert out.err == ""
    assert "secret" not in out.out
    assert report["status"] == "ready"
    assert report["execution_context"] == {
        "application": "latexy-backend",
        "selected_environment": "main",
        "expected_environment": "main",
        "image_id": "im-synthetic",
        "image_role": "candidate_migration_preflight",
        "source_revision_reported": "a" * 40,
        "expected_repository_head": "0068",
        "source_files_sha256": report["execution_context"]["source_files_sha256"],
    }
    assert len(report["execution_context"]["source_files_sha256"]) == 64
    assert calls == [(["python", "/backend/scripts/dodo_billing_preflight.py"], {
        "cwd": "/backend", "capture_output": True, "text": True, "timeout": 90,
    })]


def test_preflight_wrapper_does_not_bless_development_settings_in_main(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout='{"status":"ready","production_like":false}', stderr="",
    ))
    with pytest.raises(RuntimeError, match="requires review"):
        wrapper()("a" * 40)
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert report["blockers"] == ["main_environment_not_production_like"]


@pytest.mark.parametrize("revision,environment", [("not-a-revision", "main"), ("a" * 40, "dev")])
def test_preflight_wrapper_refuses_wrong_context_before_subprocess(monkeypatch, capsys, revision, environment):
    monkeypatch.setenv("MODAL_ENVIRONMENT", environment)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("must not run"))
    with pytest.raises(RuntimeError, match="mismatched execution context"):
        wrapper()(revision)
    report = json.loads(capsys.readouterr().out)
    assert report["error"] == "execution_context_mismatch"


@pytest.mark.parametrize("code", [1, 2])
def test_preflight_wrapper_preserves_redacted_blocking_report(monkeypatch, capsys, code):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=code, stdout='{"status":"blocked","production_like":true,"blockers":["database_unavailable"]}',
        stderr="private database URL",
    ))
    with pytest.raises(RuntimeError, match="requires review"):
        wrapper()("a" * 40)
    out = capsys.readouterr()
    assert "private" not in out.out + out.err
    assert json.loads(out.out)["blockers"] == ["database_unavailable"]


@pytest.mark.parametrize("failure", ["bad_json", "timeout", "unexpected_exit"])
def test_preflight_wrapper_suppresses_unexpected_failure_details(monkeypatch, capsys, failure):
    def run(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("private URL", 90, output="private key")
        return SimpleNamespace(
            returncode=77 if failure == "unexpected_exit" else 0,
            stdout='{"status":"ready"}' if failure == "unexpected_exit" else "private key",
            stderr="private connection URL",
        )

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError, match="no diagnostic details were logged") as exc:
        wrapper()("a" * 40)
    out = capsys.readouterr()
    assert "private" not in out.out + out.err + str(exc.value)
    assert json.loads(out.out)["error"] == "preflight_execution_failed"
