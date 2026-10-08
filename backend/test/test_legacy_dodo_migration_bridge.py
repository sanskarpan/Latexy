from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.bridge_legacy_dodo_0061 import (
    ENGINE_OUTPUT_COLUMNS,
    ENGINE_OUTPUT_CONSTRAINTS,
    ENGINE_OUTPUT_TABLES,
    REQUIRED_COLUMNS,
    REQUIRED_FOREIGN_KEYS,
    REQUIRED_UNIQUES,
    SchemaSnapshot,
    _validate_bridge_result,
    validate_current_alembic_head,
    validate_legacy_snapshot,
)


def complete_legacy_snapshot() -> SchemaSnapshot:
    tables = {
        "users", "subscriptions", "payments", "coupon_redemptions", "coupon_codes",
        "billing_webhook_events", "payment_refunds", "verification", "resumes",
        "compilations",
    }
    columns = {table: set(values) for table, values in REQUIRED_COLUMNS.items()}
    columns.update({
        "subscriptions": columns["subscriptions"] | {"id", "user_id", "status"},
        "payments": columns["payments"] | {"id", "user_id", "subscription_id", "status"},
        "coupon_redemptions": columns["coupon_redemptions"] | {"id", "coupon_id", "user_id"},
        "coupon_codes": set(REQUIRED_COLUMNS["coupon_codes"]),
        "verification": {"id", "value"},
        "resumes": {"id", "latex_content", "structured_content"},
        "compilations": {"id"},
    })
    foreign_keys = set(REQUIRED_FOREIGN_KEYS)
    foreign_keys.add(("payment_refunds", "fk_payment_refunds_payment_id_payments", "payment_id", "payments", "id", "RESTRICT"))
    return SchemaSnapshot(
        version_rows=("0061",),
        tables=frozenset(tables),
        columns={table: frozenset(values) for table, values in columns.items()},
        column_types={
            ("verification", "value"): "VARCHAR(255)",
            ("subscriptions", "provider"): "VARCHAR(32)",
            ("subscriptions", "provider_subscription_id"): "VARCHAR(255)",
            ("subscriptions", "provider_checkout_session_id"): "VARCHAR(255)",
            ("subscriptions", "provider_customer_id"): "VARCHAR(255)",
            ("subscriptions", "provider_product_id"): "VARCHAR(255)",
            ("subscriptions", "quoted_amount"): "INTEGER",
            ("subscriptions", "discount_percent"): "INTEGER",
            ("subscriptions", "quoted_tax_inclusive"): "BOOLEAN",
            ("payments", "provider"): "VARCHAR(32)",
            ("payments", "provider_payment_id"): "VARCHAR(255)",
            ("coupon_redemptions", "subscription_id"): "UUID",
            ("coupon_redemptions", "status"): "VARCHAR(20)",
            ("coupon_redemptions", "redeemed_at"): "TIMESTAMP",
        },
        column_nullable={
            ("subscriptions", "provider"): False,
            ("subscriptions", "provider_subscription_id"): True,
            ("subscriptions", "provider_checkout_session_id"): True,
            ("subscriptions", "provider_customer_id"): True,
            ("subscriptions", "provider_product_id"): True,
            ("subscriptions", "quoted_amount"): True,
            ("subscriptions", "discount_percent"): False,
            ("subscriptions", "quoted_tax_inclusive"): True,
            ("payments", "provider"): False,
            ("payments", "provider_payment_id"): True,
            ("coupon_redemptions", "subscription_id"): True,
            ("coupon_redemptions", "status"): False,
            ("coupon_redemptions", "redeemed_at"): True,
        },
        column_defaults={
            ("subscriptions", "provider"): "'dodo'::character varying",
            ("subscriptions", "provider_subscription_id"): None,
            ("subscriptions", "provider_checkout_session_id"): None,
            ("subscriptions", "provider_customer_id"): None,
            ("subscriptions", "provider_product_id"): None,
            ("subscriptions", "quoted_amount"): None,
            ("subscriptions", "discount_percent"): "0",
            ("subscriptions", "quoted_tax_inclusive"): None,
            ("payments", "provider"): "'dodo'::character varying",
            ("payments", "provider_payment_id"): None,
            ("coupon_redemptions", "subscription_id"): None,
            ("coupon_redemptions", "status"): "'redeemed'::character varying",
            ("coupon_redemptions", "redeemed_at"): "now()",
        },
        unique_constraints=frozenset(REQUIRED_UNIQUES),
        foreign_keys=tuple(foreign_keys),
        indexes=frozenset({
            ("billing_webhook_events", "ix_billing_webhook_events_status_received"),
            ("payment_refunds", "ix_payment_refunds_payment_id"),
            ("coupon_redemptions", "ix_coupon_redemptions_subscription_id"),
        }),
        constraints=frozenset(),
        engine_routines=frozenset(),
    )


def test_accepts_complete_pre_renumbering_dodo_schema() -> None:
    validate_legacy_snapshot(complete_legacy_snapshot())


@pytest.mark.parametrize("revision", [("0061", "0067"), (), ("0061", "0061")])
def test_rejects_unexpected_or_ambiguous_revision_rows(revision: tuple[str, ...]) -> None:
    snapshot = replace(complete_legacy_snapshot(), version_rows=revision)

    with pytest.raises(ValueError, match="exactly one Alembic revision row"):
        validate_legacy_snapshot(snapshot)


def test_rejects_new_engine_0061_schema_without_legacy_billing_columns() -> None:
    snapshot = complete_legacy_snapshot()
    columns = dict(snapshot.columns)
    columns["payments"] = columns["payments"] - {"provider_payment_id"}

    with pytest.raises(ValueError, match="legacy Dodo schema is incomplete at payments"):
        validate_legacy_snapshot(replace(snapshot, columns=columns))


def test_rejects_partially_applied_billing_schema() -> None:
    snapshot = complete_legacy_snapshot()
    constraints = snapshot.unique_constraints - {
        ("payments", "uq_payments_provider_payment_id", ("provider", "provider_payment_id")),
    }

    with pytest.raises(ValueError, match="legacy Dodo unique constraint is missing"):
        validate_legacy_snapshot(replace(snapshot, unique_constraints=constraints))


def test_rejects_engine_schema_already_partially_applied() -> None:
    snapshot = complete_legacy_snapshot()
    tables = snapshot.tables | {"render_artifact_manifests"}

    with pytest.raises(ValueError, match="engine migration output table already exists"):
        validate_legacy_snapshot(replace(snapshot, tables=tables))


def test_rejects_existing_engine_trigger_even_if_columns_were_removed() -> None:
    snapshot = complete_legacy_snapshot()

    with pytest.raises(ValueError, match="engine migration trigger or function already exists"):
        validate_legacy_snapshot(replace(snapshot, engine_routines=frozenset({"latexy_resume_revision"})))


def test_requires_exact_0067_and_nonnull_text_oauth_value_after_bridge() -> None:
    snapshot = complete_legacy_snapshot()
    columns = dict(snapshot.columns)
    for table, column in ENGINE_OUTPUT_COLUMNS:
        columns[table] = columns.get(table, frozenset()) | {column}
    types = dict(snapshot.column_types)
    types[("verification", "value")] = "TEXT"
    nullable = dict(snapshot.column_nullable)
    nullable[("verification", "value")] = False
    target = replace(
        snapshot,
        version_rows=("0067",),
        tables=snapshot.tables | ENGINE_OUTPUT_TABLES,
        columns=columns,
        column_types=types,
        column_nullable=nullable,
        constraints=snapshot.constraints | ENGINE_OUTPUT_CONSTRAINTS,
        engine_routines=frozenset({"latexy_resume_revision", "resumes_content_revision"}),
    )
    _validate_bridge_result(target)

    with pytest.raises(ValueError, match="exact Alembic head 0067"):
        _validate_bridge_result(replace(target, version_rows=("0066",)))
    with pytest.raises(ValueError, match="non-null TEXT"):
        _validate_bridge_result(replace(target, column_nullable={**nullable, ("verification", "value"): True}))


def test_rejects_changed_legacy_identifier_column_shape() -> None:
    snapshot = complete_legacy_snapshot()
    column_types = dict(snapshot.column_types)
    column_types[("payments", "provider_payment_id")] = "INTEGER"

    with pytest.raises(ValueError, match="column definition does not match"):
        validate_legacy_snapshot(replace(snapshot, column_types=column_types))


def test_bridge_requires_repository_graph_to_have_exactly_one_0067_head() -> None:
    validate_current_alembic_head(["0067"])

    with pytest.raises(ValueError, match="exactly one head at 0067"):
        validate_current_alembic_head(["0067", "0068"])
    with pytest.raises(ValueError, match="exactly one head at 0067"):
        validate_current_alembic_head(["0068"])
