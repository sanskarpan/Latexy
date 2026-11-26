"""Admin optimization candidate acceptance, aggregate-only.

Two first-party decision ledgers are reconciled:

* ``resume_optimization_runs.decisions.patches`` maps a candidate patch id to
  the user's terminal ``accepted``/``rejected`` choice. The candidate list is
  read from ``result.patches`` without selecting patch text.
* ``resume_suggestion_decisions`` stores one unique row per resume/suggestion
  pair. ``accepted`` and ``rejected`` are decisions; ``conflicted`` rows are
  candidates the user could no longer apply and are reported as discarded.

``candidates_shown`` is the number of candidate patches exposed by a completed
run plus retained suggestion decision rows. Suggestion proposals are ephemeral
awareness payloads, so only decided suggestion rows are retained; for that
source ``candidates_shown == decided`` is an explicit, limited proxy.

The report never selects suggestion text, patch text, resume/LaTeX content,
prompts, job descriptions or per-user rows. Breakdown rows with fewer than five
distinct users are omitted. Run rows are counted only while their existing
seven-day retention window is active; suggestion rows are counted only while
the suggestion-decision retention policy keeps them.
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES
from ..database import models
from .admin_ai_cost_service import _persona as _resume_persona

Run = models.ResumeOptimizationRun
SuggestionDecision = models.ResumeSuggestionDecision
Resume = models.Resume
User = models.User

MIN_GROUP_SIZE = 5
MAX_RANGE_DAYS = 365
RUN_SOURCE = "resume_optimization_runs"
SUGGESTION_SOURCE = "resume_suggestion_decisions"
INLINE_SUGGESTIONS = "inline_suggestions"
RUN_STATUSES = ("completed", "partial")
RUN_OUTCOMES = frozenset({"accepted", "rejected"})
SUGGESTION_OUTCOMES = frozenset({"accepted", "rejected", "conflicted"})
CSV_COLUMNS = (
    "dimension",
    "key",
    "candidates_shown",
    "decided",
    "accepted",
    "rejected",
    "discarded",
    "undecided",
    "acceptance_rate_pct",
    "decision_rate_pct",
    "accepted_of_shown_pct",
    "users",
)
_SECTION_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_SAFE_CSV_PREFIXES = {"=", "+", "-", "@", "\t", "\r"}


def _as_date(value: date | str | None) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("date range must use YYYY-MM-DD") from exc


def _resolve_range(
    *,
    days: int,
    start_date: date | str | None,
    end_date: date | str | None,
) -> tuple[date, date, datetime, datetime]:
    """Return inclusive day bounds plus the UTC half-open event range."""
    today = datetime.now(timezone.utc).date()
    start_day = _as_date(start_date)
    end_day = _as_date(end_date)
    if start_day is None and end_day is None:
        end_day = today
        start_day = end_day - timedelta(days=max(1, int(days)) - 1)
    elif start_day is None:
        end_day = end_day or today
        start_day = end_day - timedelta(days=max(1, int(days)) - 1)
    elif end_day is None:
        end_day = today

    assert start_day is not None and end_day is not None
    if start_day > end_day:
        raise ValueError("start_date must be on or before end_date")
    if (end_day - start_day).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(f"date range cannot exceed {MAX_RANGE_DAYS} days")

    start_at = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start_day, end_day, start_at, end_at


def _split_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _filter_value(value: str | None, limit: int) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized[:limit] if normalized else None


def _plan_bucket(value: Any) -> str:
    normalized = str(value or "free").strip().lower()
    if not normalized:
        normalized = "free"
    return PLAN_FAMILY_ALIASES.get(normalized, normalized)[:50]


def _day_key(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return "unknown"


def _event_persona(run_persona: Any, resume_persona: Any) -> str:
    if run_persona:
        persona = _resume_persona({"last_persona": run_persona})
        if persona != "unknown":
            return persona
    return _resume_persona({"last_persona": resume_persona})


def _run_feature(node_id: Any) -> str:
    if not isinstance(node_id, str):
        return "other"
    prefix = node_id.split(".", 1)[0].strip().lower()
    return prefix if _SECTION_RE.fullmatch(prefix) else "other"


def _safe_csv_cell(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if value[:1] in _SAFE_CSV_PREFIXES:
        return f"'{value}"
    return value


@dataclass
class _Bucket:
    shown: int = 0
    accepted: int = 0
    rejected: int = 0
    discarded: int = 0
    users: set[str] = field(default_factory=set)

    @property
    def decided(self) -> int:
        return self.accepted + self.rejected + self.discarded

    @property
    def undecided(self) -> int:
        return max(0, self.shown - self.decided)

    def add(self, user_id: str | None, outcome: str | None) -> None:
        self.shown += 1
        if user_id:
            self.users.add(user_id)
        if outcome == "accepted":
            self.accepted += 1
        elif outcome == "rejected":
            self.rejected += 1
        elif outcome == "discarded":
            self.discarded += 1


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 2) if whole else 0.0


def _metrics(bucket: _Bucket) -> dict[str, Any]:
    return {
        "candidates_shown": bucket.shown,
        "decided": bucket.decided,
        "accepted": bucket.accepted,
        "rejected": bucket.rejected,
        "discarded": bucket.discarded,
        "undecided": bucket.undecided,
        "acceptance_rate_pct": _pct(bucket.accepted, bucket.decided),
        "decision_rate_pct": _pct(bucket.decided, bucket.shown),
        "accepted_of_shown_pct": _pct(bucket.accepted, bucket.shown),
        "users": len(bucket.users),
    }


def _zero_metrics() -> dict[str, Any]:
    empty = _Bucket()
    return _metrics(empty)


class AdminOptimizationAcceptanceService:
    async def acceptance_report(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        plan: str | None = None,
        feature: str | None = None,
        persona: str | None = None,
    ) -> dict[str, Any]:
        days = max(1, min(int(days), MAX_RANGE_DAYS))
        start_day, end_day, start_at, end_at = _resolve_range(
            days=days, start_date=start_date, end_date=end_date
        )
        selected_range_days = (end_day - start_day).days + 1
        plans = sorted({_plan_bucket(item) for item in _split_csv(plan)})
        if len(plans) > 25:
            raise ValueError("at most 25 plans can be selected")
        feature_filter = _filter_value(feature, 40)
        persona_filter = _filter_value(persona, 64)
        now = datetime.now(timezone.utc)

        total = _Bucket()
        by_day: dict[str, _Bucket] = defaultdict(_Bucket)
        by_feature: dict[str, _Bucket] = defaultdict(_Bucket)
        by_persona: dict[str, _Bucket] = defaultdict(_Bucket)
        by_plan: dict[str, _Bucket] = defaultdict(_Bucket)
        by_source: dict[str, _Bucket] = defaultdict(_Bucket)

        def include(
            *,
            user_id: str | None,
            day: str,
            feature_name: str,
            persona_name: str,
            plan_name: str,
            source: str,
            outcome: str | None,
        ) -> None:
            for bucket in (total, by_day[day], by_feature[feature_name], by_persona[persona_name],
                           by_plan[plan_name], by_source[source]):
                bucket.add(user_id, outcome)

        # Run candidates: read only ids and the terminal status map. Patch text
        # is deliberately never selected.
        run_stmt = (
            select(
                Run.id,
                Run.user_id,
                Run.decisions,
                Run.updated_at,
                Run.context_payload["direction"]["persona"].astext.label("run_persona"),
                User.subscription_plan,
                Resume.resume_settings["last_persona"].astext.label("resume_persona"),
                func.jsonb_path_query_array(
                    Run.result, text("'$.patches[*].patch_id'::jsonpath")
                ).cast(JSONB).label("patch_ids"),
                func.jsonb_path_query_array(
                    Run.result, text("'$.patches[*].node_id'::jsonpath")
                ).cast(JSONB).label("node_ids"),
            )
            .outerjoin(User, User.id == Run.user_id)
            .outerjoin(Resume, Resume.id == Run.resume_id)
            .where(
                Run.updated_at >= start_at,
                Run.updated_at < end_at,
                Run.expires_at > now,
                Run.status.in_(RUN_STATUSES),
                Run.result.is_not(None),
            )
        )
        run_rows = (await db.execute(run_stmt)).all()

        expired_run_count = int(
            (
                await db.execute(
                    select(func.count(Run.id)).where(
                        Run.updated_at >= start_at,
                        Run.updated_at < end_at,
                        Run.expires_at <= now,
                        Run.status.in_(RUN_STATUSES),
                        Run.result.is_not(None),
                    )
                )
            ).scalar()
            or 0
        )

        run_rows_scanned = 0
        run_candidates = 0
        run_decision_keys = 0
        run_unmatched_decisions = 0
        run_invalid_decisions = 0
        run_duplicate_patch_ids = 0

        for row in run_rows:
            plan_name = _plan_bucket(row.subscription_plan)
            if plans and plan_name not in plans:
                continue
            persona_name = _event_persona(row.run_persona, row.resume_persona)
            if persona_filter and persona_name != persona_filter:
                continue
            run_rows_scanned += 1
            user_id = str(row.user_id) if row.user_id else None
            day = _day_key(row.updated_at)
            patch_ids = row.patch_ids if isinstance(row.patch_ids, list) else []
            node_ids = row.node_ids if isinstance(row.node_ids, list) else []
            patch_features: dict[str, str] = {}
            for index, patch_id in enumerate(patch_ids):
                if not isinstance(patch_id, str) or not patch_id:
                    continue
                node_id = node_ids[index] if index < len(node_ids) else None
                if patch_id in patch_features:
                    run_duplicate_patch_ids += 1
                    continue
                patch_features[patch_id] = _run_feature(node_id)

            decisions = row.decisions if isinstance(row.decisions, dict) else {}
            raw_statuses = decisions.get("patches") if isinstance(decisions, dict) else None
            statuses = raw_statuses if isinstance(raw_statuses, dict) else {}
            for patch_id, feature_name in patch_features.items():
                if feature_filter and feature_name != feature_filter:
                    continue
                status = statuses.get(patch_id)
                outcome = status if status in RUN_OUTCOMES else None
                if status is not None and outcome is None:
                    run_invalid_decisions += 1
                if outcome is not None:
                    run_decision_keys += 1
                run_candidates += 1
                include(
                    user_id=user_id,
                    day=day,
                    feature_name=feature_name,
                    persona_name=persona_name,
                    plan_name=plan_name,
                    source=RUN_SOURCE,
                    outcome=outcome,
                )
            run_unmatched_decisions += sum(1 for key in statuses if key not in patch_features)

        # Suggestion decisions: one retained row per (resume, suggestion id).
        suggestion_stmt = (
            select(
                SuggestionDecision.id,
                SuggestionDecision.status,
                SuggestionDecision.created_at,
                Resume.user_id,
                User.subscription_plan,
                Resume.resume_settings["last_persona"].astext.label("resume_persona"),
            )
            .join(Resume, Resume.id == SuggestionDecision.resume_id)
            .outerjoin(User, User.id == Resume.user_id)
            .where(
                SuggestionDecision.created_at >= start_at,
                SuggestionDecision.created_at < end_at,
            )
        )
        suggestion_rows = (await db.execute(suggestion_stmt)).all()

        suggestion_rows_scanned = 0
        suggestion_accepted = 0
        suggestion_rejected = 0
        suggestion_discarded = 0
        suggestion_invalid = 0
        suggestion_filtered_out = 0

        for row in suggestion_rows:
            plan_name = _plan_bucket(row.subscription_plan)
            if plans and plan_name not in plans:
                continue
            persona_name = _event_persona(None, row.resume_persona)
            if persona_filter and persona_name != persona_filter:
                continue
            if feature_filter and feature_filter != INLINE_SUGGESTIONS:
                suggestion_filtered_out += 1
                continue
            status = row.status if isinstance(row.status, str) else ""
            if status not in SUGGESTION_OUTCOMES:
                suggestion_invalid += 1
                continue
            outcome = "discarded" if status == "conflicted" else status
            if outcome == "accepted":
                suggestion_accepted += 1
            elif outcome == "rejected":
                suggestion_rejected += 1
            else:
                suggestion_discarded += 1
            suggestion_rows_scanned += 1
            include(
                user_id=str(row.user_id) if row.user_id else None,
                day=_day_key(row.created_at),
                feature_name=INLINE_SUGGESTIONS,
                persona_name=persona_name,
                plan_name=plan_name,
                source=SUGGESTION_SOURCE,
                outcome=outcome,
            )

        filtered_suppressed = total.shown > 0 and len(total.users) < MIN_GROUP_SIZE

        def _rows(
            dimension: str,
            groups: dict[str, _Bucket],
            *,
            sort_desc: bool = True,
        ) -> tuple[list[dict[str, Any]], int]:
            if filtered_suppressed:
                return [], len(groups)
            rows: list[dict[str, Any]] = []
            suppressed = 0
            for key, bucket in groups.items():
                if len(bucket.users) < MIN_GROUP_SIZE:
                    suppressed += 1
                    continue
                rows.append({dimension: key, **_metrics(bucket)})
            if dimension == "date":
                rows.sort(key=lambda item: item["date"])
            else:
                rows.sort(
                    key=lambda item: (
                        -item["decided"] if sort_desc else item["decided"],
                        -item["candidates_shown"],
                        item[dimension],
                    )
                )
            return rows, suppressed

        day_rows, day_suppressed = _rows("date", by_day, sort_desc=False)
        feature_rows, feature_suppressed = _rows("feature", by_feature)
        persona_rows, persona_suppressed = _rows("persona", by_persona)
        plan_rows, plan_suppressed = _rows("plan", by_plan)
        source_rows, source_suppressed = _rows("source", by_source)
        suppressed_by_dimension = {
            "date": day_suppressed,
            "feature": feature_suppressed,
            "persona": persona_suppressed,
            "plan": plan_suppressed,
            "source": source_suppressed,
        }
        suppressed_rows = sum(suppressed_by_dimension.values())

        totals = _zero_metrics() if filtered_suppressed else _metrics(total)

        if filtered_suppressed:
            run_candidates = run_decision_keys = run_unmatched_decisions = 0
            run_invalid_decisions = run_duplicate_patch_ids = 0
            run_rows_scanned = expired_run_count = 0
            suggestion_rows_scanned = suggestion_accepted = suggestion_rejected = 0
            suggestion_discarded = suggestion_invalid = suggestion_filtered_out = 0

        accepted = totals["accepted"]
        rejected = totals["rejected"]
        discarded = totals["discarded"]
        decided = totals["decided"]
        shown = totals["candidates_shown"]
        reconciled = bool(
            decided == accepted + rejected + discarded
            and shown == decided + totals["undecided"]
            and decided == run_decision_keys + suggestion_rows_scanned
            and shown == run_candidates + suggestion_rows_scanned
        )

        return {
            "days": selected_range_days,
            "start_date": start_day.isoformat(),
            "end_date": end_day.isoformat(),
            "timezone": "UTC",
            "date_range": {
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "days": selected_range_days,
                "timezone": "UTC",
            },
            "filters": {
                "days": selected_range_days,
                "start_date": start_day.isoformat(),
                "end_date": end_day.isoformat(),
                "plan": plans or None,
                "feature": feature_filter,
                "persona": persona_filter,
                "timezone": "UTC",
            },
            "minimum_users": MIN_GROUP_SIZE,
            "suppressed": filtered_suppressed,
            "suppression": {
                "minimum_users": MIN_GROUP_SIZE,
                "rule": "Hide a breakdown row with fewer than 5 distinct users.",
                "filtered_suppressed": filtered_suppressed,
                "suppressed_rows": suppressed_rows,
                "by_dimension": suppressed_by_dimension,
            },
            "totals": totals,
            "by_day": day_rows,
            "by_feature": feature_rows,
            "by_persona": persona_rows,
            "by_plan": plan_rows,
            "by_source": source_rows,
            "reconciliation": {
                "tables": [RUN_SOURCE, SUGGESTION_SOURCE],
                "run_rows_scanned": run_rows_scanned,
                "run_expired_rows_excluded": expired_run_count,
                "run_candidates_shown": run_candidates,
                "run_decision_keys": run_decision_keys,
                "run_unmatched_decisions": run_unmatched_decisions,
                "run_invalid_decisions": run_invalid_decisions,
                "run_duplicate_patch_ids": run_duplicate_patch_ids,
                "suggestion_rows_scanned": suggestion_rows_scanned,
                "suggestion_accepted": suggestion_accepted,
                "suggestion_rejected": suggestion_rejected,
                "suggestion_discarded": suggestion_discarded,
                "suggestion_invalid_status": suggestion_invalid,
                "suggestion_filtered_out": suggestion_filtered_out,
                "candidates_shown": shown,
                "decided": decided,
                "accepted": accepted,
                "rejected": rejected,
                "discarded": discarded,
                "undecided": totals["undecided"],
                "reconciled": reconciled,
                "hidden_by_suppression": filtered_suppressed,
            },
            "retention": {
                "run_decisions": (
                    "Only runs whose existing 7-day retention window is still active are counted. "
                    "Per-patch decision timestamps are not retained; the run's last update day is used."
                ),
                "suggestion_decisions": (
                    "Only suggestion rows still retained by the existing decision policy are counted. "
                    "Rejected/conflicted rows are short-lived; accepted idempotency tombstones expire "
                    "after 30 days."
                ),
            },
            "persona_source": (
                "Semantic optimization runs use the persisted job-submission persona; otherwise the "
                "resume's last saved persona metadata is used, and missing values stay unknown."
            ),
            "feature_source": (
                "Run candidates are grouped by resume section (for example experience or summary). "
                "Suggestion decisions are grouped as inline_suggestions because proposals are ephemeral."
            ),
            "privacy": {
                "aggregate_only": True,
                "per_user_rows": False,
                "content_fields_read": [
                    "resume_optimization_runs.decisions.patches",
                    "resume_optimization_runs.result.patches[*].patch_id",
                    "resume_optimization_runs.result.patches[*].node_id",
                    "resume_optimization_runs.context_payload.direction.persona",
                    "resume.metadata.last_persona",
                ],
                "content_fields_excluded": [
                    "suggestion text",
                    "candidate patch text",
                    "resume/LaTeX content",
                    "job descriptions and prompts",
                    "per-user payloads",
                ],
            },
            "notes": [
                "candidates_shown is the patch count in completed runs plus retained suggestion decisions.",
                "decided is accepted + rejected + discarded; conflicted suggestions are discarded.",
                "Suggestion proposals are ephemeral, so a suggestion row is both shown and decided.",
                "Run decisions use the run's last update day because per-patch timestamps are not retained.",
                "Breakdown rows under 5 distinct users are suppressed; totals remain aggregate-only.",
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def to_csv(self, result: dict[str, Any]) -> str:
        """Render only the already-suppressed aggregate rows."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        writer.writerow(
            ["total", "all", *[result["totals"].get(column) for column in CSV_COLUMNS[2:]]]
        )
        for dimension, key in (
            ("date", "by_day"),
            ("feature", "by_feature"),
            ("persona", "by_persona"),
            ("plan", "by_plan"),
            ("source", "by_source"),
        ):
            for row in result.get(key, []):
                writer.writerow(
                    [dimension, _safe_csv_cell(row.get(dimension))]
                    + [
                        _safe_csv_cell(row.get(column))
                        for column in CSV_COLUMNS[2:]
                    ]
                )
        return buffer.getvalue()


admin_optimization_acceptance_service = AdminOptimizationAcceptanceService()
