"""Read-only, redacted Dodo deployment diagnostics; never contacts Dodo.

Run from the backend image: python scripts/dodo_billing_preflight.py
Exit 0: local readiness checks pass. Exit 1: readable deployment blockers.
Exit 2: diagnostics are incomplete. One allowlisted JSON object is always emitted.
The public catalog is local configuration, not a merchant-catalog verification.
"""
from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from dotenv import dotenv_values
from pydantic import NonNegativeInt, TypeAdapter
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HEAD = "0068"
PRODUCT_KEYS = {
    "basic": "BASIC_MONTHLY", "basic_annual": "BASIC_ANNUAL",
    "pro": "PRO_MONTHLY", "pro_annual": "PRO_ANNUAL",
    "byok": "BYOK_MONTHLY", "byok_annual": "BYOK_ANNUAL",
    "student": "STUDENT", "team": "TEAM", "weekly": "WEEKLY", "lifetime": "LIFETIME",
}
ENV_KEYS = {
    "BILLING_MODE", "DODO_MODE", "ENVIRONMENT", "DEPLOY_TARGET", "SKIP_ENV_VALIDATION", "DATABASE_URL", "SUBSCRIPTION_PLANS",
    "WEEKLY_AMOUNT_MINOR", "LIFETIME_AMOUNT_MINOR", "BILLING_CURRENCY",
    *(f"DODO_{mode}_{kind}" for mode in ("TEST", "LIVE") for kind in ("API_KEY", "WEBHOOK_KEY", "BUSINESS_ID")),
    *(f"DODO_{mode}_PRODUCT_{key}" for mode in ("TEST", "LIVE") for key in PRODUCT_KEYS.values()),
}
PAID_PLANS = (*PRODUCT_KEYS, "basic_monthly", "pro_monthly", "byok_monthly", "student_monthly", "team_monthly")
TABLES = ("users", "subscriptions", "team_seats", "alembic_version", "resume_optimization_runs",
          "render_artifact_manifests", "billing_webhook_events", "payment_refunds", "payments", "coupon_redemptions")
CURRENT_BILLING_COLUMNS = {
    "users": {"id", "subscription_plan", "subscription_status", "subscription_id"},
    "subscriptions": {"id", "user_id", "plan_id", "status", "provider", "provider_subscription_id",
                      "provider_checkout_session_id", "provider_customer_id", "provider_product_id", "provider_event_at",
                      "quoted_amount", "discount_percent", "quoted_tax_inclusive", "current_period_start", "current_period_end"},
    "payments": {"id", "user_id", "subscription_id", "provider", "provider_payment_id", "provider_event_at",
                 "amount", "currency", "status"},
    "billing_webhook_events": {"id", "provider", "event_id", "event_type", "payload_sha256", "event_at", "status",
                               "attempts", "last_error", "received_at", "processed_at", "event_resource_id"},
    "payment_refunds": {"id", "payment_id", "provider", "provider_refund_id", "amount", "currency", "status", "reason", "created_at"},
    "coupon_redemptions": {"id", "coupon_id", "user_id", "subscription_id", "status", "redeemed_at"},
    "team_seats": {"owner_user_id", "member_user_id", "status"},
}


def read_environment(environ: Mapping[str, str] | None = None, backend_root: Path = BACKEND_ROOT) -> dict[str, str]:
    """Match Settings file precedence without initializing Settings or the app."""
    values: dict[str, str] = {}
    for path in (backend_root.parent / ".env", backend_root / ".env"):
        if path.is_file():
            values.update({k: v for k, v in dotenv_values(path).items() if k in ENV_KEYS and k != "SKIP_ENV_VALIDATION" and v is not None})
    values.update({k: v for k, v in (os.environ if environ is None else environ).items() if k in ENV_KEYS})
    return values


def public_defaults(backend_root: Path = BACKEND_ROOT) -> dict[str, Any]:
    # Literal evaluation never runs configuration code, validators or imports.
    tree = ast.parse((backend_root / "app/core/config.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings")
    field = next(n for n in cls.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
                 and n.target.id == "SUBSCRIPTION_PLANS")
    return ast.literal_eval(next(k.value for k in field.value.keywords if k.arg == "default"))


def known_revisions(backend_root: Path = BACKEND_ROOT) -> set[str]:
    revisions = set()
    for path in (backend_root / "alembic/versions").glob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "revision" for t in node.targets):
                revisions.add(ast.literal_eval(node.value))
    return revisions


def configuration_report(env: Mapping[str, str], backend_root: Path = BACKEND_ROOT) -> tuple[dict, list[str]]:
    billing = (env.get("BILLING_MODE") or "auto").strip().lower()
    mode = (env.get("DODO_MODE") or "test").strip().lower()
    environment = (env.get("ENVIRONMENT") or "development").strip().lower()
    deploy_target = (env.get("DEPLOY_TARGET") or "local").strip().lower()
    production = environment in {"production", "staging"}
    valid_mode = mode in {"test", "live"}
    prefix = "DODO_LIVE" if mode == "live" else "DODO_TEST"
    report = {
        "billing_mode": billing if billing in {"auto", "required", "disabled"} else "invalid",
        "dodo_mode": mode if valid_mode else "invalid", "production_like": production,
        "environment": environment if environment in {"development", "dev", "test", "testing", "staging", "production"} else "invalid",
        "deploy_target": deploy_target if deploy_target in {"local", "modal"} else "invalid",
        "skip_env_validation": env.get("SKIP_ENV_VALIDATION") == "true",
        "active_business_id_present": bool(valid_mode and env.get(prefix + "_BUSINESS_ID")),
        "active_api_key_present": bool(valid_mode and env.get(prefix + "_API_KEY")),
        "active_webhook_key_present": bool(valid_mode and env.get(prefix + "_WEBHOOK_KEY")),
        "catalog_verification": "local_expectations_only_not_provider_verified", "skus": {},
    }
    startup_reasons = []
    optional_amounts = {}
    for sku in ("weekly", "lifetime"):
        try:
            optional_amounts[sku] = TypeAdapter(NonNegativeInt).validate_python(env.get(f"{sku.upper()}_AMOUNT_MINOR", "0"))
        except Exception:
            optional_amounts[sku] = None
            startup_reasons.append("invalid_optional_sku_amount")
    if report["billing_mode"] == "invalid" or not valid_mode:
        startup_reasons.append("invalid_billing_mode")
    any_key = report["active_api_key_present"] or report["active_webhook_key_present"]
    both_keys = report["active_api_key_present"] and report["active_webhook_key_present"]
    if billing != "disabled" and production and any_key and mode != "live":
        startup_reasons.append("production_test_credentials_not_allowed")
    if billing == "required" and not both_keys:
        startup_reasons.append("required_credentials_missing")
    if billing != "disabled" and any_key and not both_keys:
        startup_reasons.append("partial_active_credentials")
    report.update(startup_configuration_valid=not startup_reasons,
                  startup_configuration_reasons=startup_reasons,
                  startup_validation_scope="strict_billing_rules_only_without_skip_bypass")
    blockers = list(startup_reasons)
    if report["environment"] == "invalid" or report["deploy_target"] == "invalid":
        blockers.append("unrecognized_environment_context")
    if billing == "disabled":
        blockers.append("billing_disabled")
    if production and mode != "live":
        blockers.append("production_requires_live_mode")
    if not report["active_api_key_present"] or not report["active_webhook_key_present"]:
        blockers.append("active_credentials_incomplete")
    catalog = public_defaults(backend_root)
    try:
        if "SUBSCRIPTION_PLANS" in env:
            catalog = json.loads(env["SUBSCRIPTION_PLANS"])
        if not isinstance(catalog, dict):
            raise ValueError
    except (ValueError, TypeError):
        catalog = {}
        startup_reasons.append("invalid_local_catalog")
        blockers.append("invalid_local_catalog")
    for sku, key in PRODUCT_KEYS.items():
        plan = catalog.get(sku, {})
        if not isinstance(plan, dict):
            plan = {}
        price, currency, interval = plan.get("price"), plan.get("currency"), plan.get("interval")
        if sku in {"weekly", "lifetime"}:
            price = optional_amounts[sku]
            currency = env.get("BILLING_CURRENCY", "INR").upper()
        price = price if type(price) is int and 0 <= price < 10**12 else None
        currency = currency if isinstance(currency, str) and re.fullmatch(r"[A-Z]{3}", currency) else None
        interval = interval if isinstance(interval, str) and interval in {"day", "week", "month", "year", "lifetime"} else None
        tax = plan.get("tax_inclusive", True)
        tax = tax if type(tax) is bool else None
        mapped = bool(valid_mode and env.get(prefix + "_PRODUCT_" + key))
        valid = price is not None and price > 0 and currency is not None and interval is not None and tax is not None
        report["skus"][sku] = {"product_id_configured": mapped, "configured": bool(mapped and valid),
                               "price_minor": price, "currency": currency, "interval": interval, "tax_inclusive": tax}
        if mapped and not valid:
            blockers.append("invalid_configured_sku_expectations")
    if not any(sku["configured"] for sku in report["skus"].values()):
        blockers.append("no_paid_sku_configured")
    blockers = list(dict.fromkeys(blockers))
    report.update(checkout_configuration_available=not blockers, checkout_configuration_reasons=list(blockers),
                  startup_configuration_valid=not startup_reasons,
                  startup_configuration_reasons=list(dict.fromkeys(startup_reasons)))
    return report, blockers


def classify_schema(revisions: list[str], columns: dict[str, set[str]], known: set[str]) -> str:
    if len(revisions) != 1 or revisions[0] not in known:
        return "unknown_requires_review"
    revision = revisions[0]
    dodo = {"provider", "provider_subscription_id"}.issubset(columns.get("subscriptions", set()))
    engine = {"render_artifact_manifests", "resume_optimization_runs"}.issubset(columns)
    any_dodo_columns = any(name == "provider" or name.startswith("provider_")
                           for table in ("subscriptions", "payments") for name in columns.get(table, set()))
    any_dodo_schema = any_dodo_columns or bool({"billing_webhook_events", "payment_refunds"} & columns.keys())
    if revision == "0061":
        if dodo and not engine and {"billing_webhook_events", "payment_refunds"}.issubset(columns):
            return "legacy_dodo_0061_requires_bridge_validation"
        if engine and not any_dodo_schema:
            return "known_mainline_pre_dodo"
        return "ambiguous_0061_requires_review"
    if revision in {"0065", "0066", "0067", "0068"}:
        if not dodo or not engine:
            return "schema_revision_mismatch_requires_review"
        if revision == EXPECTED_HEAD:
            return ("current_dodo_head" if all(required <= columns.get(table, set())
                                              for table, required in CURRENT_BILLING_COLUMNS.items())
                    else "schema_revision_mismatch_requires_review")
        return "known_mainline_dodo_upgrade_required"
    engine_expected = revision in {"0060", "0062", "0063", "0064"}
    engine_present = "resume_optimization_runs" in columns if revision == "0060" else engine
    if any_dodo_schema or (engine_expected and not engine_present):
        return "schema_revision_mismatch_requires_review"
    return "known_mainline_pre_dodo"


def aggregate_counts(connection, columns: dict[str, set[str]]) -> dict[str, int]:
    if not {"id", "subscription_plan", "subscription_id"}.issubset(columns.get("users", set())):
        raise ValueError("unsupported_schema")
    subscription_columns = columns.get("subscriptions", set())
    historical = "FALSE"
    if {"id", "user_id"}.issubset(subscription_columns):
        identity = ["CAST(s.id AS text) = u.subscription_id"]
        for name in ("razorpay_subscription_id", "provider_subscription_id"):
            if name in subscription_columns:
                identity.append(f"s.{name} = u.subscription_id")
        provider = "s.provider = 'razorpay'" if "provider" in subscription_columns else "TRUE"
        historical = ("EXISTS (SELECT 1 FROM public.subscriptions s WHERE s.user_id=u.id AND "
                      + provider + " AND (" + " OR ".join(identity) + "))")
    # Raw pointers remain relevant even if a historical intent row is missing.
    cte = f"""WITH paid AS (
        SELECT u.id, u.subscription_plan FROM public.users u
        WHERE u.subscription_plan = ANY(:paid_plans)
          AND u.subscription_id IS NOT NULL AND u.subscription_id <> ''
          AND (u.subscription_id ~ '^(sub_|order_)' OR {historical})
    ) """
    result = connection.execute(text(cte + """SELECT
        (SELECT COUNT(*) FROM public.users WHERE subscription_plan = ANY(:paid_plans)
          AND subscription_id IS NOT NULL AND subscription_id <> '') AS paid_pointer_users,
        COUNT(*) AS historical_paid_pointer_users,
        COUNT(*) FILTER (WHERE subscription_plan IN ('team','team_monthly')) AS historical_team_owners
        FROM paid"""), {"paid_plans": list(PAID_PLANS)}).mappings().one()
    counts = {key: int(value) for key, value in result.items()}
    if {"owner_user_id", "status", "member_user_id"}.issubset(columns.get("team_seats", set())):
        counts["active_seats_inheriting_historical_owners"] = int(connection.scalar(text(cte + """
            SELECT COUNT(*) FROM public.team_seats t JOIN paid p ON p.id=t.owner_user_id
            WHERE p.subscription_plan IN ('team','team_monthly') AND t.status='active'
              AND t.member_user_id IS NOT NULL"""), {"paid_plans": list(PAID_PLANS)}))
    elif "team_seats" not in columns:
        counts["active_seats_inheriting_historical_owners"] = 0
    else:
        raise ValueError("unsupported_schema")
    mandate_ids = [f"s.{name} IS NOT NULL" for name in ("razorpay_subscription_id", "provider_subscription_id")
                   if name in subscription_columns]
    if mandate_ids and {"user_id", "status"}.issubset(subscription_columns):
        provider_filter = "s.provider='razorpay' AND " if "provider" in subscription_columns else ""
        counts["historical_live_mandate_users"] = int(connection.scalar(text(
            "SELECT COUNT(DISTINCT s.user_id) FROM public.subscriptions s WHERE " + provider_filter
            + "(" + " OR ".join(mandate_ids) + ") AND s.status = ANY(:live_statuses)"
        ), {"live_statuses": ["active", "created", "authenticated", "pending", "halted", "paused", "cancel_scheduled"]}))
    else:
        raise ValueError("unsupported_schema")
    return counts


def database_report(database_url: str, *, backend_root: Path = BACKEND_ROOT, engine_factory=create_engine) -> dict:
    if not database_url:
        raise ValueError("database_unconfigured")
    url = make_url(re.sub(r"^postgres://", "postgresql://", database_url))
    if url.get_backend_name() != "postgresql":
        raise ValueError("unsupported_database")
    url = url.set(drivername="postgresql+psycopg2")
    engine = engine_factory(url, echo=False, hide_parameters=True, isolation_level="REPEATABLE READ",
                            connect_args={"connect_timeout": 5, "options":
                                "-c default_transaction_read_only=on -c statement_timeout=10000 -c lock_timeout=2000"})
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                if connection.scalar(text("SHOW transaction_read_only")) != "on":
                    raise ValueError("read_only_required")
                rows = connection.execute(text("""SELECT table_name,column_name FROM information_schema.columns
                    WHERE table_schema='public' AND table_name = ANY(:tables)"""), {"tables": list(TABLES)})
                columns: dict[str, set[str]] = {}
                for table, column in rows:
                    columns.setdefault(table, set()).add(column)
                revisions = list(connection.scalars(text("SELECT version_num FROM public.alembic_version ORDER BY version_num")))
                known = known_revisions(backend_root)
                return {"status": "read_only_complete", "alembic_revisions": [r if r in known else "unrecognized" for r in revisions],
                        "schema_classification": classify_schema(revisions, columns, known),
                        "counts": aggregate_counts(connection, columns)}
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def collect_report(environ: Mapping[str, str] | None = None, *, backend_root: Path = BACKEND_ROOT,
                   engine_factory=create_engine) -> tuple[dict, int]:
    report: dict[str, Any] = {}
    try:
        env = read_environment(environ, backend_root)
        report, blockers = configuration_report(env, backend_root)
        report["database"] = database_report(env.get("DATABASE_URL", ""), backend_root=backend_root,
                                             engine_factory=engine_factory)
        database = report["database"]
        if database["schema_classification"] != "current_dodo_head":
            blockers.append("database_migration_or_review_required")
        if database["counts"]["historical_paid_pointer_users"]:
            blockers.append("historical_paid_accounts_require_cutover_review")
        if database["counts"]["historical_live_mandate_users"]:
            blockers.append("historical_live_mandates_require_cutover_review")
        report.update(status="blocked" if blockers else "ready", blockers=blockers)
        return report, 1 if blockers else 0
    except Exception:
        # Never format exceptions: driver/parser messages may contain credentials,
        # environment values, SQL parameters or customer data.
        report.update(status="diagnostic_error", blockers=["diagnostics_incomplete"],
                      database={"status": "unavailable_or_unsupported"})
        return report, 2


def main() -> int:
    report, exit_code = collect_report()
    print(json.dumps(report, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
