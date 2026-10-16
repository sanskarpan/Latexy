"""Disposable PostgreSQL reproductions for the pre-migration cutover gate.

Enable with TEST_POSTGRES_URL pointing at loopback and
TEST_POSTGRES_ALLOW_SCHEMA_CREATE=1. CI supplies both. No shared tables are
created or changed; every test owns and drops a random schema.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic.migration import MigrationContext
from alembic.operations import Operations
from scripts.dodo_billing_preflight import billing_identity_mismatch_count


def _test_postgres_url() -> str:
    value = os.getenv("TEST_POSTGRES_URL", "")
    if os.getenv("TEST_POSTGRES_ALLOW_SCHEMA_CREATE") != "1" or not value:
        pytest.skip("requires explicitly enabled disposable PostgreSQL")
    if make_url(value).host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.skip("test PostgreSQL must be loopback")
    return value


@pytest.fixture
def isolated_schema():
    url = _test_postgres_url()
    schema = "schema_compat_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _migration(filename: str):
    path = Path(__file__).parents[1] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location("schema_compat_0065", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0065_backfill_does_not_classify_later_legacy_writes(isolated_schema):
    """Prove why legacy billing writers must stop before the schema advances."""
    with isolated_schema.begin() as connection:
        connection.execute(text("CREATE TABLE subscriptions (id uuid PRIMARY KEY, razorpay_subscription_id varchar(255))"))
        connection.execute(text("CREATE TABLE payments (id uuid PRIMARY KEY, razorpay_payment_id varchar(255))"))
        connection.execute(text(
            "INSERT INTO subscriptions (id, razorpay_subscription_id) VALUES (:id, 'sub_before')"
        ), {"id": str(uuid4())})
        connection.execute(text("INSERT INTO payments (id, razorpay_payment_id) VALUES (:id, 'pay_before')"),
                           {"id": str(uuid4())})
        migration = _migration("0065_provider_neutral_billing.py")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        # These inserts have the same column shape as the historical service at
        # c21bcc20. They do not run that service or contact a provider.
        connection.execute(text(
            "INSERT INTO subscriptions (id, razorpay_subscription_id) VALUES (:id, 'sub_after')"
        ), {"id": str(uuid4())})
        connection.execute(text("INSERT INTO payments (id, razorpay_payment_id) VALUES (:id, 'pay_after')"),
                           {"id": str(uuid4())})
        subscription_rows = connection.execute(text(
            "SELECT razorpay_subscription_id, provider, provider_subscription_id FROM subscriptions ORDER BY razorpay_subscription_id"
        )).all()
        payment_rows = connection.execute(text(
            "SELECT razorpay_payment_id, provider, provider_payment_id FROM payments ORDER BY razorpay_payment_id"
        )).all()
        assert subscription_rows == [
            ("sub_after", "dodo", None), ("sub_before", "razorpay", "sub_before")
        ]
        assert payment_rows == [("pay_after", "dodo", None), ("pay_before", "razorpay", "pay_before")]
        with pytest.raises(RuntimeError, match="cannot downgrade billing revision 0065"):
            migration.downgrade()


def test_read_only_cutover_count_detects_later_legacy_writes(isolated_schema):
    """Run the diagnostic against real 0065 columns in a disposable schema."""
    with isolated_schema.begin() as connection:
        connection.execute(text("CREATE TABLE subscriptions (id uuid PRIMARY KEY, razorpay_subscription_id varchar(255))"))
        connection.execute(text("CREATE TABLE payments (id uuid PRIMARY KEY, razorpay_payment_id varchar(255))"))
        connection.execute(text("INSERT INTO subscriptions VALUES (:id, 'sub_before')"), {"id": str(uuid4())})
        connection.execute(text("INSERT INTO payments VALUES (:id, 'pay_before')"), {"id": str(uuid4())})
        migration = _migration("0065_provider_neutral_billing.py")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        schema = connection.scalar(text("SELECT current_schema()"))
        assert billing_identity_mismatch_count(connection, schema=schema) == 0

        # Reproduce the legacy writer's columns without invoking a provider.
        connection.execute(text("INSERT INTO subscriptions (id, razorpay_subscription_id) "
                                "VALUES (:id, 'sub_after')"), {"id": str(uuid4())})
        connection.execute(text("INSERT INTO payments (id, razorpay_payment_id) "
                                "VALUES (:id, 'pay_after')"), {"id": str(uuid4())})
        assert billing_identity_mismatch_count(connection, schema=schema) == 2
        assert connection.scalar(text("SELECT COUNT(*) FROM subscriptions")) == 2
        assert connection.scalar(text("SELECT COUNT(*) FROM payments")) == 2


def test_0065_refuses_downgrade_after_new_dodo_payment(isolated_schema):
    with isolated_schema.begin() as connection:
        connection.execute(text("CREATE TABLE subscriptions (id uuid PRIMARY KEY, razorpay_subscription_id varchar(255))"))
        connection.execute(text("CREATE TABLE payments (id uuid PRIMARY KEY, razorpay_payment_id varchar(255))"))
        migration = _migration("0065_provider_neutral_billing.py")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        payment_id = str(uuid4())
        connection.execute(text(
            "INSERT INTO payments (id, provider, provider_payment_id) "
            "VALUES (:id, 'dodo', 'pay_new_dodo')"
        ), {"id": payment_id})
        with pytest.raises(RuntimeError, match="cannot downgrade billing revision 0065"):
            migration.downgrade()
        assert connection.scalar(text("SELECT provider_payment_id FROM payments WHERE id=:id"),
                                 {"id": payment_id}) == "pay_new_dodo"


def test_old_completed_reader_selects_unaccepted_candidate(isolated_schema):
    """Prove why rollback requires a build with the acceptance filter."""
    with isolated_schema.begin() as connection:
        connection.execute(text(
            "CREATE TABLE compilations (id uuid PRIMARY KEY, resume_id uuid NOT NULL, "
            "status varchar(32) NOT NULL, created_at timestamptz NOT NULL)"
        ))
        resume, accepted, candidate = (str(uuid4()) for _ in range(3))
        connection.execute(text(
            "INSERT INTO compilations (id, resume_id, status, created_at) "
            "VALUES (:id, :resume, 'completed', '2026-01-01T00:00:00Z')"
        ), {"id": accepted, "resume": resume})
        migration = _migration("0062_compilation_artifact_acceptance.py")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.scalar(text("SELECT artifact_accepted FROM compilations WHERE id=:id"),
                                 {"id": accepted}) is True
        connection.execute(text(
            "INSERT INTO compilations (id, resume_id, status, created_at, artifact_branch, artifact_accepted) "
            "VALUES (:id, :resume, 'completed', '2026-01-02T00:00:00Z', 'candidate', false)"
        ), {"id": candidate, "resume": resume})
        query = "SELECT id FROM compilations WHERE resume_id=:resume AND status='completed'"
        order = " ORDER BY created_at DESC LIMIT 1"
        old_choice = connection.scalar(text(query + order), {"resume": resume})
        safe_choice = connection.scalar(text(query + " AND artifact_accepted IS TRUE" + order), {"resume": resume})
        assert str(old_choice) == candidate
        assert str(safe_choice) == accepted


def test_deployment_cutover_gate_precedes_migration():
    workflow = (Path(__file__).parents[2] / ".github" / "workflows" / "deploy-modal.yml").read_text()
    assert workflow.index("Require schema cutover and recovery approval") < workflow.index(
        "Apply production database migrations"
    )
    assert "python backend/scripts/check_modal_schema_cutover.py" in workflow
    assert "MODAL_SCHEMA_CUTOVER_APPROVED_SHA" in workflow
    assert "MODAL_FORWARD_ROLLBACK_SHA" in workflow
    assert "MODAL_RECOVERY_VERIFIED_FOR_SHA" in workflow
