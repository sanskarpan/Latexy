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


def diagnostic_payload(*, production=True, status="ready", blockers=None, change=None, env_override=None):
    from scripts.dodo_billing_preflight import configuration_inputs, configuration_report

    environment = {
        "ENVIRONMENT": "production" if production else "development", "DODO_MODE": "live",
        "DODO_LIVE_API_KEY": "synthetic-api", "DODO_LIVE_WEBHOOK_KEY": "synthetic-hook",
        "DODO_LIVE_PRODUCT_PRO_MONTHLY": "synthetic-product",
    }
    environment.update(env_override or {})
    report, _ = configuration_report(*configuration_inputs(environment))
    report.update(status=status, blockers=blockers or [], database={
        "status": "read_only_complete", "alembic_revisions": ["0068"],
        "schema_classification": "current_dodo_head", "counts": {
            "paid_pointer_users": 0, "historical_paid_pointer_users": 0, "historical_team_owners": 0,
            "active_seats_inheriting_historical_owners": 0, "historical_live_mandate_users": 0,
            "existing_dodo_live_intent_users": 0,
        },
    })
    if change:
        change(report)
    return json.dumps(report)


@pytest.fixture(autouse=True)
def modal_context(monkeypatch):
    monkeypatch.setenv("MODAL_ENVIRONMENT", "main")
    monkeypatch.setenv("MODAL_IMAGE_ID", "im-synthetic")


def test_preflight_wrapper_reports_context_without_deploy_or_mutation(monkeypatch, capsys):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=diagnostic_payload(), stderr="secret must stay hidden")

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
        "purpose": "report",
        "source_files_sha256": report["execution_context"]["source_files_sha256"],
    }
    assert len(report["execution_context"]["source_files_sha256"]) == 64
    assert calls == [(["python", "/backend/scripts/dodo_billing_preflight.py"], {
        "cwd": "/backend", "capture_output": True, "text": True, "timeout": 90,
    })]


def test_preflight_wrapper_does_not_bless_development_settings_in_main(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=diagnostic_payload(production=False), stderr="",
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
        returncode=code, stdout=diagnostic_payload(status="blocked", blockers=["billing_disabled"]),
        stderr="private database URL",
    ))
    with pytest.raises(RuntimeError, match="requires review"):
        wrapper()("a" * 40)
    out = capsys.readouterr()
    assert "private" not in out.out + out.err
    assert json.loads(out.out)["blockers"] == ["billing_disabled"]


@pytest.mark.parametrize("change", [
    lambda r: r.update(unexpected_secret="private-child-sentinel"),
    lambda r: r["skus"]["pro"].update(customer_id="private-child-sentinel"),
    lambda r: r.update(active_api_key_present="private-child-sentinel"),
    lambda r: r["database"]["counts"].update(paid_pointer_users="private-child-sentinel"),
])
def test_preflight_wrapper_rejects_unallowlisted_child_output(monkeypatch, capsys, change):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=diagnostic_payload(change=change), stderr="private-child-sentinel",
    ))
    with pytest.raises(RuntimeError, match="no diagnostic details were logged"):
        wrapper()("a" * 40)
    out = capsys.readouterr()
    assert "private-child-sentinel" not in out.out + out.err
    assert json.loads(out.out)["error"] == "preflight_execution_failed"


def test_rollout_wrapper_accepts_safe_disabled_before_migration(monkeypatch, capsys):
    def before_migration(report):
        report["database"].update(alembic_revisions=["0059"], schema_classification="known_mainline_pre_dodo")

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=1, stdout=diagnostic_payload(status="blocked", blockers=["billing_disabled"],
            env_override={"BILLING_MODE": "disabled", "DEPLOY_TARGET": "modal"}, change=before_migration), stderr="",
    ))
    wrapper()("a" * 40, purpose="rollout")
    report = json.loads(capsys.readouterr().out)
    assert report["rollout_safety"]["safe_to_rollout"] is True
    assert report["rollout_safety"]["sales_state"] == "safe_disabled"
    assert report["rollout_safety"]["live_sales_acceptance"] == "unverified"
    assert set(report) == {"execution_context", "rollout_safety"}
    assert "database" not in report and "active_api_key_present" not in report


@pytest.mark.parametrize("accepted,passes", [(False, False), (True, True)])
def test_rollout_wrapper_configured_live_requires_explicit_acceptance(monkeypatch, capsys, accepted, passes):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=diagnostic_payload(env_override={"DEPLOY_TARGET": "modal"}), stderr="",
    ))
    if passes:
        wrapper()("a" * 40, purpose="rollout", allow_configured_live=accepted)
    else:
        with pytest.raises(RuntimeError, match="requires review"):
            wrapper()("a" * 40, purpose="rollout", allow_configured_live=accepted)
    report = json.loads(capsys.readouterr().out)
    assert report["rollout_safety"]["safe_to_rollout"] is passes


def test_rollout_wrapper_never_overrides_incomplete_diagnostic_exit(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=2, stdout=diagnostic_payload(env_override={"BILLING_MODE": "disabled", "DEPLOY_TARGET": "modal"}), stderr="",
    ))
    with pytest.raises(RuntimeError, match="requires review"):
        wrapper()("a" * 40, purpose="rollout", allow_configured_live=True)
    report = json.loads(capsys.readouterr().out)
    assert report["rollout_safety"]["safe_to_rollout"] is False
    assert "rollout_diagnostics_incomplete" in report["rollout_safety"]["reasons"]


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


@pytest.mark.parametrize("stage", [
    "configuration", "engine", "connect", "read_only_setup", "schema_metadata", "schema_revision", "aggregate_counts", "cleanup",
])
@pytest.mark.parametrize("purpose", ["report", "rollout"])
def test_wrapper_preserves_only_fixed_database_failure_stages(monkeypatch, capsys, stage, purpose):
    from scripts.dodo_billing_preflight import DATABASE_FAILURE_REASONS

    def incomplete(report):
        report["database"] = {"status": "unavailable_or_unsupported", "failure_stage": stage}

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=2, stdout=diagnostic_payload(status="diagnostic_error", blockers=["diagnostics_incomplete"],
            env_override={"BILLING_MODE": "disabled", "DEPLOY_TARGET": "modal"}, change=incomplete),
        stderr="private-database-driver-sentinel",
    ))
    with pytest.raises(RuntimeError, match="requires review"):
        wrapper()("a" * 40, purpose=purpose, allow_configured_live=True)
    output = capsys.readouterr()
    assert "sentinel" not in output.out + output.err
    report = json.loads(output.out)
    if purpose == "report":
        assert report["database"] == {"status": "unavailable_or_unsupported", "failure_stage": stage}
    else:
        assert set(report) == {"rollout_safety", "execution_context"}
        assessment = report["rollout_safety"]
        assert assessment["safe_to_rollout"] is False
        assert assessment["reasons"] == ["rollout_diagnostics_incomplete", "rollout_database_diagnostics_incomplete",
                                          DATABASE_FAILURE_REASONS[stage]]
        assert "active_api_key_present" not in output.out and "counts" not in report


@pytest.mark.parametrize("stage", ["private-stage-sentinel", "", None, False, 1, [], {"value": "private-stage-sentinel"}])
@pytest.mark.parametrize("purpose", ["report", "rollout"])
def test_wrapper_rejects_unknown_database_failure_stage_without_logging_it(monkeypatch, capsys, stage, purpose):
    def incomplete(report):
        report["database"] = {"status": "unavailable_or_unsupported", "failure_stage": stage}

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=2, stdout=diagnostic_payload(status="diagnostic_error", blockers=["diagnostics_incomplete"],
            env_override={"BILLING_MODE": "disabled", "DEPLOY_TARGET": "modal"}, change=incomplete),
        stderr="private-stage-sentinel",
    ))
    with pytest.raises(RuntimeError, match="no diagnostic details were logged"):
        wrapper()("a" * 40, purpose=purpose)
    output = capsys.readouterr()
    assert "sentinel" not in output.out + output.err
    assert json.loads(output.out)["error"] == "preflight_execution_failed"


@pytest.mark.parametrize("stage", [None, "connect", "aggregate_counts"])
@pytest.mark.parametrize("production", [None, False])
@pytest.mark.parametrize("purpose", ["report", "rollout"])
def test_wrapper_incomplete_reports_without_production_context_do_not_cascade(monkeypatch, capsys, stage, production, purpose):
    payload = {"status": "diagnostic_error", "blockers": ["diagnostics_incomplete"],
               "database": {"status": "unavailable_or_unsupported"}}
    if stage is not None:
        payload["database"]["failure_stage"] = stage
    if production is not None:
        payload["production_like"] = production
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=2, stdout=json.dumps(payload), stderr="private-database-sentinel",
    ))
    with pytest.raises(RuntimeError, match="requires review"):
        wrapper()("a" * 40, purpose=purpose, allow_configured_live=True)
    output = capsys.readouterr()
    assert "sentinel" not in output.out + output.err
    report = json.loads(output.out)
    if purpose == "report":
        assert report["status"] == "diagnostic_error"
        assert "main_environment_not_production_like" in report["blockers"]
    else:
        assert report["rollout_safety"]["safe_to_rollout"] is False
        assert "rollout_diagnostics_incomplete" in report["rollout_safety"]["reasons"]
        assert "rollout_public_report_invalid" not in report["rollout_safety"]["reasons"]
