"""Admin route-transition (Sankey) analysis before upgrade and churn (#2076).

Data boundary
-------------
Every value in this report is first-party and aggregate.  Route labels are
canonicalised server-side from the existing ``usage_analytics`` JSONB column:
query strings and fragments are removed, opaque identifiers are replaced with
stable placeholders, unknown paths collapse to ``/other``, and no document
content, share token, email, user agent, IP address or per-user row ever leaves
this module.

Data source
-----------
The report reconstructs a visitor's last few sanitised routes from
``usage_analytics`` ``page_view`` rows, then joins them to the append-only
``subscription_history`` ledger:

* **upgrade** - the first paid activation or plan upgrade for a subscription
  inside the selected period;
* **churn** - the first cancellation or expiry for a subscription inside the
  selected period.

An outcome with no first-party route rows is reported as ``Path data missing``.
It is never given an inferred route and never dropped from the outcome total.

Suppression and reconciliation
------------------------------
A section with fewer than five distinct users is fully suppressed.  Individual
edges, nodes and paths below five distinct users, or below the requested edge
threshold, are omitted.  Node totals are computed only from visible edges, so
the displayed Sankey always reconciles: every visible edge contributes exactly
one unit to a visible source node and one unit to a visible target node.
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES, resolve_plan_family
from ..database import models
from .subscription_history_service import movement_direction

UsageAnalytics = models.UsageAnalytics
SubscriptionHistory = models.SubscriptionHistory
User = models.User

MIN_GROUP_SIZE = 5
MAX_RANGE_DAYS = 366
MAX_OUTCOME_ROWS = 100_000
MAX_PAGEVIEW_ROWS = 200_000
MAX_PATH_ROUTE_STEPS = 4
MAX_TOP_PATHS = 10
PATH_LOOKBACK_DAYS = 30
NEW_ACCOUNT_DAYS = 30
MAX_PLAN_FILTERS = 6

UPGRADE = "upgrade"
CHURN = "churn"
OUTCOME_LABELS = {UPGRADE: "Upgrade", CHURN: "Churn"}
COHORTS = ("all", "new", "established")

ROUTE_NODE_PREFIX = "route:"
OUTCOME_NODE_PREFIX = "outcome:"
MISSING_NODE_PREFIX = "missing:"
MISSING_LABEL = "Path data missing"
OTHER_ROUTE = "/other"
OTHER_LABEL = "Other route"

PAID_STATUSES = frozenset({"active", "cancel_scheduled", "past_due", "on_hold", "paused"})
UPGRADE_EVENTS = frozenset({"subscription_created", "activated", "plan_changed"})
CHURN_EVENTS = frozenset({"cancelled", "expired"})

STATIC_ROUTES = frozenset(
    {
        "/",
        "/accessibility",
        "/admin",
        "/admin/tenant",
        "/billing",
        "/byok",
        "/dashboard",
        "/developer",
        "/faq",
        "/forgot-password",
        "/login",
        "/platform",
        "/pricing",
        "/privacy",
        "/reset-password",
        "/resources",
        "/settings",
        "/signup",
        "/templates",
        "/tenant-invite",
        "/terms",
        "/tracker",
        "/try",
        "/two-factor",
        "/updates",
        "/verify-email",
        "/workspace",
        "/workspace/builder/new",
        "/workspace/cover-letters",
        "/workspace/history",
        "/workspace/merge",
        "/workspace/new",
        "/workspaces",
    }
)

# Order matters: the more specific workspace routes must be checked before the
# generic ``/workspace/:resumeId`` route.
ROUTE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^/r/[^/]+$"), "/r/:token"),
    (re.compile(r"^/u/[^/]+$"), "/u/:username"),
    (re.compile(r"^/share/[^/]+$"), "/share/:token"),
    (re.compile(r"^/portfolio/[^/]+$"), "/portfolio/:username"),
    (re.compile(r"^/tenant-invite/[^/]+$"), "/tenant-invite/:token"),
    (re.compile(r"^/workspace/builder/[^/]+$"), "/workspace/builder/:resumeId"),
    (re.compile(r"^/workspace/variant/[^/]+$"), "/workspace/variant/:resumeId"),
    (re.compile(r"^/workspace/[^/]+/edit$"), "/workspace/:resumeId/edit"),
    (re.compile(r"^/workspace/[^/]+/optimize$"), "/workspace/:resumeId/optimize"),
    (re.compile(r"^/workspace/[^/]+/cover-letter$"), "/workspace/:resumeId/cover-letter"),
    (re.compile(r"^/workspace/[^/]+/career$"), "/workspace/:resumeId/career"),
    (re.compile(r"^/workspace/[^/]+/batch-tailor$"), "/workspace/:resumeId/batch-tailor"),
    (re.compile(r"^/workspaces/[^/]+/recruiter$"), "/workspaces/:workspaceId/recruiter"),
    (re.compile(r"^/workspaces/[^/]+$"), "/workspaces/:workspaceId"),
    (re.compile(r"^/workspace/[^/]+$"), "/workspace/:resumeId"),
)
CANONICAL_DYNAMIC_ROUTES = frozenset(label for _pattern, label in ROUTE_PATTERNS)

# Conservative grammar: no whitespace, percent-escapes, backslashes, or control
# characters. A rejected value is bucketed, never echoed.
_ROUTE_PATTERN = re.compile(r"^[A-Za-z0-9_.:/~-]{1,240}$")
_PLAN_FAMILIES = tuple(dict.fromkeys(PLAN_FAMILY_ALIASES.values()))

CSV_COLUMNS = (
    "section",
    "outcome",
    "source",
    "target",
    "label",
    "count",
    "users",
    "suppressed",
    "note",
)


def sanitize_path_route(value: Any) -> str:
    """Return a canonical route label, never a raw URL or token.

    Query strings and fragments are discarded before validation.  Dynamic
    segments are replaced with placeholders, and any value outside the bounded
    grammar or the canonical route vocabulary becomes ``/other``.
    """

    if not isinstance(value, str):
        return OTHER_ROUTE
    route = value.strip().split("?", 1)[0].split("#", 1)[0]
    if not route or len(route) > 240 or _ROUTE_PATTERN.fullmatch(route) is None:
        return OTHER_ROUTE
    if not route.startswith("/"):
        route = f"/{route}"
    if "//" in route:
        return OTHER_ROUTE
    route = route.rstrip("/") or "/"
    if route in STATIC_ROUTES or route in CANONICAL_DYNAMIC_ROUTES:
        return route
    for pattern, label in ROUTE_PATTERNS:
        if pattern.fullmatch(route):
            return label
    return OTHER_ROUTE


def _route_label(route: str) -> str:
    if route == OTHER_ROUTE:
        return OTHER_LABEL
    return route


def _normalize_plan_filter(values: Sequence[str] | None) -> list[str] | None:
    if not values:
        return None
    normalized: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            raise ValueError("plan filters must be strings")
        for part in raw.split(","):
            candidate = part.strip().lower()
            if not candidate:
                continue
            family = PLAN_FAMILY_ALIASES.get(candidate)
            if family is None and candidate in _PLAN_FAMILIES:
                family = candidate
            if family is None:
                raise ValueError(f"unknown plan filter: {candidate[:32]}")
            if family not in normalized:
                normalized.append(family)
    if len(normalized) > MAX_PLAN_FILTERS:
        raise ValueError(f"at most {MAX_PLAN_FILTERS} plan filters are allowed")
    return normalized or None


def _resolve_period(
    *,
    days: int,
    start_date: date | None,
    end_date: date | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    current = now or datetime.now(timezone.utc)
    if end_date is not None:
        end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    else:
        end_at = current
    if start_date is not None:
        start_at = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    else:
        start_at = end_at - timedelta(days=max(1, min(int(days), MAX_RANGE_DAYS)))
    if start_at >= end_at:
        raise ValueError("start_date must be before end_date")
    if end_at - start_at > timedelta(days=MAX_RANGE_DAYS):
        raise ValueError("date range cannot exceed 366 days")
    return start_at, end_at


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _cohort(created_at: datetime | None, occurred_at: datetime) -> str:
    if created_at is None or created_at > occurred_at:
        return "unknown"
    return "new" if occurred_at - created_at <= timedelta(days=NEW_ACCOUNT_DAYS) else "established"


@dataclass(frozen=True)
class PathOutcome:
    key: str
    user_id: str
    occurred_at: datetime
    plan: str
    plan_family: str
    cohort: str


@dataclass
class _Agg:
    count: int = 0
    users: set[str] = field(default_factory=set)

    def add(self, user_id: str) -> None:
        self.count += 1
        self.users.add(user_id)


@dataclass
class _NodeAgg:
    count: int = 0
    users: set[str] = field(default_factory=set)

    def add(self, user_id: str) -> None:
        self.count += 1
        self.users.add(user_id)


@dataclass
class _RawSection:
    key: str
    outcomes: list[PathOutcome]
    paths: dict[tuple[str, ...], _Agg]
    nodes: dict[str, _NodeAgg]
    edges: dict[tuple[str, str], _Agg]
    missing_outcomes: int
    missing_users: set[str]


def _select_routes(
    events: Sequence[tuple[datetime, Any]],
    occurred_at: datetime,
) -> tuple[str, ...]:
    """Pick the last few canonical routes before one outcome.

    ``events`` are ordered oldest-first.  Consecutive duplicates are collapsed
    because reloading the same page is not a new transition.  Missing route
    metadata is skipped, never replaced with a guessed route.
    """

    if not events:
        return ()
    cutoff = occurred_at - timedelta(days=PATH_LOOKBACK_DAYS)
    selected: list[str] = []
    for created_at, raw_route in reversed(events):
        if created_at >= occurred_at:
            continue
        if created_at < cutoff:
            break
        if not isinstance(raw_route, str) or not raw_route.strip():
            continue
        route = sanitize_path_route(raw_route)
        if selected and selected[-1] == route:
            continue
        selected.append(route)
        if len(selected) >= MAX_PATH_ROUTE_STEPS:
            break
    selected.reverse()
    return tuple(selected)


def _build_raw_section(
    key: str,
    outcomes: Sequence[PathOutcome],
    routes_by_user: Mapping[str, Sequence[tuple[datetime, Any]]],
) -> _RawSection:
    paths: dict[tuple[str, ...], _Agg] = defaultdict(_Agg)
    nodes: dict[str, _NodeAgg] = defaultdict(_NodeAgg)
    edges: dict[tuple[str, str], _Agg] = defaultdict(_Agg)
    missing_outcomes = 0
    missing_users: set[str] = set()

    for outcome in outcomes:
        routes = _select_routes(routes_by_user.get(outcome.user_id, ()), outcome.occurred_at)
        if routes:
            route_nodes = tuple(f"{ROUTE_NODE_PREFIX}{route}" for route in routes)
        else:
            route_nodes = (f"{MISSING_NODE_PREFIX}{key}",)
            missing_outcomes += 1
            missing_users.add(outcome.user_id)
        sequence = (*route_nodes, f"{OUTCOME_NODE_PREFIX}{key}")
        for node_id in sequence:
            nodes[node_id].add(outcome.user_id)
        for source, target in zip(sequence, sequence[1:]):
            edges[(source, target)].add(outcome.user_id)
        paths[routes].add(outcome.user_id)

    return _RawSection(
        key=key,
        outcomes=list(outcomes),
        paths=dict(paths),
        nodes=dict(nodes),
        edges=dict(edges),
        missing_outcomes=missing_outcomes,
        missing_users=missing_users,
    )


def _node_kind(node_id: str) -> str:
    if node_id.startswith(OUTCOME_NODE_PREFIX):
        return "outcome"
    if node_id.startswith(MISSING_NODE_PREFIX):
        return "missing"
    return "route"


def _node_label(node_id: str) -> str:
    kind = _node_kind(node_id)
    if kind == "outcome":
        return OUTCOME_LABELS.get(node_id.split(":", 1)[1], "Outcome")
    if kind == "missing":
        return MISSING_LABEL
    return _route_label(node_id[len(ROUTE_NODE_PREFIX) :])


def _path_label(routes: Sequence[str], outcome_key: str) -> str:
    if not routes:
        return f"{MISSING_LABEL} → {OUTCOME_LABELS[outcome_key]}"
    return " → ".join([*(_route_label(route) for route in routes), OUTCOME_LABELS[outcome_key]])


def _check(key: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"key": key, "ok": bool(ok), "detail": detail}


def _empty_section(key: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": OUTCOME_LABELS[key],
        "status": "empty",
        "total_outcomes": 0,
        "missing_path_outcomes": 0,
        "route_path_outcomes": 0,
        "route_coverage_pct": None,
        "missing_path_suppressed": False,
        "nodes": [],
        "edges": [],
        "top_paths": [],
        "suppressed_edges": 0,
        "thresholded_edges": 0,
        "suppressed_paths": 0,
        "visible_paths": 0,
        "top_paths_truncated": False,
        "raw": None,
        "reconciliation": {
            "reconciled": True,
            "checks": [_check("no_outcomes", True, "No outcome rows in this section for the selected period.")],
        },
        "notes": [],
    }


def _suppressed_section(key: str) -> dict[str, Any]:
    section = _empty_section(key)
    section.update(
        {
            "status": "suppressed",
            "total_outcomes": None,
            "missing_path_outcomes": None,
            "route_path_outcomes": None,
            "missing_path_suppressed": True,
            "suppressed_edges": 0,
            "thresholded_edges": 0,
            "suppressed_paths": 0,
            "visible_paths": 0,
            "top_paths_truncated": False,
            "reconciliation": {
                "reconciled": True,
                "checks": [
                    _check(
                        "five_user_floor",
                        True,
                        f"Hidden: fewer than {MIN_GROUP_SIZE} distinct users in this section.",
                    )
                ],
            },
            "notes": [f"Hidden because the section has fewer than {MIN_GROUP_SIZE} distinct users."],
        }
    )
    return section


def _finalize_section(raw: _RawSection, *, min_edge_count: int) -> dict[str, Any]:
    key = raw.key
    total_outcomes = len(raw.outcomes)
    if 0 < total_outcomes < MIN_GROUP_SIZE:
        return _suppressed_section(key)
    if total_outcomes == 0:
        return _empty_section(key)

    visible_edge_keys: list[tuple[str, str]] = []
    suppressed_edges = 0
    thresholded_edges = 0
    for edge_key, aggregate in raw.edges.items():
        if len(aggregate.users) < MIN_GROUP_SIZE:
            suppressed_edges += 1
        elif aggregate.count < min_edge_count:
            thresholded_edges += 1
        else:
            visible_edge_keys.append(edge_key)

    node_incoming: dict[str, int] = defaultdict(int)
    node_outgoing: dict[str, int] = defaultdict(int)
    node_users: dict[str, set[str]] = defaultdict(set)
    for source, target in visible_edge_keys:
        aggregate = raw.edges[(source, target)]
        node_outgoing[source] += aggregate.count
        node_incoming[target] += aggregate.count
        node_users[source].update(aggregate.users)
        node_users[target].update(aggregate.users)

    nodes: list[dict[str, Any]] = []
    for node_id in sorted(node_users):
        kind = _node_kind(node_id)
        count = node_outgoing[node_id] if kind != "outcome" else node_incoming[node_id]
        node: dict[str, Any] = {
            "id": node_id,
            "label": _node_label(node_id),
            "kind": kind,
            "count": count,
            "users": len(node_users[node_id]),
            "incoming": node_incoming[node_id],
            "outgoing": node_outgoing[node_id],
        }
        if kind == "route":
            route = node_id[len(ROUTE_NODE_PREFIX) :]
            node["route"] = route
            node["filter"] = {"route": route}
        elif kind == "outcome":
            node["outcome"] = key
            node["filter"] = {"outcome": key}
        else:
            node["missing"] = True
            node["filter"] = {"missing": True, "outcome": key}
        nodes.append(node)

    edges: list[dict[str, Any]] = []
    for source, target in sorted(visible_edge_keys):
        aggregate = raw.edges[(source, target)]
        edges.append(
            {
                "source": source,
                "target": target,
                "source_label": _node_label(source),
                "target_label": _node_label(target),
                "label": f"{_node_label(source)} → {_node_label(target)}",
                "count": aggregate.count,
                "users": len(aggregate.users),
            }
        )
    edges.sort(key=lambda row: (-row["count"], -row["users"], row["label"]))

    visible_paths: list[dict[str, Any]] = []
    suppressed_paths = 0
    for routes, aggregate in raw.paths.items():
        if len(aggregate.users) < MIN_GROUP_SIZE or aggregate.count < min_edge_count:
            suppressed_paths += 1
            continue
        visible_paths.append(
            {
                "path": list(routes),
                "node_ids": [
                    *(
                        [f"{MISSING_NODE_PREFIX}{key}"]
                        if not routes
                        else [f"{ROUTE_NODE_PREFIX}{route}" for route in routes]
                    ),
                    f"{OUTCOME_NODE_PREFIX}{key}",
                ],
                "label": _path_label(routes, key),
                "count": aggregate.count,
                "users": len(aggregate.users),
                "missing": not routes,
            }
        )
    visible_paths.sort(key=lambda row: (-row["count"], -row["users"], row["label"]))
    top_paths = visible_paths[:MAX_TOP_PATHS]

    missing_visible = (
        raw.missing_outcomes > 0 and len(raw.missing_users) >= MIN_GROUP_SIZE and raw.missing_outcomes >= min_edge_count
    )
    missing_suppressed = raw.missing_outcomes > 0 and not missing_visible
    if missing_visible:
        missing_path_outcomes: int | None = raw.missing_outcomes
        route_path_outcomes: int | None = total_outcomes - raw.missing_outcomes
        route_coverage_pct: float | None = round(route_path_outcomes / total_outcomes * 100, 2)
    elif raw.missing_outcomes == 0:
        missing_path_outcomes = 0
        route_path_outcomes = total_outcomes
        route_coverage_pct = 100.0
    else:
        missing_path_outcomes = None
        route_path_outcomes = None
        route_coverage_pct = None

    edge_total = sum(row["count"] for row in edges)
    edge_incoming_total = sum(row["incoming"] for row in nodes)
    edge_outgoing_total = sum(row["outgoing"] for row in nodes)
    source_node_total = sum(row["count"] for row in nodes if row["kind"] != "outcome")
    outcome_node_total = sum(row["count"] for row in nodes if row["kind"] == "outcome")
    route_node_balances = all(row["count"] == row["outgoing"] for row in nodes if row["kind"] != "outcome")
    outcome_node_balances = all(row["count"] == row["incoming"] for row in nodes if row["kind"] == "outcome")

    raw_edge_total = sum(aggregate.count for aggregate in raw.edges.values())
    raw_route_outgoing = sum(
        aggregate.count for node_id, aggregate in raw.nodes.items() if _node_kind(node_id) != "outcome"
    )
    raw_outcome_incoming = sum(
        aggregate.count for node_id, aggregate in raw.nodes.items() if _node_kind(node_id) == "outcome"
    )
    raw_nodes_balance = raw_route_outgoing == raw_edge_total and raw_outcome_incoming == total_outcomes

    checks = [
        _check(
            "source_nodes_reconcile",
            source_node_total == edge_total,
            f"{source_node_total} source-node flows / {edge_total} visible edges",
        ),
        _check(
            "edge_incoming_reconcile",
            edge_incoming_total == edge_total,
            f"{edge_incoming_total} incoming node flows / {edge_total} visible edges",
        ),
        _check(
            "edge_outgoing_reconcile",
            edge_outgoing_total == edge_total,
            f"{edge_outgoing_total} outgoing node flows / {edge_total} visible edges",
        ),
        _check(
            "outcome_nodes_reconcile",
            outcome_node_total == sum(row["count"] for row in edges if row["target"].startswith(OUTCOME_NODE_PREFIX)),
            f"{outcome_node_total} outcome-node flows match visible terminal edges",
        ),
        _check(
            "route_nodes_balance",
            route_node_balances,
            "Every visible route/missing node is the source of its recorded flow.",
        ),
        _check(
            "outcome_nodes_balance",
            outcome_node_balances,
            "Every visible outcome node is the target of its recorded flow.",
        ),
        _check(
            "raw_graph_balances",
            raw_nodes_balance,
            f"{raw_edge_total} raw transitions reconcile to outcome flows.",
        ),
        _check(
            "outcomes_complete",
            raw_outcome_incoming == total_outcomes,
            f"{raw_outcome_incoming} path outcomes / {total_outcomes} selected outcomes",
        ),
        _check(
            "edge_floor",
            all(len(raw.edges[edge_key].users) >= MIN_GROUP_SIZE for edge_key in visible_edge_keys),
            f"Every visible edge has at least {MIN_GROUP_SIZE} distinct users.",
        ),
        _check(
            "edge_threshold",
            all(raw.edges[edge_key].count >= min_edge_count for edge_key in visible_edge_keys),
            f"Every visible edge has at least {min_edge_count} transitions.",
        ),
        _check(
            "top_paths_limit",
            len(top_paths) <= MAX_TOP_PATHS,
            f"At most {MAX_TOP_PATHS} paths are shown per outcome.",
        ),
        _check(
            "missing_paths_labeled",
            not missing_visible or any(row["kind"] == "missing" for row in nodes),
            "Outcomes without route data are labelled, never imputed.",
        ),
    ]

    return {
        "key": key,
        "label": OUTCOME_LABELS[key],
        "status": "visible",
        "total_outcomes": total_outcomes,
        "missing_path_outcomes": missing_path_outcomes,
        "route_path_outcomes": route_path_outcomes,
        "route_coverage_pct": route_coverage_pct,
        "missing_path_suppressed": missing_suppressed,
        "nodes": nodes,
        "edges": edges,
        "top_paths": top_paths,
        "suppressed_edges": suppressed_edges,
        "thresholded_edges": thresholded_edges,
        "suppressed_paths": suppressed_paths,
        "visible_paths": len(visible_paths),
        "top_paths_truncated": len(visible_paths) > MAX_TOP_PATHS,
        "raw": {
            "outcomes": total_outcomes,
            "paths": len(raw.paths),
            "transitions": raw_edge_total,
            "route_paths": (None if missing_suppressed else total_outcomes - raw.missing_outcomes),
            "missing_path_outcomes": (raw.missing_outcomes if raw.missing_outcomes == 0 or missing_visible else None),
        },
        "reconciliation": {
            "reconciled": all(check["ok"] for check in checks),
            "checks": checks,
        },
        "notes": [
            f"Path steps are the last {MAX_PATH_ROUTE_STEPS} distinct sanitized routes in the "
            f"{PATH_LOOKBACK_DAYS}-day lookback before the outcome.",
            "Missing route data is labelled and excluded from transitions; it is never imputed.",
        ],
    }


class AdminPathAnalysisService:
    """Build the read-only aggregate path report."""

    async def snapshot(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        start_date: date | None = None,
        end_date: date | None = None,
        plan: Sequence[str] | None = None,
        cohort: str = "all",
        min_edge_count: int = 1,
    ) -> dict[str, Any]:
        start_at, end_at = _resolve_period(days=days, start_date=start_date, end_date=end_date)
        plan_filters = _normalize_plan_filter(plan)
        cohort_filter = str(cohort or "all").strip().lower()
        if cohort_filter not in COHORTS:
            raise ValueError("cohort must be one of all, new, established")
        try:
            threshold = int(min_edge_count)
        except (TypeError, ValueError) as exc:
            raise ValueError("min_edge_count must be an integer") from exc
        if threshold < 1 or threshold > 10_000:
            raise ValueError("min_edge_count must be between 1 and 10000")

        history_stmt = (
            select(
                SubscriptionHistory.user_id,
                SubscriptionHistory.subscription_id,
                SubscriptionHistory.plan_id,
                SubscriptionHistory.previous_plan_id,
                SubscriptionHistory.status,
                SubscriptionHistory.event_type,
                SubscriptionHistory.effective_at,
                User.created_at,
            )
            .join(User, User.id == SubscriptionHistory.user_id)
            .where(
                SubscriptionHistory.effective_at >= start_at,
                SubscriptionHistory.effective_at < end_at,
                SubscriptionHistory.subscription_id.is_not(None),
                SubscriptionHistory.event_type.in_(tuple(UPGRADE_EVENTS | CHURN_EVENTS)),
            )
            .order_by(
                SubscriptionHistory.user_id,
                SubscriptionHistory.effective_at,
                SubscriptionHistory.recorded_at,
            )
            .limit(MAX_OUTCOME_ROWS + 1)
        )
        history_rows = (await db.execute(history_stmt)).all()
        outcome_rows_truncated = len(history_rows) > MAX_OUTCOME_ROWS
        history_rows = history_rows[:MAX_OUTCOME_ROWS]

        upgrades: list[PathOutcome] = []
        churns: list[PathOutcome] = []
        seen_initial_upgrade_subscriptions: set[str] = set()
        seen_churn_subscriptions: set[str] = set()

        for (
            user_id,
            subscription_id,
            plan_id,
            previous_plan_id,
            status,
            event_type,
            effective_at,
            user_created_at,
        ) in history_rows:
            occurred_at = _as_utc(effective_at)
            if occurred_at is None or not user_id or not subscription_id:
                continue
            plan_family = resolve_plan_family(str(plan_id or ""))
            if plan_filters is not None and plan_family not in plan_filters:
                continue
            cohort_key = _cohort(_as_utc(user_created_at), occurred_at)
            if cohort_filter != "all" and cohort_key != cohort_filter:
                continue
            raw_status = str(status or "").strip().lower()
            raw_event = str(event_type or "").strip().lower()
            subscription_key = str(subscription_id)

            if raw_event in CHURN_EVENTS:
                if subscription_key in seen_churn_subscriptions:
                    continue
                seen_churn_subscriptions.add(subscription_key)
                churns.append(
                    PathOutcome(
                        key=CHURN,
                        user_id=str(user_id),
                        occurred_at=occurred_at,
                        plan=str(plan_id or "unknown"),
                        plan_family=plan_family,
                        cohort=cohort_key,
                    )
                )
                continue

            if raw_event not in UPGRADE_EVENTS or raw_status not in PAID_STATUSES:
                continue
            if raw_event == "plan_changed":
                if movement_direction(previous_plan_id, plan_id) != "upgrade":
                    continue
            else:
                if plan_family == "free":
                    continue
                # subscription_created and activated can describe the same first
                # paid conversion; count only the first qualifying one.
                if subscription_key in seen_initial_upgrade_subscriptions:
                    continue
                seen_initial_upgrade_subscriptions.add(subscription_key)
            upgrades.append(
                PathOutcome(
                    key=UPGRADE,
                    user_id=str(user_id),
                    occurred_at=occurred_at,
                    plan=str(plan_id or "unknown"),
                    plan_family=plan_family,
                    cohort=cohort_key,
                )
            )

        all_outcomes = [*upgrades, *churns]
        outcome_user_ids = sorted({outcome.user_id for outcome in all_outcomes})
        routes_by_user: dict[str, list[tuple[datetime, Any]]] = defaultdict(list)
        pageviews_truncated = False
        if outcome_user_ids:
            first_outcome = min(outcome.occurred_at for outcome in all_outcomes)
            last_outcome = max(outcome.occurred_at for outcome in all_outcomes)
            route_column = UsageAnalytics.event_metadata["route"].as_string()
            route_rows = (
                await db.execute(
                    select(
                        UsageAnalytics.user_id,
                        route_column,
                        UsageAnalytics.created_at,
                    )
                    .where(
                        UsageAnalytics.action == "page_view",
                        UsageAnalytics.user_id.in_(outcome_user_ids),
                        UsageAnalytics.created_at >= first_outcome - timedelta(days=PATH_LOOKBACK_DAYS),
                        UsageAnalytics.created_at < last_outcome,
                    )
                    .order_by(UsageAnalytics.user_id, UsageAnalytics.created_at, UsageAnalytics.id)
                    .limit(MAX_PAGEVIEW_ROWS + 1)
                )
            ).all()
            pageviews_truncated = len(route_rows) > MAX_PAGEVIEW_ROWS
            for user_id, raw_route, created_at in route_rows[:MAX_PAGEVIEW_ROWS]:
                event_at = _as_utc(created_at)
                if user_id and event_at is not None:
                    routes_by_user[str(user_id)].append((event_at, raw_route))

        upgrade_raw = _build_raw_section(UPGRADE, upgrades, routes_by_user)
        churn_raw = _build_raw_section(CHURN, churns, routes_by_user)
        upgrade_section = _finalize_section(upgrade_raw, min_edge_count=threshold)
        churn_section = _finalize_section(churn_raw, min_edge_count=threshold)

        distinct_outcome_users = len({outcome.user_id for outcome in all_outcomes})
        globally_suppressed = 0 < distinct_outcome_users < MIN_GROUP_SIZE
        if globally_suppressed:
            upgrade_section = _suppressed_section(UPGRADE)
            churn_section = _suppressed_section(CHURN)

        sections = [upgrade_section, churn_section]
        sections_visible = all(section["status"] in {"visible", "empty"} for section in sections)
        if sections_visible:
            total_outcomes = sum(int(section["total_outcomes"] or 0) for section in sections)
            missing_counts = [section["missing_path_outcomes"] for section in sections]
            route_counts = [section["route_path_outcomes"] for section in sections]
            missing_known = all(value is not None for value in missing_counts)
            route_known = all(value is not None for value in route_counts)
            missing_total = sum(int(value or 0) for value in missing_counts) if missing_known else None
            route_total = sum(int(value or 0) for value in route_counts) if route_known else None
            route_coverage_pct = (
                round(route_total / total_outcomes * 100, 2) if route_total is not None and total_outcomes > 0 else None
            )
        else:
            total_outcomes = None
            missing_total = None
            route_total = None
            route_coverage_pct = None

        visible_edges = sum(len(section["edges"]) for section in sections)
        suppressed_edges = sum(int(section["suppressed_edges"]) for section in sections)
        thresholded_edges = sum(int(section["thresholded_edges"]) for section in sections)
        suppressed_paths = sum(int(section["suppressed_paths"]) for section in sections)
        reconciled = all(bool(section["reconciliation"]["reconciled"]) for section in sections)

        now = datetime.now(timezone.utc)
        return {
            "days": max(1, min(int(days), MAX_RANGE_DAYS)),
            "start_date": start_at.date().isoformat(),
            "end_date": (end_at - timedelta(microseconds=1)).date().isoformat(),
            "period": {
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "timezone": "UTC",
            },
            "filters": {
                "days": max(1, min(int(days), MAX_RANGE_DAYS)),
                "start_date": start_at.date().isoformat(),
                "end_date": (end_at - timedelta(microseconds=1)).date().isoformat(),
                "plan": plan_filters,
                "cohort": cohort_filter,
                "min_edge_count": threshold,
                "timezone": "UTC",
            },
            "minimum_cohort_size": MIN_GROUP_SIZE,
            "suppressed": globally_suppressed,
            "suppression": {
                "minimum_users": MIN_GROUP_SIZE,
                "applied": globally_suppressed,
                "rule": (
                    "Sections, edges, nodes and paths with fewer than five distinct users "
                    "are suppressed; edges below the requested threshold are omitted."
                ),
                "upgrade_suppressed": upgrade_section["status"] == "suppressed",
                "churn_suppressed": churn_section["status"] == "suppressed",
                "suppressed_edges": suppressed_edges,
                "thresholded_edges": thresholded_edges,
                "suppressed_paths": suppressed_paths,
            },
            "summary": {
                "outcomes": total_outcomes,
                "upgrade_outcomes": upgrade_section["total_outcomes"],
                "churn_outcomes": churn_section["total_outcomes"],
                "paths_with_route_data": route_total,
                "paths_without_route_data": missing_total,
                "route_coverage_pct": route_coverage_pct,
                "visible_edges": visible_edges,
            },
            "upgrade": upgrade_section,
            "churn": churn_section,
            "reconciliation": {
                "reconciled": reconciled,
                "checks": [
                    _check(
                        "sections_reconcile",
                        reconciled,
                        "Every visible section's nodes and edges balance.",
                    ),
                    _check(
                        "outcome_totals_reconcile",
                        total_outcomes is None
                        or total_outcomes
                        == sum(
                            int(section["total_outcomes"] or 0)
                            for section in sections
                            if section["total_outcomes"] is not None
                        ),
                        "Upgrade and churn outcomes sum to the selected total.",
                    ),
                ],
            },
            "data_source": {
                "kind": "first_party_event_sequences",
                "pageview_action": "page_view",
                "route_field": "event_metadata.route",
                "outcome_source": "subscription_history",
                "posthog_paths_queried": False,
                "path_lookback_days": PATH_LOOKBACK_DAYS,
                "max_route_steps": MAX_PATH_ROUTE_STEPS,
                "upgrade_rule": (
                    "First paid subscription_created/activated event, or a plan_changed "
                    "event whose plan rank increases."
                ),
                "churn_rule": "First cancelled or expired transition for a subscription.",
            },
            "data_quality": {
                "outcome_rows_truncated": outcome_rows_truncated,
                "pageviews_truncated": pageviews_truncated,
                "max_outcome_rows": MAX_OUTCOME_ROWS,
                "max_pageview_rows": MAX_PAGEVIEW_ROWS,
                "missing_path_label": MISSING_LABEL,
                "missing_path_imputed": False,
            },
            "privacy": {
                "aggregate_only": True,
                "per_user_rows": False,
                "minimum_users": MIN_GROUP_SIZE,
                "route_sanitization": (
                    "Query strings, fragments, opaque route identifiers and document "
                    "content are stripped before a route is stored or returned."
                ),
                "excluded_fields": [
                    "email",
                    "user_agent",
                    "ip_address",
                    "device_fingerprint",
                    "document_id",
                    "document_content",
                    "share_token",
                    "query_string",
                    "provider_payload",
                ],
            },
            "automation": {
                "automatic_refund": False,
                "automatic_grant": False,
                "automatic_enforcement": False,
                "read_only": True,
            },
            "notes": [
                "Read-only aggregate view; no plan, subscription, refund or entitlement is changed.",
                "Route events are first-party only; PostHog saved insights are not queried by this surface.",
                "Only authenticated page_view rows are joined to outcomes; anonymous pre-login paths are never linked into an account sequence.",
                "Outcomes with no route rows are shown as 'Path data missing' and never receive an inferred transition.",
            ],
            "generated_at": now.isoformat(),
        }

    def to_csv(self, result: Mapping[str, Any]) -> str:
        """Render the report as a flat, privacy-safe CSV."""

        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)

        def emit(
            section: str,
            outcome: str = "",
            source: str = "",
            target: str = "",
            label: str = "",
            count: Any = "",
            users: Any = "",
            suppressed: Any = "",
            note: str = "",
        ) -> None:
            writer.writerow(
                [
                    section,
                    outcome,
                    source,
                    target,
                    label,
                    "" if count is None else count,
                    "" if users is None else users,
                    "yes" if suppressed is True else "no" if suppressed is False else "",
                    note,
                ]
            )

        for section_key in (UPGRADE, CHURN):
            section = result.get(section_key) or {}
            emit(
                "summary",
                section_key,
                label="total outcomes",
                count=section.get("total_outcomes"),
                note=section.get("status", ""),
            )
            emit(
                "summary",
                section_key,
                label="outcomes with route data",
                count=section.get("route_path_outcomes"),
                suppressed=section.get("missing_path_suppressed"),
            )
            emit(
                "summary",
                section_key,
                label=MISSING_LABEL,
                count=section.get("missing_path_outcomes"),
                suppressed=section.get("missing_path_suppressed"),
                note="never imputed",
            )
            for row in section.get("top_paths") or []:
                emit(
                    "path",
                    section_key,
                    label=row.get("label", ""),
                    count=row.get("count"),
                    users=row.get("users"),
                    note="missing path data" if row.get("missing") else "",
                )
            for row in section.get("edges") or []:
                emit(
                    "edge",
                    section_key,
                    source=row.get("source_label", ""),
                    target=row.get("target_label", ""),
                    label=row.get("label", ""),
                    count=row.get("count"),
                    users=row.get("users"),
                )
            for row in section.get("nodes") or []:
                emit(
                    "node",
                    section_key,
                    source=row.get("id", ""),
                    label=row.get("label", ""),
                    count=row.get("count"),
                    users=row.get("users"),
                )
            emit(
                "suppression",
                section_key,
                label="suppressed edges",
                count=section.get("suppressed_edges"),
            )
            emit(
                "suppression",
                section_key,
                label="edges below threshold",
                count=section.get("thresholded_edges"),
            )
            emit(
                "suppression",
                section_key,
                label="suppressed paths",
                count=section.get("suppressed_paths"),
            )
            emit(
                "summary",
                section_key,
                label="visible paths",
                count=section.get("visible_paths"),
                note="top 10 shown" if section.get("top_paths_truncated") else "",
            )

        emit(
            "reconciliation",
            label="all sections reconcile",
            suppressed=False,
            note="yes" if result.get("reconciliation", {}).get("reconciled") else "no",
        )
        return buffer.getvalue()


admin_path_analysis_service = AdminPathAnalysisService()
