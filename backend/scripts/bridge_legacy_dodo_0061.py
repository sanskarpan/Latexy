"""Safely bridge the pre-renumbering Dodo Alembic revision 0061.

This one-off bridge applies the OAuth and resume-engine migrations that were
inserted before Dodo's migrations, verifies that the original Dodo schema is
already complete, and advances the Alembic marker to 0067 in one PostgreSQL
transaction. It never re-runs or rewrites billing migrations.

Run with --dry-run first. Applying requires both --apply and an exact database
name supplied with --expected-database. The connection URL comes from the
normal backend settings and is never printed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = BACKEND_ROOT / "alembic" / "versions"
EXPECTED_REVISION = "0061"
TARGET_REVISION = "0067"
LOCK_KEY = 5_184_992_910_061_067

FINANCIAL_TABLES = (
    "subscriptions",
    "payments",
    "coupon_redemptions",
    "billing_webhook_events",
    "payment_refunds",
    "coupon_codes",
)
USER_ENTITLEMENT_COLUMNS = ("id", "subscription_plan", "subscription_status", "subscription_id")

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "subscriptions": {
        "razorpay_subscription_id",
        "provider", "provider_subscription_id", "provider_checkout_session_id",
        "provider_customer_id", "provider_product_id", "provider_event_at",
        "quoted_amount", "discount_percent", "quoted_tax_inclusive",
    },
    "payments": {"razorpay_payment_id", "provider", "provider_payment_id", "provider_event_at"},
    "coupon_codes": {"id", "code", "discount_percent", "applicable_plans", "max_uses", "used_count", "expires_at", "created_at"},
    "coupon_redemptions": {"subscription_id", "status", "redeemed_at", "coupon_id", "user_id"},
    "billing_webhook_events": {
        "id", "provider", "event_id", "event_type", "payload_sha256", "event_at",
        "status", "attempts", "last_error", "received_at", "processed_at",
    },
    "payment_refunds": {
        "id", "payment_id", "provider", "provider_refund_id", "amount", "currency",
        "status", "reason", "created_at",
    },
}

REQUIRED_UNIQUES = {
    ("subscriptions", "uq_subscriptions_provider_subscription_id", ("provider", "provider_subscription_id")),
    ("subscriptions", "uq_subscriptions_provider_checkout_id", ("provider", "provider_checkout_session_id")),
    ("payments", "uq_payments_provider_payment_id", ("provider", "provider_payment_id")),
    ("billing_webhook_events", "uq_billing_webhook_provider_event", ("provider", "event_id")),
    ("payment_refunds", "uq_payment_refunds_provider_id", ("provider", "provider_refund_id")),
}

REQUIRED_FOREIGN_KEYS = {
    ("coupon_redemptions", "fk_coupon_redemptions_subscription_id_subscriptions", "subscription_id", "subscriptions", "id", "SET NULL"),
    ("payment_refunds", None, "payment_id", "payments", "id", "RESTRICT"),
}

ENGINE_OUTPUT_COLUMNS = {
    ("resumes", "content_revision"),
    ("compilations", "artifact_branch"),
    ("compilations", "artifact_accepted"),
    ("resumes", "imported_projection"),
}
ENGINE_OUTPUT_TABLES = {
    "resume_optimization_runs",
    "resume_optimization_stages",
    "resume_requirement_contexts",
    "render_artifact_manifests",
    "resume_pdf_imports",
}
ENGINE_OUTPUT_CONSTRAINTS = {
    ("resumes", "ck_resumes_content_revision_positive"),
    ("compilations", "ck_compilation_artifact_branch"),
    ("resumes", "ck_resumes_imported_projection_bounded"),
}


@dataclass(frozen=True)
class SchemaSnapshot:
    version_rows: tuple[str, ...]
    tables: frozenset[str]
    columns: dict[str, frozenset[str]]
    column_types: dict[tuple[str, str], str]
    column_nullable: dict[tuple[str, str], bool]
    column_defaults: dict[tuple[str, str], str | None]
    unique_constraints: frozenset[tuple[str, str, tuple[str, ...]]]
    foreign_keys: tuple[tuple[str, str | None, str, str, str, str | None], ...]
    indexes: frozenset[tuple[str, str]]
    constraints: frozenset[tuple[str, str]]
    engine_routines: frozenset[str]


def validate_legacy_snapshot(snapshot: SchemaSnapshot) -> None:
    """Reject any database except a complete old Dodo 0061 schema."""
    if snapshot.version_rows != (EXPECTED_REVISION,):
        raise ValueError("expected exactly one Alembic revision row at legacy Dodo 0061")

    for table, columns in REQUIRED_COLUMNS.items():
        if table not in snapshot.tables or not columns.issubset(snapshot.columns.get(table, frozenset())):
            raise ValueError(f"legacy Dodo schema is incomplete at {table}")

    if not {"users", "subscriptions", "payments", "coupon_codes", "coupon_redemptions", "verification", "resumes", "compilations"}.issubset(snapshot.tables):
        raise ValueError("required base tables are missing")

    for table, name, columns in REQUIRED_UNIQUES:
        if (table, name, columns) not in snapshot.unique_constraints:
            raise ValueError(f"legacy Dodo unique constraint is missing: {name}")

    for table, name, source, target_table, target_column, ondelete in REQUIRED_FOREIGN_KEYS:
        if not any(
            fk_table == table
            and (name is None or fk_name == name)
            and source == fk_source
            and target_table == fk_target_table
            and target_column == fk_target_column
            and (ondelete is None or (fk_ondelete or "").upper() == ondelete)
            for fk_table, fk_name, fk_source, fk_target_table, fk_target_column, fk_ondelete in snapshot.foreign_keys
        ):
            raise ValueError(f"legacy Dodo foreign key is missing on {table}.{source}")

    if not {("billing_webhook_events", "ix_billing_webhook_events_status_received"),
            ("payment_refunds", "ix_payment_refunds_payment_id"),
            ("coupon_redemptions", "ix_coupon_redemptions_subscription_id")}.issubset(snapshot.indexes):
        raise ValueError("legacy Dodo supporting indexes are incomplete")

    verification_type = snapshot.column_types.get(("verification", "value"), "").lower()
    if "character varying(255)" not in verification_type and "varchar(255)" not in verification_type:
        raise ValueError("verification.value is not at the pre-OAuth 0059 type")

    required_column_specs = {
        ("subscriptions", "provider"): ("varchar(32)", False, "dodo"),
        ("subscriptions", "provider_subscription_id"): ("varchar(255)", True, None),
        ("subscriptions", "provider_checkout_session_id"): ("varchar(255)", True, None),
        ("subscriptions", "provider_customer_id"): ("varchar(255)", True, None),
        ("subscriptions", "provider_product_id"): ("varchar(255)", True, None),
        ("subscriptions", "quoted_amount"): ("integer", True, None),
        ("subscriptions", "discount_percent"): ("integer", False, "0"),
        ("subscriptions", "quoted_tax_inclusive"): ("boolean", True, None),
        ("payments", "provider"): ("varchar(32)", False, "dodo"),
        ("payments", "provider_payment_id"): ("varchar(255)", True, None),
        ("coupon_redemptions", "subscription_id"): ("uuid", True, None),
        ("coupon_redemptions", "status"): ("varchar(20)", False, "redeemed"),
        ("coupon_redemptions", "redeemed_at"): ("timestamp", True, "now()"),
    }
    for key, (expected_type, nullable, default_fragment) in required_column_specs.items():
        actual_type = snapshot.column_types.get(key, "").lower()
        actual_nullable = snapshot.column_nullable.get(key)
        actual_default = (snapshot.column_defaults.get(key) or "").lower()
        if expected_type not in actual_type or actual_nullable is not nullable:
            raise ValueError(f"legacy Dodo column definition does not match at {key[0]}.{key[1]}")
        if default_fragment is not None and default_fragment not in actual_default:
            raise ValueError(f"legacy Dodo default does not match at {key[0]}.{key[1]}")
        if default_fragment is None and actual_default:
            raise ValueError(f"legacy Dodo column unexpectedly has a default at {key[0]}.{key[1]}")

    for table, column in ENGINE_OUTPUT_COLUMNS:
        if column in snapshot.columns.get(table, frozenset()):
            raise ValueError(f"engine migration output already exists: {table}.{column}")
    if snapshot.tables.intersection(ENGINE_OUTPUT_TABLES):
        raise ValueError("engine migration output table already exists")
    if snapshot.constraints.intersection(ENGINE_OUTPUT_CONSTRAINTS):
        raise ValueError("engine migration output constraint already exists")
    if "latexy_resume_revision" in snapshot.engine_routines or "resumes_content_revision" in snapshot.engine_routines:
        raise ValueError("engine migration trigger or function already exists")


def validate_current_alembic_head(heads: list[str] | tuple[str, ...]) -> None:
    if tuple(sorted(heads)) != (TARGET_REVISION,):
        raise ValueError("bridge requires repository Alembic to have exactly one head at 0067")


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (datetime, date, Decimal, UUID)):
        return str(value)
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    return value


def _financial_fingerprints(connection: Any, inspector: Any) -> dict[str, dict[str, Any]]:
    report: dict[str, dict[str, Any]] = {}
    for table_name in FINANCIAL_TABLES:
        if table_name not in inspector.get_table_names():
            report[table_name] = {"count": 0, "sha256": hashlib.sha256(b"missing").hexdigest()}
            continue
        primary_key = inspector.get_pk_constraint(table_name).get("constrained_columns") or []
        if not primary_key:
            raise ValueError(f"cannot fingerprint financial table without a primary key: {table_name}")
        quoted = connection.dialect.identifier_preparer.quote(table_name)
        order = ", ".join(connection.dialect.identifier_preparer.quote(name) for name in primary_key)
        result = connection.execute(text(f"SELECT * FROM {quoted} ORDER BY {order}"))
        digest = hashlib.sha256()
        count = 0
        for row in result.mappings():
            encoded = json.dumps(_normalize(dict(row)), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            count += 1
        report[table_name] = {"count": count, "sha256": digest.hexdigest()}
    if "users" not in inspector.get_table_names():
        raise ValueError("users table is missing; cannot fingerprint entitlement state")
    preparer = connection.dialect.identifier_preparer
    selected = ", ".join(preparer.quote(name) for name in USER_ENTITLEMENT_COLUMNS)
    result = connection.execute(text(f"SELECT {selected} FROM users ORDER BY id"))
    digest = hashlib.sha256()
    count = 0
    for row in result.mappings():
        encoded = json.dumps(_normalize(dict(row)), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        count += 1
    report["user_entitlements"] = {"count": count, "sha256": digest.hexdigest()}
    return report


def _snapshot(connection: Any) -> SchemaSnapshot:
    inspector = inspect(connection)
    tables = frozenset(inspector.get_table_names())
    columns: dict[str, frozenset[str]] = {}
    column_types: dict[tuple[str, str], str] = {}
    column_nullable: dict[tuple[str, str], bool] = {}
    column_defaults: dict[tuple[str, str], str | None] = {}
    for table in tables:
        entries = inspector.get_columns(table)
        columns[table] = frozenset(entry["name"] for entry in entries)
        for entry in entries:
            key = (table, entry["name"])
            column_types[key] = str(entry["type"])
            column_nullable[key] = bool(entry["nullable"])
            column_defaults[key] = entry.get("default")

    uniques: set[tuple[str, str, tuple[str, ...]]] = set()
    foreign_keys: list[tuple[str, str | None, str, str, str, str | None]] = []
    indexes: set[tuple[str, str]] = set()
    constraints: set[tuple[str, str]] = set()
    for table in tables:
        for constraint in inspector.get_check_constraints(table):
            if constraint.get("name"):
                constraints.add((table, constraint["name"]))
        for constraint in inspector.get_unique_constraints(table):
            if constraint.get("name"):
                uniques.add((table, constraint["name"], tuple(constraint.get("column_names") or ())))
        for fk in inspector.get_foreign_keys(table):
            options = fk.get("options") or {}
            source_cols = fk.get("constrained_columns") or []
            target_cols = fk.get("referred_columns") or []
            if len(source_cols) == len(target_cols) == 1:
                foreign_keys.append((table, fk.get("name"), source_cols[0], fk.get("referred_table"), target_cols[0], options.get("ondelete")))
        for index in inspector.get_indexes(table):
            if index.get("name"):
                indexes.add((table, index["name"]))

    version_rows = tuple(row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num FOR UPDATE")))
    engine_routines = frozenset(
        row[0]
        for row in connection.execute(text(
            "SELECT proname FROM pg_proc WHERE proname = 'latexy_resume_revision' "
            "UNION SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname = 'resumes_content_revision'"
        ))
    )
    return SchemaSnapshot(
        version_rows=version_rows,
        tables=tables,
        columns=columns,
        column_types=column_types,
        column_nullable=column_nullable,
        column_defaults=column_defaults,
        unique_constraints=frozenset(uniques),
        foreign_keys=tuple(foreign_keys),
        indexes=frozenset(indexes),
        constraints=frozenset(constraints),
        engine_routines=engine_routines,
    )


def _validate_preserved_legacy_ids(connection: Any) -> None:
    for table, provider_id, legacy_id in (
        ("subscriptions", "provider_subscription_id", "razorpay_subscription_id"),
        ("payments", "provider_payment_id", "razorpay_payment_id"),
    ):
        mismatch = connection.execute(text(
            f"SELECT COUNT(*) FROM {table} WHERE provider = 'razorpay' "
            f"AND {provider_id} IS DISTINCT FROM {legacy_id}"
        )).scalar_one()
        if mismatch:
            raise ValueError(f"legacy provider identifiers are inconsistent in {table}")


def _validate_bridge_result(snapshot: SchemaSnapshot) -> None:
    if snapshot.version_rows != (TARGET_REVISION,):
        raise ValueError("migration bridge did not produce exact Alembic head 0067")
    for table, columns in REQUIRED_COLUMNS.items():
        if table not in snapshot.tables or not columns.issubset(snapshot.columns.get(table, frozenset())):
            raise ValueError(f"billing schema is incomplete after migration at {table}")
    for table, column in ENGINE_OUTPUT_COLUMNS:
        if column not in snapshot.columns.get(table, frozenset()):
            raise ValueError(f"engine migration output is missing after bridge: {table}.{column}")
    if not ENGINE_OUTPUT_TABLES.issubset(snapshot.tables):
        raise ValueError("engine migration output tables are incomplete after bridge")
    if not ENGINE_OUTPUT_CONSTRAINTS.issubset(snapshot.constraints):
        raise ValueError("engine migration constraints are incomplete after bridge")
    if not {"latexy_resume_revision", "resumes_content_revision"}.issubset(snapshot.engine_routines):
        raise ValueError("engine migration trigger/function are incomplete after bridge")
    verification_type = snapshot.column_types.get(("verification", "value"), "").lower()
    if "text" not in verification_type or snapshot.column_nullable.get(("verification", "value")) is not False:
        raise ValueError("OAuth migration did not preserve verification.value as non-null TEXT")
    for table, name, columns in REQUIRED_UNIQUES:
        if (table, name, columns) not in snapshot.unique_constraints:
            raise ValueError(f"billing unique constraint is missing after bridge: {name}")
    if not {
        ("billing_webhook_events", "ix_billing_webhook_events_status_received"),
        ("payment_refunds", "ix_payment_refunds_payment_id"),
        ("coupon_redemptions", "ix_coupon_redemptions_subscription_id"),
    }.issubset(snapshot.indexes):
        raise ValueError("billing supporting indexes are incomplete after bridge")


def _load_migration(revision: str) -> Any:
    path = MIGRATIONS / {
        "0059": "0059_verification_value_text.py",
        "0060": "0060_semantic_resume_engine.py",
        "0061": "0061_render_artifact_manifests.py",
        "0062": "0062_compilation_artifact_acceptance.py",
        "0063": "0063_imported_node_projection.py",
        "0064": "0064_private_original_pdf_imports.py",
    }[revision]
    spec = importlib.util.spec_from_file_location(f"legacy_dodo_bridge_{revision}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load migration {revision}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _database_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/").split("/", 1)[0]


def run(*, apply: bool, expected_database: str, allow_primary_local_database: bool = False) -> dict[str, Any]:
    # Import only after args are validated; no connection string is logged.
    sys.path.insert(0, str(BACKEND_ROOT))
    from app.core.config import settings

    alembic_config = Config()
    alembic_config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    validate_current_alembic_head(ScriptDirectory.from_config(alembic_config).get_heads())

    sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
    actual_database = _database_name(sync_url)
    if not expected_database or actual_database != expected_database:
        raise ValueError("configured database does not match --expected-database")
    if settings.normalized_environment not in {"development", "test"} or settings.normalized_dodo_mode != "test":
        raise ValueError("bridge requires development/test environment and DODO_MODE=test")
    if actual_database == "latexy" and not allow_primary_local_database:
        raise ValueError("refusing to run against the primary local database")
    if allow_primary_local_database and actual_database != "latexy":
        raise ValueError("--allow-primary-local-database is valid only for the exact database name latexy")

    engine = create_engine(sync_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            connection.execute(text("SET LOCAL statement_timeout = '60s'"))
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
            connection.execute(text(
                "LOCK TABLE alembic_version, users, subscriptions, payments, coupon_redemptions, "
                "billing_webhook_events, payment_refunds, coupon_codes IN SHARE MODE"
            ))
            snapshot = _snapshot(connection)
            validate_legacy_snapshot(snapshot)
            _validate_preserved_legacy_ids(connection)
            before = _financial_fingerprints(connection, inspect(connection))

            if apply:
                migration_context = MigrationContext.configure(connection)
                with Operations.context(migration_context):
                    for revision in ("0059", "0060", "0061", "0062", "0063", "0064"):
                        _load_migration(revision).upgrade()
                advanced = connection.execute(
                    text("UPDATE alembic_version SET version_num=:target WHERE version_num=:source"),
                    {"target": TARGET_REVISION, "source": EXPECTED_REVISION},
                )
                if advanced.rowcount != 1:
                    raise ValueError("Alembic marker changed during bridge; transaction rolled back")
                after_snapshot = _snapshot(connection)
                after = _financial_fingerprints(connection, inspect(connection))
                if after != before:
                    raise ValueError("financial rows changed during migration bridge; transaction rolled back")
                _validate_bridge_result(after_snapshot)
                _validate_preserved_legacy_ids(connection)
                result = {"mode": "applied", "from": EXPECTED_REVISION, "to": TARGET_REVISION,
                          "financial_rows_before": before, "financial_rows_after": after}
            else:
                result = {"mode": "dry_run", "from": EXPECTED_REVISION, "to": TARGET_REVISION,
                          "financial_rows": before}
        return result
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-database", required=True, help="exact database name already selected by backend settings")
    parser.add_argument("--dry-run", action="store_true", help="validate exact legacy schema and report protected fingerprints (default)")
    parser.add_argument("--apply", action="store_true", help="apply the validated bridge transaction")
    parser.add_argument("--allow-primary-local-database", action="store_true",
                        help="allow exact local database name 'latexy'; requires development/test and DODO_MODE=test")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("choose either --dry-run or --apply")
    try:
        result = run(apply=args.apply, expected_database=args.expected_database,
                     allow_primary_local_database=args.allow_primary_local_database)
    except ValueError as exc:
        # These bridge-owned messages contain schema names only.
        print(f"Bridge refused: {exc}")
        return 2
    except Exception as exc:
        # Driver exception text can contain SQL and data. Log only type.
        print(f"Bridge refused/failed ({type(exc).__name__}). No connection details or row values were emitted.")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
