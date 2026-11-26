"""Admin saved views and reusable cohort segments.

Saved views are owner-scoped snapshots of an admin tab: an allowlisted scope,
validated filter values, a bounded column list, an optional sort, and a range.
Segments are a small typed filter DSL compiled by this module into fixed
SQLAlchemy expressions. Nothing here accepts SQL, identifiers, column names or
free-form query fragments from a caller.

Privacy boundary
----------------
* Only aggregate counts and suppressed breakdown buckets leave this module.
  Per-user rows, emails, names, documents, prompts, IPs and user agents are
  never selected or returned.
* Five distinct users are required before a count or a breakdown bucket is
  shown. Smaller cohorts return ``suppressed: true`` with ``count: null``.
* Names and descriptions are bounded and rejected when they contain email
  addresses, national identifiers, credentials or document markers.

Writes are audited in the same transaction as the change. Private rows are
visible only to their owner; shared rows are readable by other admins and
remain editable only by the owner. Updates and deletes require the current
``version`` (optimistic concurrency) and deletes are soft.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

from sqlalchemy import and_, exists, func, not_, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES
from ..database import models
from .admin_audit_service import AdminActor, record_admin_audit
from .client_environment import normalize_country_code

MIN_COHORT_SIZE = 5
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50
MAX_NAME_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 280
MAX_FILTER_KEYS = 10
MAX_FILTER_VALUES = 20
MAX_COLUMNS = 20
MAX_CONDITIONS = 12
MAX_SEGMENT_VALUES = 50

VIEW_SCOPES: tuple[str, ...] = (
    "analytics",
    "operations",
    "quality",
    "billing",
    "subscriptions",
    "email",
    "growth",
    "customers",
)

COUNTRY_UNKNOWN = "unknown"
PLAN_FAMILIES: tuple[str, ...] = tuple(sorted(set(PLAN_FAMILY_ALIASES.values())))
ROLES: tuple[str, ...] = ("user", "support", "admin")

COMPILERS = frozenset({"pdflatex", "xelatex", "lualatex"})
OPERATION_STATUSES = frozenset({"open", "resolved"})
SEVERITIES = frozenset({"critical", "high", "medium", "low"})
BILLING_STATUSES = frozenset(
    {"active", "trialing", "past_due", "cancelled", "expired", "paused", "unknown"}
)
EMAIL_STATUSES = frozenset({"delivered", "bounced", "complained", "failed", "pending", "unknown"})

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,:/()_+&'\-]{1,79}$")
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_FEATURE_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")
_SERVICE_RE = re.compile(r"^[a-z][a-z0-9_.\-]{1,39}$")
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_SECRET_RE = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._\-]{12,}|sk_(?:live|test)_[a-z0-9]{8,}|"
    r"ghp_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,}|"
    r"xox[baprs]-[a-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"api[_-]?key\s*[:=]\s*\S{8,}|password\s*[:=]\s*\S{4,})"
)
_DOCUMENT_RE = re.compile(
    r"\\(?:documentclass|begin\s*\{\s*(?:document|resume|coverletter)|section\s*\{)",
    re.IGNORECASE,
)

SCHEMA_VERSION = 1


class SavedViewsError(ValueError):
    """Validation failure mapped to HTTP 422 by the route layer."""


class DuplicateNameError(ValueError):
    """An active view/segment with the same owner and name already exists."""


class VersionConflictError(RuntimeError):
    """The caller's version token is stale; mapped to HTTP 409."""


class ViewPermissionError(PermissionError):
    """The actor may read but not mutate another admin's shared row."""


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    normalized = _as_utc(value)
    return normalized.isoformat() if normalized else None


_PHONE_SHAPE_RE = re.compile(r"[+\d][\d\s().-]{7,}\d")


def _reject_identifiers(text: str, *, field: str) -> None:
    if _EMAIL_RE.search(text) or _SSN_RE.search(text) or _SECRET_RE.search(text):
        raise SavedViewsError(f"{field} must not contain customer identifiers or credentials")
    if _DOCUMENT_RE.search(text):
        raise SavedViewsError(f"{field} must not contain document content")
    # A 9+ digit run that looks like a phone number is rejected too. Eight-digit
    # date labels such as "2026-11-27" stay valid.
    if len(re.sub(r"\D", "", text)) >= 9 and _PHONE_SHAPE_RE.search(text):
        raise SavedViewsError(f"{field} must not contain customer phone numbers")


def _clean_name(value: Any) -> tuple[str, str]:
    if not isinstance(value, str):
        raise SavedViewsError("name must be text")
    cleaned = " ".join(value.split())
    if not (2 <= len(cleaned) <= MAX_NAME_LENGTH):
        raise SavedViewsError(f"name must be 2-{MAX_NAME_LENGTH} characters")
    if not _NAME_RE.fullmatch(cleaned):
        raise SavedViewsError(
            "name may only contain letters, digits, spaces and . , : / ( ) _ + & ' -"
        )
    _reject_identifiers(cleaned, field="name")
    return cleaned, cleaned.casefold()


def _clean_description(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SavedViewsError("description must be text")
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    if len(cleaned) > MAX_DESCRIPTION_LENGTH:
        raise SavedViewsError(f"description must be at most {MAX_DESCRIPTION_LENGTH} characters")
    _reject_identifiers(cleaned, field="description")
    return cleaned


def _expect_str(value: Any, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise SavedViewsError(f"{field} must be text")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_length:
        raise SavedViewsError(f"{field} must be 1-{max_length} characters")
    return cleaned


def _enum(allowed: Iterable[str], *, field: str) -> Callable[[Any], str]:
    values = frozenset(allowed)

    def validate(value: Any) -> str:
        if not isinstance(value, str):
            raise SavedViewsError(f"{field} must be text")
        normalized = value.strip().lower()
        if normalized not in values:
            raise SavedViewsError(f"{field} must be one of: {', '.join(sorted(values))}")
        return normalized

    return validate


def _bounded_pattern(pattern: re.Pattern[str], *, field: str, lower: bool = False) -> Callable[[Any], str]:
    def validate(value: Any) -> str:
        if not isinstance(value, str):
            raise SavedViewsError(f"{field} must be text")
        normalized = value.strip()
        if lower:
            normalized = normalized.lower()
        if not normalized or not pattern.fullmatch(normalized):
            raise SavedViewsError(f"{field} has an invalid format")
        return normalized

    return validate


def _uuid_value(value: Any) -> str:
    if not isinstance(value, str) or not _UUID_RE.fullmatch(value.strip()):
        raise SavedViewsError("value must be a UUID")
    return value.strip().lower()


def _date_value(value: Any) -> str:
    if not isinstance(value, str):
        raise SavedViewsError("date values must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError as exc:
        raise SavedViewsError("date values must use YYYY-MM-DD") from exc
    return parsed.isoformat()


def _bool_value(value: Any) -> bool:
    if not isinstance(value, bool):
        raise SavedViewsError("value must be true or false")
    return value


def _month_value(value: Any) -> str:
    if not isinstance(value, str):
        raise SavedViewsError("signup_month must use YYYY-MM")
    match = _MONTH_RE.fullmatch(value.strip())
    if not match:
        raise SavedViewsError("signup_month must use YYYY-MM")
    year = int(match.group(1))
    if year < 2000 or year > 2100:
        raise SavedViewsError("signup_month year is out of range")
    return value.strip()


def _plan_value(value: Any) -> str:
    if not isinstance(value, str):
        raise SavedViewsError("plan must be text")
    normalized = value.strip().lower()
    if normalized not in PLAN_FAMILY_ALIASES and normalized not in PLAN_FAMILIES:
        raise SavedViewsError("plan must be a known plan family or SKU")
    return normalized


def _country_value(value: Any) -> str:
    if not isinstance(value, str):
        raise SavedViewsError("country_bucket must be an ISO alpha-2 code or unknown")
    normalized = value.strip().lower()
    if normalized == COUNTRY_UNKNOWN:
        return COUNTRY_UNKNOWN
    code = normalize_country_code(value)
    if code is None:
        raise SavedViewsError("country_bucket must be an ISO alpha-2 code or unknown")
    return code


def _feature_value(value: Any) -> str:
    if not isinstance(value, str):
        raise SavedViewsError("feature values must be text")
    normalized = value.strip()
    if not _FEATURE_RE.fullmatch(normalized):
        raise SavedViewsError("feature values contain unsupported characters")
    return normalized


def _service_value(value: Any) -> str:
    return _bounded_pattern(_SERVICE_RE, field="service", lower=True)(value)


def _tenant_value(value: Any) -> str:
    return _bounded_pattern(_SLUG_RE, field="tenant", lower=True)(value)


def _opaque_value(value: Any) -> str:
    return _bounded_pattern(_OPAQUE_ID_RE, field="value")(value)


def _status_for(scope: str) -> Callable[[Any], str]:
    if scope == "operations":
        return _enum(OPERATION_STATUSES, field="status")
    if scope in {"billing", "subscriptions"}:
        return _enum(BILLING_STATUSES, field="status")
    if scope == "email":
        return _enum(EMAIL_STATUSES, field="status")
    return _enum(frozenset({"active", "inactive", "unknown"}), field="status")


def _filter_validators(scope: str) -> dict[str, Callable[[Any], Any]]:
    """Return the exact allowlisted view filters for one admin tab."""
    common: dict[str, Callable[[Any], Any]] = {"plan": _plan_value}
    if scope == "analytics":
        return {
            **common,
            "compiler": _enum(COMPILERS, field="compiler"),
            "template": _uuid_value,
            "feature": _feature_value,
        }
    if scope == "operations":
        return {
            "status": _status_for(scope),
            "severity": _enum(SEVERITIES, field="severity"),
            "service": _service_value,
            "start_date": _date_value,
            "end_date": _date_value,
        }
    if scope == "quality":
        return {
            **common,
            "compiler": _enum(COMPILERS, field="compiler"),
        }
    if scope == "billing":
        return {"status": _status_for(scope), "plan": _plan_value}
    if scope == "subscriptions":
        return {"status": _status_for(scope), "plan": _plan_value}
    if scope == "email":
        return {"status": _status_for(scope)}
    if scope == "growth":
        return {"plan": _plan_value}
    if scope == "customers":
        return {
            "plan": _plan_value,
            "role": _enum(ROLES, field="role"),
            "verified": _bool_value,
        }
    raise SavedViewsError("unknown saved-view scope")


SCOPE_COLUMNS: dict[str, frozenset[str]] = {
    "analytics": frozenset({"kpis", "funnel", "timeseries", "features", "operations", "events"}),
    "operations": frozenset({"incidents", "artifacts"}),
    "quality": frozenset({"templates", "content", "optimization", "linter"}),
    "billing": frozenset({"revenue", "dunning"}),
    "subscriptions": frozenset({"subscriptions", "dunning"}),
    "email": frozenset({"deliverability", "bounces"}),
    "growth": frozenset({"growth", "cost"}),
    "customers": frozenset({"users"}),
}

SCOPE_SORT_FIELDS: dict[str, frozenset[str]] = {
    "analytics": frozenset({"days", "plan", "compiler", "feature"}),
    "operations": frozenset({"status", "severity", "service", "start_date"}),
    "quality": frozenset({"days", "plan", "compiler"}),
    "billing": frozenset({"days", "status", "plan"}),
    "subscriptions": frozenset({"days", "status", "plan"}),
    "email": frozenset({"days", "status"}),
    "growth": frozenset({"days", "plan"}),
    "customers": frozenset({"plan", "role", "verified"}),
}


def _validate_filter_value(validator: Callable[[Any], Any], value: Any, *, key: str) -> Any:
    if isinstance(value, list):
        if not (1 <= len(value) <= MAX_FILTER_VALUES):
            raise SavedViewsError(f"filters.{key} must contain 1-{MAX_FILTER_VALUES} values")
        normalized: list[Any] = []
        for item in value:
            candidate = validator(item)
            if candidate not in normalized:
                normalized.append(candidate)
        return normalized
    if isinstance(value, (dict, tuple, set)) or value is None:
        raise SavedViewsError(f"filters.{key} must be a scalar or a list of scalars")
    return validator(value)


def validate_view_filters(scope: str, raw: Any) -> dict[str, Any]:
    """Validate an allowlisted saved-view filter object.

    Unknown keys, unknown operators/shapes and values outside the field's fixed
    domain are rejected before anything is stored. No SQL is built here.
    """
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise SavedViewsError("filters must be an object")
    if len(raw) > MAX_FILTER_KEYS:
        raise SavedViewsError(f"filters may contain at most {MAX_FILTER_KEYS} keys")
    validators = _filter_validators(scope)
    result: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or key not in validators:
            raise SavedViewsError(f"unknown filter key for scope {scope}")
        result[key] = _validate_filter_value(validators[key], value, key=key)
    start = result.get("start_date")
    end = result.get("end_date")
    if start and end and start > end:
        raise SavedViewsError("start_date must be on or before end_date")
    return result


def validate_columns(scope: str, raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SavedViewsError("columns must be a list")
    if len(raw) > MAX_COLUMNS:
        raise SavedViewsError(f"columns may contain at most {MAX_COLUMNS} entries")
    allowed = SCOPE_COLUMNS[scope]
    result: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise SavedViewsError("columns must contain text identifiers")
        key = item.strip().lower()
        if key not in allowed:
            raise SavedViewsError(f"unknown column for scope {scope}")
        if key not in result:
            result.append(key)
    return result


def validate_sort(scope: str, raw: Any) -> dict[str, str] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise SavedViewsError("sort must be an object")
    extra = set(raw) - {"field", "direction"}
    if extra:
        raise SavedViewsError("sort only accepts field and direction")
    field = raw.get("field")
    direction = raw.get("direction", "desc")
    if not isinstance(field, str) or field.strip().lower() not in SCOPE_SORT_FIELDS[scope]:
        raise SavedViewsError(f"unknown sort field for scope {scope}")
    if direction not in {"asc", "desc"}:
        raise SavedViewsError("sort direction must be asc or desc")
    return {"field": field.strip().lower(), "direction": direction}


def _validate_range(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SavedViewsError("range_days must be an integer")
    if not (1 <= value <= 365):
        raise SavedViewsError("range_days must be between 1 and 365")
    return value


# --------------------------------------------------------------------------- #
#  Segment DSL                                                                #
# --------------------------------------------------------------------------- #

SEGMENT_FIELDS: dict[str, dict[str, Any]] = {
    "plan": {
        "label": "Subscription plan",
        "type": "plan",
        "operators": ("eq", "neq", "in", "not_in"),
    },
    "role": {
        "label": "Account role",
        "type": "enum",
        "values": list(ROLES),
        "operators": ("eq", "neq", "in", "not_in"),
    },
    "signup_month": {
        "label": "Signup month (UTC)",
        "type": "month",
        "operators": ("eq", "neq", "gte", "lte", "in"),
    },
    "verified": {
        "label": "Email verified",
        "type": "boolean",
        "operators": ("eq", "neq"),
    },
    "tenant": {
        "label": "Tenant slug",
        "type": "tenant",
        "operators": ("eq", "neq", "in", "not_in"),
    },
    "feature_used": {
        "label": "Feature or event used",
        "type": "feature",
        "operators": ("eq", "neq", "in", "not_in"),
    },
    "country_bucket": {
        "label": "Country bucket",
        "type": "country",
        "operators": ("eq", "neq", "in", "not_in"),
    },
}

_SEGMENT_VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "plan": _plan_value,
    "role": _enum(ROLES, field="role"),
    "signup_month": _month_value,
    "verified": _bool_value,
    "tenant": _tenant_value,
    "feature_used": _feature_value,
    "country_bucket": _country_value,
}

GROUP_BY_FIELDS = ("plan", "role", "verified")


def validate_segment_definition(raw: Any) -> dict[str, Any]:
    """Normalize and validate the typed segment DSL.

    The result is the canonical object persisted and later re-validated on
    every read/compile, so a manually edited JSONB row cannot inject a field or
    operator that the compiler does not know about.
    """
    if not isinstance(raw, Mapping):
        raise SavedViewsError("definition must be an object")
    extra = set(raw) - {"match", "conditions"}
    if extra:
        raise SavedViewsError("definition only accepts match and conditions")
    match = raw.get("match", "all")
    if match not in {"all", "any"}:
        raise SavedViewsError("match must be all or any")
    conditions = raw.get("conditions", [])
    if not isinstance(conditions, list):
        raise SavedViewsError("conditions must be a list")
    if len(conditions) > MAX_CONDITIONS:
        raise SavedViewsError(f"at most {MAX_CONDITIONS} conditions are allowed")
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for condition in conditions:
        if not isinstance(condition, Mapping):
            raise SavedViewsError("each condition must be an object")
        extra = set(condition) - {"field", "operator", "value"}
        if extra:
            raise SavedViewsError("conditions only accept field, operator and value")
        field = condition.get("field")
        operator = condition.get("operator")
        if not isinstance(field, str) or field not in SEGMENT_FIELDS:
            raise SavedViewsError("unknown segment field")
        if not isinstance(operator, str) or operator not in SEGMENT_FIELDS[field]["operators"]:
            raise SavedViewsError(f"unsupported operator for {field}")
        validator = _SEGMENT_VALIDATORS[field]
        value = condition.get("value")
        if operator in {"in", "not_in"}:
            if not isinstance(value, list):
                raise SavedViewsError(f"{operator} requires a list value")
            if not (1 <= len(value) <= MAX_SEGMENT_VALUES):
                raise SavedViewsError(
                    f"segment lists must contain 1-{MAX_SEGMENT_VALUES} values"
                )
            values: list[Any] = []
            for item in value:
                normalized_item = validator(item)
                if normalized_item not in values:
                    values.append(normalized_item)
            value = values
        else:
            if isinstance(value, list):
                raise SavedViewsError(f"{operator} requires a scalar value")
            value = validator(value)
        marker = (field, operator, repr(value))
        if marker in seen:
            continue
        seen.add(marker)
        normalized.append({"field": field, "operator": operator, "value": value})
    return {"match": match, "conditions": normalized}


def segment_field_catalog() -> dict[str, Any]:
    """Return the safe field/operator catalog for the cohort builder UI."""
    return {
        "schema_version": SCHEMA_VERSION,
        "minimum_cohort": MIN_COHORT_SIZE,
        "max_conditions": MAX_CONDITIONS,
        "max_values": MAX_SEGMENT_VALUES,
        "fields": [
            {
                "field": key,
                "label": spec["label"],
                "type": spec["type"],
                "operators": list(spec["operators"]),
                **({"values": spec["values"]} if "values" in spec else {}),
            }
            for key, spec in SEGMENT_FIELDS.items()
        ],
        "group_by": list(GROUP_BY_FIELDS),
    }


def view_scope_catalog() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "scopes": [
            {
                "scope": scope,
                "filters": sorted(_filter_validators(scope)),
                "columns": sorted(SCOPE_COLUMNS[scope]),
                "sort_fields": sorted(SCOPE_SORT_FIELDS[scope]),
            }
            for scope in VIEW_SCOPES
        ],
    }


# --------------------------------------------------------------------------- #
#  Query compilation                                                          #
# --------------------------------------------------------------------------- #


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    match = _MONTH_RE.fullmatch(month)
    assert match is not None
    year = int(match.group(1))
    month_number = int(match.group(2))
    start = datetime(year, month_number, 1, tzinfo=timezone.utc)
    if month_number == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month_number + 1, 1, tzinfo=timezone.utc)
    return start, end


def _plan_aliases(value: str) -> list[str]:
    """Map a canonical family to every accepted SKU spelling.

    Concrete SKUs (for example ``student``) match themselves only; a family
    label (``pro``) matches every alias that resolves to it.
    """
    if value in PLAN_FAMILIES:
        aliases = {alias for alias, family in PLAN_FAMILY_ALIASES.items() if family == value}
        aliases.add(value)
        return sorted(aliases)
    return [value]


def _tenant_clause(values: Sequence[str]) -> Any:
    tenant_ids = select(models.Tenant.id).where(models.Tenant.slug.in_(list(values)))
    membership = exists(
        select(1)
        .select_from(models.TenantMember)
        .join(models.Tenant, models.Tenant.id == models.TenantMember.tenant_id)
        .where(
            models.TenantMember.user_id == models.User.id,
            models.Tenant.slug.in_(list(values)),
        )
    )
    return or_(models.User.default_tenant_id.in_(tenant_ids), membership)


def _feature_clause(values: Sequence[str]) -> Any:
    feature_expr = models.UsageAnalytics.event_metadata["feature"].as_string()
    return exists(
        select(1)
        .select_from(models.UsageAnalytics)
        .where(
            models.UsageAnalytics.user_id == models.User.id,
            or_(
                models.UsageAnalytics.action.in_(list(values)),
                feature_expr.in_(list(values)),
            ),
        )
    )


def _country_clause(values: Sequence[str]) -> Any:
    codes = [value for value in values if value != COUNTRY_UNKNOWN]
    include_unknown = COUNTRY_UNKNOWN in values
    clauses: list[Any] = []
    country_expr = models.UsageAnalytics.event_metadata["country"].as_string()
    if codes:
        clauses.append(
            exists(
                select(1)
                .select_from(models.UsageAnalytics)
                .where(
                    models.UsageAnalytics.user_id == models.User.id,
                    func.upper(country_expr).in_([code.upper() for code in codes]),
                )
            )
        )
    if include_unknown:
        clauses.append(
            exists(
                select(1)
                .select_from(models.UsageAnalytics)
                .where(
                    models.UsageAnalytics.user_id == models.User.id,
                    country_expr.is_(None),
                )
            )
        )
    return or_(*clauses) if clauses else not_(true())


def _month_clause(operator: str, values: Sequence[str]) -> Any:
    clauses: list[Any] = []
    for month in values:
        start, end = _month_bounds(month)
        if operator in {"eq", "in"}:
            clauses.append(and_(models.User.created_at >= start, models.User.created_at < end))
        elif operator == "gte":
            clauses.append(models.User.created_at >= start)
        elif operator == "lte":
            clauses.append(models.User.created_at < end)
        elif operator == "neq":
            clauses.append(not_(and_(models.User.created_at >= start, models.User.created_at < end)))
    return or_(*clauses) if operator in {"in", "eq"} and len(clauses) > 1 else clauses[0]


def _condition_clause(condition: Mapping[str, Any]) -> Any:
    field = condition["field"]
    operator = condition["operator"]
    value = condition["value"]
    values = value if isinstance(value, list) else [value]

    if field == "plan":
        aliases: list[str] = []
        for item in values:
            for alias in _plan_aliases(item):
                if alias not in aliases:
                    aliases.append(alias)
        clause = models.User.subscription_plan.in_(aliases)
        return clause if operator in {"eq", "in"} else not_(clause)
    if field == "role":
        clause = models.User.role.in_(list(values))
        return clause if operator in {"eq", "in"} else not_(clause)
    if field == "verified":
        clause = models.User.email_verified.is_(bool(value))
        return clause if operator == "eq" else not_(clause)
    if field == "signup_month":
        return _month_clause(operator, list(values))
    if field == "tenant":
        clause = _tenant_clause(list(values))
        return clause if operator in {"eq", "in"} else not_(clause)
    if field == "feature_used":
        clause = _feature_clause(list(values))
        return clause if operator in {"eq", "in"} else not_(clause)
    if field == "country_bucket":
        clause = _country_clause(list(values))
        return clause if operator in {"eq", "in"} else not_(clause)
    raise SavedViewsError("unknown segment field")


def segment_where(definition: Mapping[str, Any]) -> Any:
    conditions = definition.get("conditions", [])
    clauses = [_condition_clause(condition) for condition in conditions]
    if not clauses:
        return true()
    return and_(*clauses) if definition.get("match", "all") == "all" else or_(*clauses)


# --------------------------------------------------------------------------- #
#  Persistence helpers                                                        #
# --------------------------------------------------------------------------- #


def _paginate(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(int(limit), MAX_PAGE_SIZE)), max(0, int(offset))


def _visible_clause(actor: AdminActor, visibility: str) -> Any:
    owned = models.AdminSavedView.owner_user_id == actor.user_id
    shared = models.AdminSavedView.shared.is_(True)
    if visibility == "owned":
        return owned
    if visibility == "shared":
        return shared
    return or_(owned, shared)


def view_payload(row: models.AdminSavedView, actor: AdminActor) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "scope": row.scope,
        "filters": row.filters or {},
        "columns": row.columns or [],
        "sort": row.sort,
        "range_days": row.range_days,
        "shared": bool(row.shared),
        "is_default": bool(row.is_default),
        "is_owner": str(row.owner_user_id) == actor.user_id,
        "version": int(row.version),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def segment_payload(row: models.AdminSegment, actor: AdminActor) -> dict[str, Any]:
    definition = row.definition if isinstance(row.definition, dict) else {}
    conditions = definition.get("conditions")
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description,
        "definition": definition,
        "condition_count": len(conditions) if isinstance(conditions, list) else 0,
        "match": definition.get("match", "all"),
        "shared": bool(row.shared),
        "is_owner": str(row.owner_user_id) == actor.user_id,
        "version": int(row.version),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _view_snapshot(row: models.AdminSavedView) -> dict[str, Any]:
    """Audit-safe metadata. Names and filter values never enter the audit log."""
    filters = row.filters if isinstance(row.filters, dict) else {}
    columns = row.columns if isinstance(row.columns, list) else []
    return {
        "scope": row.scope,
        "shared": bool(row.shared),
        "is_default": bool(row.is_default),
        "range_days": row.range_days,
        "filter_count": len(filters),
        "column_count": len(columns),
        "sort_field": (row.sort or {}).get("field") if isinstance(row.sort, dict) else None,
        "version": int(row.version),
    }


def _segment_snapshot(row: models.AdminSegment) -> dict[str, Any]:
    definition = row.definition if isinstance(row.definition, dict) else {}
    conditions = definition.get("conditions")
    return {
        "shared": bool(row.shared),
        "match": definition.get("match", "all"),
        "condition_count": len(conditions) if isinstance(conditions, list) else 0,
        "version": int(row.version),
    }


async def _is_duplicate_name(
    db: AsyncSession,
    *,
    model: Any,
    owner_user_id: str,
    name_key: str,
    scope: str | None = None,
    exclude_id: str | None = None,
) -> bool:
    stmt = select(model.id).where(
        model.owner_user_id == owner_user_id,
        model.name_key == name_key,
        model.deleted_at.is_(None),
    )
    if scope is not None:
        stmt = stmt.where(model.scope == scope)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    return (await db.execute(stmt.limit(1))).first() is not None


async def list_saved_views(
    db: AsyncSession,
    *,
    actor: AdminActor,
    scope: str | None = None,
    visibility: str = "all",
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    if scope is not None and scope not in VIEW_SCOPES:
        raise SavedViewsError("unknown saved-view scope")
    if visibility not in {"all", "owned", "shared"}:
        raise SavedViewsError("visibility must be all, owned or shared")
    bounded_limit, bounded_offset = _paginate(limit, offset)
    base = select(models.AdminSavedView).where(
        models.AdminSavedView.deleted_at.is_(None),
        _visible_clause(actor, visibility),
    )
    if scope is not None:
        base = base.where(models.AdminSavedView.scope == scope)
    total = await db.scalar(
        select(func.count()).select_from(base.order_by(None).subquery())
    )
    rows = (
        await db.execute(
            base.order_by(
                models.AdminSavedView.is_default.desc(),
                models.AdminSavedView.updated_at.desc(),
                models.AdminSavedView.id.desc(),
            )
            .limit(bounded_limit)
            .offset(bounded_offset)
        )
    ).scalars().all()
    return {
        "items": [view_payload(row, actor) for row in rows],
        "total": int(total or 0),
        "limit": bounded_limit,
        "offset": bounded_offset,
        "scopes": list(VIEW_SCOPES),
    }


async def get_saved_view(db: AsyncSession, *, actor: AdminActor, view_id: str) -> dict[str, Any]:
    row = (
        await db.execute(
            select(models.AdminSavedView).where(
                models.AdminSavedView.id == view_id,
                models.AdminSavedView.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise KeyError("Saved view not found")
    if str(row.owner_user_id) != actor.user_id and not row.shared:
        raise KeyError("Saved view not found")
    return view_payload(row, actor)


async def _clear_default_views(
    db: AsyncSession, *, owner_user_id: str, scope: str, exclude_id: str | None = None
) -> None:
    stmt = select(models.AdminSavedView).where(
        models.AdminSavedView.owner_user_id == owner_user_id,
        models.AdminSavedView.scope == scope,
        models.AdminSavedView.is_default.is_(True),
        models.AdminSavedView.deleted_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(models.AdminSavedView.id != exclude_id)
    cleared = (await db.execute(stmt)).scalars().all()
    for row in cleared:
        row.is_default = False
    if cleared:
        # Flush the clears before the new default is written so the partial
        # unique index (owner, scope) never sees two default rows at once.
        await db.flush()


async def create_saved_view(
    db: AsyncSession,
    *,
    actor: AdminActor,
    name: str,
    scope: str,
    filters: Any = None,
    columns: Any = None,
    sort: Any = None,
    range_days: Any = None,
    shared: bool = False,
    is_default: bool = False,
    request: Any = None,
) -> dict[str, Any]:
    if scope not in VIEW_SCOPES:
        raise SavedViewsError("unknown saved-view scope")
    clean_name, name_key = _clean_name(name)
    clean_filters = validate_view_filters(scope, filters)
    clean_columns = validate_columns(scope, columns)
    clean_sort = validate_sort(scope, sort)
    clean_range = _validate_range(range_days)
    if not isinstance(shared, bool) or not isinstance(is_default, bool):
        raise SavedViewsError("shared and is_default must be booleans")
    if await _is_duplicate_name(
        db,
        model=models.AdminSavedView,
        owner_user_id=actor.user_id,
        scope=scope,
        name_key=name_key,
    ):
        raise DuplicateNameError("A saved view with this name already exists in this scope")
    if is_default:
        await _clear_default_views(db, owner_user_id=actor.user_id, scope=scope)
    row = models.AdminSavedView(
        owner_user_id=actor.user_id,
        name=clean_name,
        name_key=name_key,
        scope=scope,
        filters=clean_filters,
        columns=clean_columns,
        sort=clean_sort,
        range_days=clean_range,
        shared=shared,
        is_default=is_default,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateNameError("A saved view with this name already exists in this scope") from exc
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.saved_view.create",
        target_type="admin_saved_view",
        target_id=str(row.id),
        request=request,
        after=_view_snapshot(row),
        metadata={"shared": bool(shared)},
    )
    await db.commit()
    await db.refresh(row)
    return view_payload(row, actor)


async def _load_for_write(
    db: AsyncSession, *, model: Any, row_id: str, actor: AdminActor, label: str
) -> Any:
    row = (
        await db.execute(
            select(model)
            .where(model.id == row_id, model.deleted_at.is_(None))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise KeyError(f"{label} not found")
    if str(row.owner_user_id) != actor.user_id:
        is_shared = bool(row.shared)
        await db.rollback()
        if is_shared:
            raise ViewPermissionError(f"Only the owner may change this {label.lower()}")
        raise KeyError(f"{label} not found")
    return row


async def update_saved_view(
    db: AsyncSession,
    *,
    actor: AdminActor,
    view_id: str,
    expected_version: int,
    changes: Mapping[str, Any],
    request: Any = None,
) -> dict[str, Any]:
    row = await _load_for_write(
        db, model=models.AdminSavedView, row_id=view_id, actor=actor, label="Saved view"
    )
    if int(expected_version) != int(row.version):
        await db.rollback()
        raise VersionConflictError("Saved view changed elsewhere; reload before retrying")
    before = _view_snapshot(row)
    update_fields = set(changes) - {"expected_version", "reason"}
    if not update_fields:
        raise SavedViewsError("No saved-view changes were supplied")
    new_scope = row.scope
    if "scope" in changes:
        new_scope = changes["scope"]
        if new_scope not in VIEW_SCOPES:
            raise SavedViewsError("unknown saved-view scope")
    if new_scope != row.scope:
        # Scope changes must be revalidated against the new allowlist instead of
        # carrying filters/columns that may not exist there.
        filters = changes.get("filters", {})
        columns = changes.get("columns", [])
        sort = changes.get("sort")
    else:
        filters = changes.get("filters", row.filters)
        columns = changes.get("columns", row.columns)
        sort = changes.get("sort", row.sort)
    if "name" in changes:
        clean_name, name_key = _clean_name(changes["name"])
        if name_key != row.name_key and await _is_duplicate_name(
            db,
            model=models.AdminSavedView,
            owner_user_id=actor.user_id,
            scope=new_scope,
            name_key=name_key,
            exclude_id=view_id,
        ):
            raise DuplicateNameError("A saved view with this name already exists in this scope")
        row.name = clean_name
        row.name_key = name_key
    row.scope = new_scope
    row.filters = validate_view_filters(new_scope, filters)
    row.columns = validate_columns(new_scope, columns)
    row.sort = validate_sort(new_scope, sort)
    if "range_days" in changes:
        row.range_days = _validate_range(changes["range_days"])
    shared_changed = False
    if "shared" in changes:
        if not isinstance(changes["shared"], bool):
            raise SavedViewsError("shared must be a boolean")
        shared_changed = bool(changes["shared"]) != bool(row.shared)
        row.shared = bool(changes["shared"])
    default_changed = False
    if "is_default" in changes:
        if not isinstance(changes["is_default"], bool):
            raise SavedViewsError("is_default must be a boolean")
        default_changed = bool(changes["is_default"]) != bool(row.is_default)
        if changes["is_default"]:
            await _clear_default_views(
                db,
                owner_user_id=actor.user_id,
                scope=row.scope,
                exclude_id=str(row.id),
            )
        row.is_default = bool(changes["is_default"])
    row.version = int(row.version) + 1
    row.updated_at = datetime.now(timezone.utc)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateNameError("A saved view with this name already exists in this scope") from exc
    action = "admin.saved_view.update"
    if shared_changed:
        action = "admin.saved_view.share" if row.shared else "admin.saved_view.unshare"
    elif default_changed:
        action = "admin.saved_view.default"
    await record_admin_audit(
        db,
        actor=actor,
        action=action,
        target_type="admin_saved_view",
        target_id=str(row.id),
        reason=changes.get("reason"),
        request=request,
        before=before,
        after=_view_snapshot(row),
    )
    await db.commit()
    await db.refresh(row)
    return view_payload(row, actor)


async def delete_saved_view(
    db: AsyncSession,
    *,
    actor: AdminActor,
    view_id: str,
    expected_version: int,
    reason: str,
    request: Any = None,
) -> dict[str, Any]:
    if not isinstance(reason, str) or len(" ".join(reason.split())) < 3:
        raise SavedViewsError("A deletion reason of at least 3 characters is required")
    row = await _load_for_write(
        db, model=models.AdminSavedView, row_id=view_id, actor=actor, label="Saved view"
    )
    if int(expected_version) != int(row.version):
        await db.rollback()
        raise VersionConflictError("Saved view changed elsewhere; reload before retrying")
    before = _view_snapshot(row)
    row.deleted_at = datetime.now(timezone.utc)
    row.is_default = False
    row.version = int(row.version) + 1
    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.saved_view.delete",
        target_type="admin_saved_view",
        target_id=str(row.id),
        reason=reason,
        request=request,
        before=before,
        after={"deleted": True, "version": int(row.version)},
    )
    await db.commit()
    return {"id": str(row.id), "deleted": True, "version": int(row.version)}


# --------------------------------------------------------------------------- #
#  Segments                                                                   #
# --------------------------------------------------------------------------- #


async def list_segments(
    db: AsyncSession,
    *,
    actor: AdminActor,
    visibility: str = "all",
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    if visibility not in {"all", "owned", "shared"}:
        raise SavedViewsError("visibility must be all, owned or shared")
    bounded_limit, bounded_offset = _paginate(limit, offset)
    owned = models.AdminSegment.owner_user_id == actor.user_id
    shared = models.AdminSegment.shared.is_(True)
    if visibility == "owned":
        visible = owned
    elif visibility == "shared":
        visible = shared
    else:
        visible = or_(owned, shared)
    base = select(models.AdminSegment).where(
        models.AdminSegment.deleted_at.is_(None), visible
    )
    total = await db.scalar(select(func.count()).select_from(base.order_by(None).subquery()))
    rows = (
        await db.execute(
            base.order_by(
                models.AdminSegment.updated_at.desc(),
                models.AdminSegment.id.desc(),
            )
            .limit(bounded_limit)
            .offset(bounded_offset)
        )
    ).scalars().all()
    return {
        "items": [segment_payload(row, actor) for row in rows],
        "total": int(total or 0),
        "limit": bounded_limit,
        "offset": bounded_offset,
    }


async def get_segment(db: AsyncSession, *, actor: AdminActor, segment_id: str) -> dict[str, Any]:
    row = (
        await db.execute(
            select(models.AdminSegment).where(
                models.AdminSegment.id == segment_id,
                models.AdminSegment.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise KeyError("Segment not found")
    if str(row.owner_user_id) != actor.user_id and not row.shared:
        raise KeyError("Segment not found")
    return segment_payload(row, actor)


async def create_segment(
    db: AsyncSession,
    *,
    actor: AdminActor,
    name: str,
    description: Any = None,
    definition: Any = None,
    shared: bool = False,
    request: Any = None,
) -> dict[str, Any]:
    clean_name, name_key = _clean_name(name)
    clean_description = _clean_description(description)
    clean_definition = validate_segment_definition(definition)
    if not isinstance(shared, bool):
        raise SavedViewsError("shared must be a boolean")
    if await _is_duplicate_name(
        db,
        model=models.AdminSegment,
        owner_user_id=actor.user_id,
        name_key=name_key,
    ):
        raise DuplicateNameError("A segment with this name already exists")
    row = models.AdminSegment(
        owner_user_id=actor.user_id,
        name=clean_name,
        name_key=name_key,
        description=clean_description,
        definition=clean_definition,
        shared=shared,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateNameError("A segment with this name already exists") from exc
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.segment.create",
        target_type="admin_segment",
        target_id=str(row.id),
        request=request,
        after=_segment_snapshot(row),
    )
    await db.commit()
    await db.refresh(row)
    return segment_payload(row, actor)


async def update_segment(
    db: AsyncSession,
    *,
    actor: AdminActor,
    segment_id: str,
    expected_version: int,
    changes: Mapping[str, Any],
    request: Any = None,
) -> dict[str, Any]:
    row = await _load_for_write(
        db, model=models.AdminSegment, row_id=segment_id, actor=actor, label="Segment"
    )
    if int(expected_version) != int(row.version):
        await db.rollback()
        raise VersionConflictError("Segment changed elsewhere; reload before retrying")
    update_fields = set(changes) - {"expected_version", "reason"}
    if not update_fields:
        raise SavedViewsError("No segment changes were supplied")
    before = _segment_snapshot(row)
    if "name" in changes:
        clean_name, name_key = _clean_name(changes["name"])
        if name_key != row.name_key and await _is_duplicate_name(
            db,
            model=models.AdminSegment,
            owner_user_id=actor.user_id,
            name_key=name_key,
            exclude_id=segment_id,
        ):
            raise DuplicateNameError("A segment with this name already exists")
        row.name = clean_name
        row.name_key = name_key
    if "description" in changes:
        row.description = _clean_description(changes["description"])
    if "definition" in changes:
        row.definition = validate_segment_definition(changes["definition"])
    shared_changed = False
    if "shared" in changes:
        if not isinstance(changes["shared"], bool):
            raise SavedViewsError("shared must be a boolean")
        shared_changed = bool(changes["shared"]) != bool(row.shared)
        row.shared = bool(changes["shared"])
    row.version = int(row.version) + 1
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    action = "admin.segment.update"
    if shared_changed:
        action = "admin.segment.share" if row.shared else "admin.segment.unshare"
    await record_admin_audit(
        db,
        actor=actor,
        action=action,
        target_type="admin_segment",
        target_id=str(row.id),
        reason=changes.get("reason"),
        request=request,
        before=before,
        after=_segment_snapshot(row),
    )
    await db.commit()
    await db.refresh(row)
    return segment_payload(row, actor)


async def delete_segment(
    db: AsyncSession,
    *,
    actor: AdminActor,
    segment_id: str,
    expected_version: int,
    reason: str,
    request: Any = None,
) -> dict[str, Any]:
    if not isinstance(reason, str) or len(" ".join(reason.split())) < 3:
        raise SavedViewsError("A deletion reason of at least 3 characters is required")
    row = await _load_for_write(
        db, model=models.AdminSegment, row_id=segment_id, actor=actor, label="Segment"
    )
    if int(expected_version) != int(row.version):
        await db.rollback()
        raise VersionConflictError("Segment changed elsewhere; reload before retrying")
    before = _segment_snapshot(row)
    row.deleted_at = datetime.now(timezone.utc)
    row.version = int(row.version) + 1
    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.segment.delete",
        target_type="admin_segment",
        target_id=str(row.id),
        reason=reason,
        request=request,
        before=before,
        after={"deleted": True, "version": int(row.version)},
    )
    await db.commit()
    return {"id": str(row.id), "deleted": True, "version": int(row.version)}


# --------------------------------------------------------------------------- #
#  Preview                                                                    #
# --------------------------------------------------------------------------- #


def _group_expression(field: str) -> Any:
    if field == "plan":
        return models.User.subscription_plan
    if field == "role":
        return models.User.role
    if field == "verified":
        return models.User.email_verified
    raise SavedViewsError("unknown group_by field")


async def preview_segment(
    db: AsyncSession,
    *,
    definition: Any,
    group_by: str | None = None,
) -> dict[str, Any]:
    """Return an aggregate count (never user rows) with five-user suppression."""
    clean_definition = validate_segment_definition(definition)
    if group_by is not None and group_by not in GROUP_BY_FIELDS:
        raise SavedViewsError("unknown group_by field")
    where = segment_where(clean_definition)
    total = int(
        (await db.scalar(select(func.count(models.User.id)).where(where))) or 0
    )
    response: dict[str, Any] = {
        "count": None,
        "suppressed": True,
        "minimum_cohort": MIN_COHORT_SIZE,
        "match": clean_definition["match"],
        "condition_count": len(clean_definition["conditions"]),
        "group_by": group_by,
        "groups": [],
        "suppressed_groups": 0,
        "data_source": "users and first-party event aggregates",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if total < MIN_COHORT_SIZE:
        return response

    response["count"] = total
    response["suppressed"] = False
    if group_by is None:
        return response

    expression = _group_expression(group_by)
    rows = (
        await db.execute(
            select(expression, func.count(models.User.id))
            .where(where)
            .group_by(expression)
        )
    ).all()
    merged: dict[str, int] = {}
    for raw_value, count in rows:
        if group_by == "verified":
            label = "verified" if bool(raw_value) else "unverified"
        elif group_by == "plan":
            value = str(raw_value or "free").strip().lower() or "free"
            label = PLAN_FAMILY_ALIASES.get(value, value)
        else:
            label = str(raw_value or "user").strip().lower() or "user"
        merged[label] = merged.get(label, 0) + int(count)
    visible = [
        {"value": label, "count": count}
        for label, count in sorted(merged.items(), key=lambda item: (-item[1], item[0]))
        if count >= MIN_COHORT_SIZE
    ]
    response["groups"] = visible
    response["suppressed_groups"] = sum(
        1 for count in merged.values() if count < MIN_COHORT_SIZE
    )
    return response


async def preview_saved_segment(
    db: AsyncSession,
    *,
    actor: AdminActor,
    segment_id: str,
    group_by: str | None = None,
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(models.AdminSegment).where(
                models.AdminSegment.id == segment_id,
                models.AdminSegment.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise KeyError("Segment not found")
    if str(row.owner_user_id) != actor.user_id and not row.shared:
        raise KeyError("Segment not found")
    result = await preview_segment(db, definition=row.definition, group_by=group_by)
    result["segment_id"] = str(row.id)
    result["segment_version"] = int(row.version)
    return result
