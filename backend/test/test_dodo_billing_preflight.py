"""Redaction and read-only guarantees for operator-run Dodo diagnostics."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event, text

from scripts import dodo_billing_preflight as preflight


def live_environment():
    return {"ENVIRONMENT": "production", "BILLING_MODE": "required", "DODO_MODE": "live",
            "DODO_LIVE_API_KEY": "private-api-sentinel", "DODO_LIVE_WEBHOOK_KEY": "private-webhook-sentinel",
            "DODO_LIVE_PRODUCT_PRO_MONTHLY": "private-product-sentinel", "DATABASE_URL": "postgresql://fixture"}


def current_columns():
    return {**{table: set(names) for table, names in preflight.CURRENT_BILLING_COLUMNS.items()},
            "render_artifact_manifests": {"artifact_id"}, "resume_optimization_runs": {"id"}}


def test_public_catalog_matches_current_runtime_defaults():
    from app.core.config import get_plan_config
    report, blockers = preflight.configuration_report(live_environment())
    assert blockers == []
    assert set(report["skus"]) == set(preflight.PRODUCT_KEYS)
    for key, sku in report["skus"].items():
        expected = get_plan_config(key)
        assert (sku["price_minor"], sku["currency"], sku["interval"]) == (
            expected["price"], expected["currency"], expected["interval"],
        )
    assert report["skus"]["pro"]["configured"] is True
    assert report["skus"]["weekly"]["configured"] is False
    output = json.dumps(report)
    assert "sentinel" not in output
    assert "not_provider_verified" in output


@pytest.mark.parametrize("mode", ["test", "live", "secret-invalid-mode"])
def test_only_active_mode_credential_presence_is_reported(mode):
    env = live_environment() | {"DODO_MODE": mode}
    report, blockers = preflight.configuration_report(env)
    assert report["active_api_key_present"] is (mode == "live")
    assert report["active_webhook_key_present"] is (mode == "live")
    assert "secret-invalid-mode" not in json.dumps(report)
    if mode != "live":
        assert "production_requires_live_mode" in blockers


def test_optional_sku_public_override_never_emits_product_ids():
    env = live_environment() | {"DODO_LIVE_PRODUCT_LIFETIME": "secret-lifetime-id",
                               "LIFETIME_AMOUNT_MINOR": "12500", "BILLING_CURRENCY": "usd"}
    report, _ = preflight.configuration_report(env)
    assert report["skus"]["lifetime"] == {"product_id_configured": True, "configured": True,
                                          "price_minor": 12500, "currency": "USD", "interval": "lifetime", "tax_inclusive": True}
    assert "secret-lifetime-id" not in json.dumps(report)


@pytest.mark.parametrize("override", ["invalid-secret-json", '[]', '{"pro":{"price":"secret","currency":"secret","interval":"secret"}}'])
def test_invalid_catalog_is_redacted_and_blocks_readiness(override):
    report, blockers = preflight.configuration_report(live_environment() | {"SUBSCRIPTION_PLANS": override})
    assert blockers
    assert "secret" not in json.dumps(report)
    assert not report["skus"]["pro"]["configured"]


def test_environment_precedence_is_allowlisted_without_startup(tmp_path):
    backend = tmp_path / "backend"
    backend.mkdir()
    (tmp_path / ".env").write_text("BILLING_MODE=disabled\nDODO_MODE=test\nUNRELATED_SECRET=never-read-out\n")
    (backend / ".env").write_text("BILLING_MODE=auto\nDODO_MODE=live\n")
    values = preflight.read_environment({"BILLING_MODE": "required", "ANOTHER_SECRET": "hidden"}, backend)
    assert values == {"BILLING_MODE": "required", "DODO_MODE": "live"}


@pytest.mark.parametrize("revision,columns,expected", [
    ("0059", {"users": set(), "subscriptions": set()}, "known_mainline_pre_dodo"),
    ("0061", {"render_artifact_manifests": set(), "resume_optimization_runs": set()}, "known_mainline_pre_dodo"),
    ("0061", {"subscriptions": {"provider", "provider_subscription_id"}, "billing_webhook_events": set(), "payment_refunds": set()},
     "legacy_dodo_0061_requires_bridge_validation"),
    ("0061", current_columns(), "ambiguous_0061_requires_review"),
    ("0067", current_columns(), "known_mainline_dodo_upgrade_required"),
    ("0068", current_columns(), "current_dodo_head"),
    ("0068", {}, "schema_revision_mismatch_requires_review"),
    ("secret", current_columns(), "unknown_requires_review"),
])
def test_revision_collision_classification(revision, columns, expected):
    assert preflight.classify_schema([revision], columns, preflight.known_revisions()) == expected


def fake_engine(columns=None, revision="0068", historical=0):
    columns = current_columns() if columns is None else columns
    connection = MagicMock()
    transaction = connection.begin.return_value
    captured = []

    def execute(statement, params=None):
        sql = str(statement)
        captured.append(sql)
        if "information_schema.columns" in sql:
            return [(table, column) for table, names in columns.items() for column in names]
        if "historical_paid_pointer_users" in sql:
            return SimpleNamespace(mappings=lambda: SimpleNamespace(one=lambda: {
                "paid_pointer_users": historical, "historical_paid_pointer_users": historical,
                "historical_team_owners": 0,
            }))
        return None

    connection.execute.side_effect = execute
    connection.scalar.side_effect = lambda statement, *_args: "on" if "transaction_read_only" in str(statement) else 0
    connection.scalars.return_value = [revision]
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    return engine, connection, transaction, captured


def test_database_transaction_is_read_only_rolled_back_and_aggregated():
    engine, connection, transaction, captured = fake_engine()
    factory = MagicMock(return_value=engine)
    report = preflight.database_report("postgresql+asyncpg://user:secret@host/database", engine_factory=factory)
    assert captured[0] == "SET TRANSACTION READ ONLY"
    assert factory.call_args.kwargs["hide_parameters"] is True
    assert "default_transaction_read_only=on" in factory.call_args.kwargs["connect_args"]["options"]
    assert factory.call_args.kwargs["isolation_level"] == "REPEATABLE READ"
    transaction.rollback.assert_called_once()
    transaction.commit.assert_not_called()
    engine.dispose.assert_called_once()
    assert report["status"] == "read_only_complete"
    assert all("SELECT *" not in sql for sql in captured)
    assert "secret" not in json.dumps(report)


def test_pre_migration_schema_uses_legacy_columns_without_provider_assumptions():
    columns = current_columns()
    columns["subscriptions"] = {"id", "user_id", "status", "razorpay_subscription_id"}
    columns.pop("billing_webhook_events")
    columns.pop("payment_refunds")
    columns.pop("payments")
    engine, _, _, captured = fake_engine(columns, "0064", historical=3)
    report = preflight.database_report("postgresql://fixture", engine_factory=lambda *_a, **_k: engine)
    query = next(sql for sql in captured if "historical_paid_pointer_users" in sql)
    assert "s.provider =" not in query
    assert "s.provider_subscription_id" not in query
    assert "s.razorpay_subscription_id = u.subscription_id" in query
    assert "^(sub_|order_)" in query
    assert report["counts"]["historical_paid_pointer_users"] == 3


@pytest.mark.parametrize("historical,expected_exit", [(0, 0), (2, 1)])
def test_report_exit_code_distinguishes_readiness_and_cutover_blockers(monkeypatch, historical, expected_exit):
    monkeypatch.setattr(preflight, "read_environment", lambda *_: live_environment())
    engine, _, _, _ = fake_engine(historical=historical)
    report, exit_code = preflight.collect_report(engine_factory=lambda *_a, **_k: engine)
    assert exit_code == expected_exit
    assert report["status"] == ("ready" if not historical else "blocked")
    assert "sentinel" not in json.dumps(report)


def test_driver_failures_never_emit_exception_text_and_always_roll_back(monkeypatch):
    monkeypatch.setattr(preflight, "read_environment", lambda *_: live_environment())
    engine, connection, transaction, _ = fake_engine()
    connection.execute.side_effect = RuntimeError("password=secret-user-data")
    report, code = preflight.collect_report(engine_factory=lambda *_a, **_k: engine)
    assert code == 2
    assert "secret-user-data" not in json.dumps(report)
    assert "RuntimeError" not in json.dumps(report)
    transaction.rollback.assert_called_once()
    engine.dispose.assert_called_once()


def test_cli_survives_settings_startup_errors_without_emitting_secrets():
    env = {key: value for key, value in os.environ.items() if key not in preflight.ENV_KEYS}
    env.update(live_environment(), DATABASE_URL="unsupported://secret-database-password", SKIP_ENV_VALIDATION="false",
               JWT_SECRET_KEY="", API_KEY_ENCRYPTION_KEY="")
    result = subprocess.run([sys.executable, str(preflight.BACKEND_ROOT / "scripts/dodo_billing_preflight.py")],
                            env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["dodo_mode"] == "live"
    assert report["active_api_key_present"] is True
    assert "sentinel" not in result.stdout + result.stderr
    assert "secret-database-password" not in result.stdout + result.stderr
    assert not result.stderr


@pytest.mark.asyncio
async def test_real_postgres_read_only_report_contains_only_aggregate_counts(db_session):
    uid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    await db_session.execute(text("""INSERT INTO users(id,email,name,email_verified,subscription_plan,subscription_status,subscription_id,trial_used)
        VALUES(:id,:email,'Preflight privacy',true,'team','active',:sid,false)"""),
        {"id": uid, "email": f"test_{uid}@example.com", "sid": sid})
    await db_session.execute(text("""INSERT INTO subscriptions(id,user_id,provider,provider_subscription_id,plan_id,status)
        VALUES(:id,:uid,'razorpay',:pid,'team','active')"""),
        {"id": sid, "uid": uid, "pid": f"sub_{uid}"})
    await db_session.commit()
    statements = []
    read_only_seen = []

    def factory(*args, **kwargs):
        engine = create_engine(*args, **kwargs)

        @event.listens_for(engine, "before_cursor_execute")
        def record(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)
            if statement.startswith("SELECT table_name"):
                read_only_seen.append(_connection.scalar(text("SHOW transaction_read_only")))
        return engine

    report = preflight.database_report(os.environ["DATABASE_URL"], engine_factory=factory)
    assert read_only_seen == ["on"]
    assert report["schema_classification"] == "current_dodo_head"
    assert report["counts"]["historical_paid_pointer_users"] >= 1
    assert report["counts"]["historical_team_owners"] >= 1
    assert all(not sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP")) for sql in statements)
    assert uid not in json.dumps(report) and sid not in json.dumps(report)


@pytest.mark.parametrize("billing,mode,api,webhook,startup_valid,checkout_available", [
    ("disabled", "test", False, False, True, False),
    ("disabled", "test", True, False, True, False),
    ("disabled", "test", True, True, True, False),
    ("auto", "test", False, False, True, False),
    ("auto", "live", False, False, True, False),
    ("auto", "live", True, False, False, False),
    ("required", "live", False, False, False, False),
    ("required", "test", True, True, False, False),
    ("required", "live", True, True, True, True),
])
def test_billing_startup_and_sales_availability_are_distinct(billing, mode, api, webhook, startup_valid, checkout_available):
    env = {"ENVIRONMENT": "production", "BILLING_MODE": billing, "DODO_MODE": mode,
           "SKIP_ENV_VALIDATION": "true", f"DODO_{mode.upper()}_PRODUCT_PRO_MONTHLY": "private-product"}
    if api:
        env[f"DODO_{mode.upper()}_API_KEY"] = "private-api"
    if webhook:
        env[f"DODO_{mode.upper()}_WEBHOOK_KEY"] = "private-webhook"
    report, _ = preflight.configuration_report(env)
    assert report["startup_configuration_valid"] is startup_valid
    assert report["checkout_configuration_available"] is checkout_available
    assert report["skip_env_validation"] is True
    assert report["startup_validation_scope"] == "strict_billing_rules_only_without_skip_bypass"


def test_unknown_environment_and_tax_expectations_are_redacted():
    env = live_environment() | {"ENVIRONMENT": "private-env-sentinel", "DEPLOY_TARGET": "private-target-sentinel",
                               "SUBSCRIPTION_PLANS": json.dumps({"pro": {
                                   "price": 100, "currency": "INR", "interval": "month", "tax_inclusive": "private-tax-sentinel",
                               }})}
    report, blockers = preflight.configuration_report(env)
    assert report["environment"] == "invalid" and report["deploy_target"] == "invalid"
    assert report["skus"]["pro"]["tax_inclusive"] is None
    assert "invalid_configured_sku_expectations" in blockers
    assert "sentinel" not in json.dumps(report)


def test_disposable_pre_dodo_database_reports_history_without_changing_it():
    """Fixture setup/cleanup writes only a new disposable test DB; preflight does not."""
    from sqlalchemy.engine import make_url

    source_url = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql+psycopg2")
    assert source_url.database.endswith("_test")
    name = f"latexy_preflight_{uuid.uuid4().hex}_test"
    admin = create_engine(source_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    fixture = None
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created = True
        fixture_url = source_url.set(database=name)
        fixture = create_engine(fixture_url, hide_parameters=True)
        with fixture.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE alembic_version(version_num varchar(32))")
            connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('0064')")
            connection.exec_driver_sql("CREATE TABLE users(id text,subscription_plan text,subscription_id text)")
            connection.exec_driver_sql("CREATE TABLE subscriptions(id text,user_id text,razorpay_subscription_id text,status text)")
            connection.exec_driver_sql("CREATE TABLE team_seats(owner_user_id text,member_user_id text,status text)")
            connection.exec_driver_sql("CREATE TABLE render_artifact_manifests(id text)")
            connection.exec_driver_sql("CREATE TABLE resume_optimization_runs(id text)")
            connection.exec_driver_sql("""INSERT INTO users VALUES
                ('owner','team','sub_fixture'),('member','team_member',NULL),
                ('pro','pro','local-fixture-id'),('orphan','lifetime','order_fixture')""")
            connection.exec_driver_sql("""INSERT INTO subscriptions VALUES
                ('team-local','owner','sub_fixture','active'),('local-fixture-id','pro','sub_other','cancelled'),
                ('orphan-local','not-pointed-at','sub_unresolved','authenticated')""")
            connection.exec_driver_sql("INSERT INTO team_seats VALUES ('owner','member','active')")
        with fixture.connect() as connection:
            before = {table: connection.exec_driver_sql(f"SELECT * FROM {table}").all()
                      for table in ("users", "subscriptions", "team_seats", "alembic_version")}
        report = preflight.database_report(fixture_url.render_as_string(hide_password=False))
        assert report["schema_classification"] == "known_mainline_pre_dodo"
        assert report["alembic_revisions"] == ["0064"]
        assert report["counts"] == {"paid_pointer_users": 3, "historical_paid_pointer_users": 3,
                                    "historical_team_owners": 1, "active_seats_inheriting_historical_owners": 1,
                                    "historical_live_mandate_users": 2}
        with fixture.connect() as connection:
            after = {table: connection.exec_driver_sql(f"SELECT * FROM {table}").all()
                     for table in before}
        assert before == after
        assert "sub_fixture" not in json.dumps(report)
        assert "local-fixture-id" not in json.dumps(report)
    finally:
        if fixture is not None:
            fixture.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


@pytest.mark.parametrize("table,column", [
    (table, column) for table, columns in preflight.CURRENT_BILLING_COLUMNS.items() for column in sorted(columns)
])
def test_current_revision_with_missing_billing_column_is_not_ready(table, column):
    columns = current_columns()
    columns[table].remove(column)
    assert preflight.classify_schema(["0068"], columns, preflight.known_revisions()) == "schema_revision_mismatch_requires_review"


@pytest.mark.parametrize("table", list(preflight.CURRENT_BILLING_COLUMNS))
def test_current_revision_with_missing_billing_table_is_not_ready(table):
    columns = current_columns()
    del columns[table]
    assert preflight.classify_schema(["0068"], columns, preflight.known_revisions()) == "schema_revision_mismatch_requires_review"


@pytest.mark.parametrize("revision", ["0059", "0060", "0061", "0064"])
def test_pre_dodo_revision_with_partial_provider_columns_requires_review(revision):
    columns = {"subscriptions": {"provider"}, "resume_optimization_runs": {"id"}, "render_artifact_manifests": {"id"}}
    assert "requires_review" in preflight.classify_schema([revision], columns, preflight.known_revisions())


@pytest.mark.parametrize("revision", ["0060", "0061", "0062", "0063", "0064"])
def test_pre_dodo_revision_requires_its_engine_markers(revision):
    assert "requires_review" in preflight.classify_schema([revision], {}, preflight.known_revisions())


def test_unpointed_historical_mandates_block_readiness(monkeypatch):
    monkeypatch.setattr(preflight, "read_environment", lambda *_: live_environment())
    engine, connection, _, _ = fake_engine()
    connection.scalar.side_effect = lambda statement, *_args: (
        "on" if "transaction_read_only" in str(statement) else 1 if "COUNT(DISTINCT s.user_id)" in str(statement) else 0
    )
    report, code = preflight.collect_report(engine_factory=lambda *_a, **_k: engine)
    assert code == 1
    assert report["database"]["counts"]["historical_paid_pointer_users"] == 0
    assert report["database"]["counts"]["historical_live_mandate_users"] == 1
    assert "historical_live_mandates_require_cutover_review" in report["blockers"]


@pytest.mark.parametrize("key", ["WEEKLY_AMOUNT_MINOR", "LIFETIME_AMOUNT_MINOR"])
@pytest.mark.parametrize("value", ["secret-invalid-amount", "-1"])
@pytest.mark.parametrize("billing", ["required", "disabled"])
def test_optional_amounts_must_pass_startup_validation_even_when_unmapped(key, value, billing):
    report, blockers = preflight.configuration_report(live_environment() | {key: value, "BILLING_MODE": billing})
    assert not report["startup_configuration_valid"]
    assert not report["checkout_configuration_available"]
    assert "invalid_optional_sku_amount" in report["startup_configuration_reasons"]
    assert "invalid_optional_sku_amount" in blockers
    assert "secret-invalid-amount" not in json.dumps(report)


@pytest.mark.parametrize("catalog", ["bad-secret-json", "[]", '"secret-string"'])
def test_invalid_catalog_shape_is_a_startup_blocker_even_when_sales_disabled(catalog):
    report, _ = preflight.configuration_report(live_environment() | {"SUBSCRIPTION_PLANS": catalog, "BILLING_MODE": "disabled"})
    assert not report["startup_configuration_valid"]
    assert "invalid_local_catalog" in report["startup_configuration_reasons"]
    assert "secret" not in json.dumps(report)


def test_optional_integer_parsing_matches_pydantic_runtime():
    report, _ = preflight.configuration_report(live_environment() | {"WEEKLY_AMOUNT_MINOR": "123.0"})
    assert report["startup_configuration_valid"]
    assert report["skus"]["weekly"]["price_minor"] == 123
