"""Admin-only quarterly access review for privileged accounts.

The review enumerates every ``admin`` and ``support`` account with the current
role, two-factor/passkey posture, last login/session activity and account age.
Last login is derived from Better Auth ``session."createdAt"``. The query never
selects ``session.token``, ``session."ipAddress"``, ``session."userAgent"``,
TOTP secrets, backup codes or passkey credential material, so a token or secret
cannot leak through this surface even by accident.

The review is read-only. Attestations are appended to the existing immutable
``admin_audit_log``; no role, session or credential is changed and no automatic
demotion exists. A submit is bound to the exact roster/security-posture snapshot
the reviewer loaded: if an account is added, removed, changes role, or enables
or removes 2FA/passkeys in between, the server rejects the stale attestation
with a ``409`` conflict instead of attesting data nobody reviewed.

Five-user suppression is intentionally not applied here: this is a security
inventory of privileged accounts, and hiding a small admin list would defeat
the review. The endpoint is admin-only, returns masked identities, and never
returns per-account activity histories.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models
from .admin_audit_service import AdminActor, record_admin_audit
from .admin_user_service import mask_email, mask_name

User = models.User
AdminAuditLog = models.AdminAuditLog

REVIEW_ROLES: tuple[str, ...] = ("admin", "support")
ROLE_RANK = {"admin": 0, "support": 1}
STALE_AFTER_DAYS = 90
MAX_EXPECTED_ACCOUNTS = 500
MAX_CONFLICT_ITEMS = 50
HISTORY_LIMIT = 12
ATTESTATION_DECISIONS = ("attested", "follow_up_required")
AUDIT_ACTION = "access_review.attest"
AUDIT_TARGET_TYPE = "access_review"
ATTESTATION_LOCK_ID = 4_752_861_104
MIN_NOTE_LENGTH = 10
MAX_NOTE_LENGTH = 1000
MAX_IDEMPOTENCY_KEY_LENGTH = 120

CSV_COLUMNS = (
    "quarter",
    "user_id",
    "email_masked",
    "name_masked",
    "role",
    "two_factor_enabled",
    "passkey_count",
    "strong_auth",
    "last_login_at",
    "last_activity_at",
    "active_sessions",
    "session_count",
    "account_age_days",
    "stale",
    "never_used",
    "missing_two_factor",
    "missing_strong_auth",
    "flags",
    "generated_at",
)


class AccessReviewConflict(RuntimeError):
    """A reviewed snapshot no longer matches the current privileged roster."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
        status_code: int = 409,
    ) -> None:
        self.code = code
        self.details = dict(details) if details else None
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class Quarter:
    label: str
    year: int
    number: int
    start: datetime
    end: datetime  # exclusive


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return _utc(value).isoformat() if value else None


def _quarter_for(now: datetime) -> Quarter:
    now = _utc(now)
    number = (now.month - 1) // 3 + 1
    start_month = 3 * (number - 1) + 1
    start = datetime(now.year, start_month, 1, tzinfo=timezone.utc)
    if number == 4:
        end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(now.year, start_month + 3, 1, tzinfo=timezone.utc)
    return Quarter(
        label=f"{now.year}-Q{number}",
        year=now.year,
        number=number,
        start=start,
        end=end,
    )


def _account_signature(accounts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Fields that define the reviewed security posture, in stable order."""
    return [
        {
            "user_id": str(account["user_id"]),
            "role": str(account["role"]),
            "two_factor_enabled": bool(account["two_factor_enabled"]),
            "passkey_count": int(account["passkey_count"]),
        }
        for account in sorted(accounts, key=lambda item: str(item["user_id"]))
    ]


def _snapshot_hash(quarter: Quarter, accounts: Sequence[Mapping[str, Any]]) -> str:
    payload = {
        "quarter": quarter.label,
        "stale_after_days": STALE_AFTER_DAYS,
        "accounts": _account_signature(accounts),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_csv_cell(value: Any) -> str:
    """Neutralise spreadsheet formulas without altering ordinary values."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text_value = str(value)
    if text_value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text_value
    return text_value


def _masked_email(value: Optional[str]) -> Optional[str]:
    return mask_email(value) if isinstance(value, str) else None


def _masked_name(value: Optional[str]) -> Optional[str]:
    return mask_name(value) if isinstance(value, str) else None


async def _session_aggregates(
    db: AsyncSession,
    user_ids: Sequence[str],
    *,
    now: datetime,
) -> dict[str, Any]:
    if not user_ids:
        return {}
    statement = text(
        'SELECT "userId" AS user_id, '
        "count(*) AS session_count, "
        'max("createdAt") AS last_login_at, '
        'max("updatedAt") AS last_activity_at, '
        'max("expiresAt") AS last_session_expires_at, '
        'count(*) FILTER (WHERE "expiresAt" > :now) AS active_sessions '
        'FROM session WHERE "userId" IN :ids GROUP BY "userId"'
    ).bindparams(bindparam("ids", expanding=True))
    rows = (await db.execute(statement, {"ids": list(user_ids), "now": now})).mappings().all()
    return {str(row["user_id"]): row for row in rows}


async def _passkey_counts(db: AsyncSession, user_ids: Sequence[str]) -> dict[str, int]:
    if not user_ids:
        return {}
    statement = text(
        'SELECT "userId" AS user_id, count(*) AS passkey_count FROM passkey WHERE "userId" IN :ids GROUP BY "userId"'
    ).bindparams(bindparam("ids", expanding=True))
    rows = (await db.execute(statement, {"ids": list(user_ids)})).mappings().all()
    return {str(row["user_id"]): int(row["passkey_count"] or 0) for row in rows}


def _build_accounts(
    users: Iterable[User],
    sessions: Mapping[str, Any],
    passkeys: Mapping[str, int],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    stale_before = now - timedelta(days=STALE_AFTER_DAYS)
    accounts: list[dict[str, Any]] = []
    for user in users:
        session = sessions.get(str(user.id))
        session_count = int(session["session_count"] or 0) if session else 0
        active_sessions = int(session["active_sessions"] or 0) if session else 0
        last_login = session["last_login_at"] if session else None
        last_activity = session["last_activity_at"] if session else None
        last_expires = session["last_session_expires_at"] if session else None
        passkey_count = int(passkeys.get(str(user.id), 0))
        two_factor_enabled = bool(user.two_factor_enabled)
        strong_auth = two_factor_enabled or passkey_count > 0
        never_used = session_count == 0

        created_at = _utc(user.created_at) if user.created_at else None
        account_age_days = max(0, (now - created_at).days) if created_at else None

        # "Stale" means the account has no login or session activity inside the
        # review window. A never-used privileged account becomes stale once it
        # is older than the window, so account creation alone cannot hide an
        # unused admin.
        seen = [value for value in (last_login, last_activity) if value is not None]
        last_seen = max((_utc(value) for value in seen), default=created_at)
        stale = bool(last_seen is not None and last_seen <= stale_before)

        flags: list[str] = []
        if not two_factor_enabled:
            flags.append("missing_two_factor")
        if not strong_auth:
            flags.append("missing_strong_auth")
        if stale:
            flags.append("stale")
        if never_used:
            flags.append("never_used")

        accounts.append(
            {
                "user_id": str(user.id),
                "email_masked": _masked_email(user.email),
                "name_masked": _masked_name(user.name),
                "role": str(user.role),
                "two_factor_enabled": two_factor_enabled,
                "passkey_count": passkey_count,
                "strong_auth": strong_auth,
                "missing_two_factor": not two_factor_enabled,
                "missing_strong_auth": not strong_auth,
                "last_login_at": _iso(last_login),
                "last_activity_at": _iso(last_activity),
                "last_session_expires_at": _iso(last_expires),
                "session_count": session_count,
                "active_sessions": active_sessions,
                "account_age_days": account_age_days,
                "stale": stale,
                "never_used": never_used,
                "flags": flags,
            }
        )

    # Highest-risk privileged accounts first: no 2FA, admins before support,
    # dormant before recently active, then oldest login and a stable id tiebreak.
    accounts.sort(
        key=lambda item: (
            0 if item["missing_two_factor"] else 1,
            ROLE_RANK.get(item["role"], 2),
            0 if item["stale"] else 1,
            item["last_login_at"] or "",
            item["user_id"],
        )
    )
    return accounts


def _flag(
    *,
    code: str,
    label: str,
    severity: str,
    accounts: Sequence[Mapping[str, Any]],
    predicate,
) -> dict[str, Any]:
    matching = [account for account in accounts if predicate(account)]
    return {
        "code": code,
        "label": label,
        "severity": severity,
        "count": len(matching),
        "account_ids": [str(account["user_id"]) for account in matching[:MAX_CONFLICT_ITEMS]],
        "truncated": len(matching) > MAX_CONFLICT_ITEMS,
    }


def _summary(accounts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    admins = [account for account in accounts if account["role"] == "admin"]
    support = [account for account in accounts if account["role"] == "support"]
    total = len(accounts)
    two_factor = sum(1 for account in accounts if account["two_factor_enabled"])
    strong = sum(1 for account in accounts if account["strong_auth"])
    return {
        "total": total,
        "admins": len(admins),
        "support": len(support),
        "two_factor_enabled": two_factor,
        "without_two_factor": total - two_factor,
        "admins_without_2fa": sum(1 for account in admins if account["missing_two_factor"]),
        "support_without_2fa": sum(1 for account in support if account["missing_two_factor"]),
        "strong_auth_enabled": strong,
        "without_strong_auth": total - strong,
        "admins_without_strong_auth": sum(1 for account in admins if account["missing_strong_auth"]),
        "stale": sum(1 for account in accounts if account["stale"]),
        "stale_admins": sum(1 for account in admins if account["stale"]),
        "stale_support": sum(1 for account in support if account["stale"]),
        "never_used": sum(1 for account in accounts if account["never_used"]),
        "never_used_admins": sum(1 for account in admins if account["never_used"]),
        "never_used_support": sum(1 for account in support if account["never_used"]),
        "active_sessions": sum(int(account["active_sessions"]) for account in accounts),
        "flagged": sum(1 for account in accounts if account["flags"]),
        "two_factor_coverage_pct": round(two_factor / total * 100, 2) if total else 0.0,
        "strong_auth_coverage_pct": round(strong / total * 100, 2) if total else 0.0,
    }


def _flag_rows(accounts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        _flag(
            code="admin_without_2fa",
            label="Admin accounts without two-factor authentication",
            severity="high",
            accounts=accounts,
            predicate=lambda account: account["role"] == "admin" and account["missing_two_factor"],
        ),
        _flag(
            code="support_without_2fa",
            label="Support accounts without two-factor authentication",
            severity="medium",
            accounts=accounts,
            predicate=lambda account: account["role"] == "support" and account["missing_two_factor"],
        ),
        _flag(
            code="without_strong_auth",
            label="Privileged accounts without 2FA or a passkey",
            severity="high",
            accounts=accounts,
            predicate=lambda account: account["missing_strong_auth"],
        ),
        _flag(
            code="stale_admin",
            label="Admin accounts with no login in the review window",
            severity="medium",
            accounts=accounts,
            predicate=lambda account: account["role"] == "admin" and account["stale"],
        ),
        _flag(
            code="never_used_admin",
            label="Admin accounts with no recorded session",
            severity="high",
            accounts=accounts,
            predicate=lambda account: account["role"] == "admin" and account["never_used"],
        ),
    ]


def _attestation_summary(row: AdminAuditLog) -> dict[str, Any]:
    metadata = row.event_metadata if isinstance(row.event_metadata, dict) else {}
    return {
        "audit_id": str(row.id),
        "quarter": row.target_id,
        "decision": metadata.get("decision"),
        "note": row.reason,
        "attested_at": _iso(row.created_at),
        "attested_by_user_id": row.actor_user_id,
        "attested_by_email_masked": _masked_email(row.actor_email),
        "roster_size": metadata.get("roster_size"),
        "admins": metadata.get("admins"),
        "support": metadata.get("support"),
        "admins_without_2fa": metadata.get("admins_without_2fa"),
        "support_without_2fa": metadata.get("support_without_2fa"),
        "stale": metadata.get("stale"),
        "never_used": metadata.get("never_used"),
        "active_sessions": metadata.get("active_sessions"),
        "snapshot_hash": metadata.get("snapshot_hash"),
        "automatic_demotion": False,
    }


async def _attestation_rows(
    db: AsyncSession,
    *,
    quarter: Quarter,
) -> tuple[Optional[AdminAuditLog], list[AdminAuditLog]]:
    base = (
        select(AdminAuditLog)
        .where(
            AdminAuditLog.action == AUDIT_ACTION,
            AdminAuditLog.target_type == AUDIT_TARGET_TYPE,
        )
        .order_by(AdminAuditLog.created_at.desc())
    )
    history = list((await db.execute(base.limit(HISTORY_LIMIT))).scalars().all())
    latest = (await db.execute(base.where(AdminAuditLog.target_id == quarter.label).limit(1))).scalar_one_or_none()
    return latest, history


async def access_review_snapshot(
    db: AsyncSession,
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Return the current privileged roster, flags and attestation state."""
    current = _utc(now or datetime.now(timezone.utc))
    quarter = _quarter_for(current)

    users = (
        (
            await db.execute(
                select(User)
                .where(User.role.in_(REVIEW_ROLES))
                .order_by(User.created_at.asc().nulls_last(), User.id.asc())
            )
        )
        .scalars()
        .all()
    )
    user_ids = [str(user.id) for user in users]
    sessions = await _session_aggregates(db, user_ids, now=current)
    passkeys = await _passkey_counts(db, user_ids)
    accounts = _build_accounts(users, sessions, passkeys, now=current)
    summary = _summary(accounts)
    snapshot_hash = _snapshot_hash(quarter, accounts)
    latest, history = await _attestation_rows(db, quarter=quarter)
    latest_summary = _attestation_summary(latest) if latest else None

    return {
        "quarter": quarter.label,
        "quarter_bounds": {
            "start": quarter.start.date().isoformat(),
            "end": (quarter.end - timedelta(days=1)).date().isoformat(),
            "timezone": "UTC",
        },
        "generated_at": current.isoformat(),
        "stale_after_days": STALE_AFTER_DAYS,
        "review_policy": {
            "read_only": True,
            "automatic_demotion": False,
            "quarterly_attestation": True,
            "requires_confirmation": True,
            "requires_reason": True,
            "minimum_note_length": MIN_NOTE_LENGTH,
            "role_change_detection": "snapshot_hash_and_roster",
            "attestation_store": "admin_audit_log",
            "attestation_retention": "append-only admin audit retention",
        },
        "summary": summary,
        "flags": _flag_rows(accounts),
        "accounts": accounts,
        "snapshot_hash": snapshot_hash,
        "attestation": {
            "quarter": quarter.label,
            "required": True,
            "current": latest is not None,
            "latest": latest_summary,
            "roster_changed_since_attestation": bool(
                latest_summary and latest_summary.get("snapshot_hash") != snapshot_hash
            ),
            "history": [_attestation_summary(row) for row in history],
        },
        "privacy": {
            "admin_only": True,
            "read_only": True,
            "scope": "admin_and_support_accounts_only",
            "minimum_user_suppression": False,
            "suppression_exception": (
                "A privileged-access inventory must enumerate every admin and "
                "support account; hiding a small roster would defeat the review."
            ),
            "per_user_histories": False,
            "fields_read": [
                "users.id",
                "users.email (masked in responses)",
                "users.name (masked in responses)",
                "users.role",
                "users.two_factor_enabled",
                "users.created_at",
                'session."userId"',
                'session."createdAt"',
                'session."updatedAt"',
                'session."expiresAt"',
                'passkey."userId" (count only)',
            ],
            "fields_excluded": [
                "session tokens",
                "session IP addresses",
                "session user agents",
                "TOTP secrets and backup codes",
                "passkey public keys and credential ids",
                "raw email addresses",
                "provider payloads",
                "per-account activity histories",
            ],
        },
        "notes": [
            "Last login is the newest Better Auth session creation time; tokens, IP addresses and user agents are never read.",
            "Account age uses users.created_at; stale accounts have no login or session activity inside the review window and never-used accounts have no recorded session.",
            "Passkeys count as strong authentication but not as TOTP two-factor authentication; both states are shown.",
            "The review never changes roles, sessions, credentials or entitlements and never demotes an account automatically.",
            "Attestations are append-only admin audit records bound to the reviewed snapshot hash.",
        ],
    }


def to_csv(snapshot: Mapping[str, Any]) -> str:
    """Render the reviewed roster as formula-safe, secret-free CSV."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    quarter = snapshot.get("quarter")
    generated_at = snapshot.get("generated_at")
    for account in snapshot.get("accounts", []):
        writer.writerow(
            [
                _safe_csv_cell(quarter),
                _safe_csv_cell(account.get("user_id")),
                _safe_csv_cell(account.get("email_masked")),
                _safe_csv_cell(account.get("name_masked")),
                _safe_csv_cell(account.get("role")),
                _safe_csv_cell(bool(account.get("two_factor_enabled"))),
                _safe_csv_cell(account.get("passkey_count")),
                _safe_csv_cell(bool(account.get("strong_auth"))),
                _safe_csv_cell(account.get("last_login_at")),
                _safe_csv_cell(account.get("last_activity_at")),
                _safe_csv_cell(account.get("active_sessions")),
                _safe_csv_cell(account.get("session_count")),
                _safe_csv_cell(account.get("account_age_days")),
                _safe_csv_cell(bool(account.get("stale"))),
                _safe_csv_cell(bool(account.get("never_used"))),
                _safe_csv_cell(bool(account.get("missing_two_factor"))),
                _safe_csv_cell(bool(account.get("missing_strong_auth"))),
                _safe_csv_cell(";".join(account.get("flags") or [])),
                _safe_csv_cell(generated_at),
            ]
        )
    return buffer.getvalue()


def _expected_roster(
    expected_accounts: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    expected: dict[str, str] = {}
    for item in expected_accounts:
        user_id = str(item.get("user_id") or "").strip()
        role = str(item.get("role") or "").strip()
        if not user_id or role not in REVIEW_ROLES:
            raise ValueError("expected_accounts contains an invalid user_id or role")
        try:
            normalized = str(uuid.UUID(user_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("expected_accounts contains a non-UUID user_id") from exc
        if normalized in expected:
            raise ValueError("expected_accounts contains a duplicate user_id")
        expected[normalized] = role
    if len(expected) > MAX_EXPECTED_ACCOUNTS:
        raise ValueError(f"expected_accounts exceeds {MAX_EXPECTED_ACCOUNTS} entries")
    return expected


def _roster_conflicts(
    expected: Mapping[str, str],
    accounts: Sequence[Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    current = {str(account["user_id"]): str(account["role"]) for account in accounts}
    role_changes = [
        {
            "user_id": user_id,
            "expected_role": expected[user_id],
            "current_role": current[user_id],
        }
        for user_id in sorted(expected)
        if user_id in current and current[user_id] != expected[user_id]
    ]
    removed = [
        {"user_id": user_id, "expected_role": expected[user_id]}
        for user_id in sorted(expected)
        if user_id not in current
    ]
    added = [
        {"user_id": user_id, "current_role": current[user_id]} for user_id in sorted(current) if user_id not in expected
    ]
    if not role_changes and not removed and not added:
        return None
    total = len(role_changes) + len(removed) + len(added)
    return {
        "role_changes": role_changes[:MAX_CONFLICT_ITEMS],
        "removed": removed[:MAX_CONFLICT_ITEMS],
        "added": added[:MAX_CONFLICT_ITEMS],
        "truncated": total > MAX_CONFLICT_ITEMS * 3,
        "total_conflicts": total,
    }


async def _find_idempotent_attestation(
    db: AsyncSession,
    *,
    actor: AdminActor,
    idempotency_key: str,
    quarter: Quarter,
) -> Optional[AdminAuditLog]:
    statement = (
        select(AdminAuditLog)
        .where(
            AdminAuditLog.actor_user_id == actor.user_id,
            AdminAuditLog.action == AUDIT_ACTION,
            AdminAuditLog.target_type == AUDIT_TARGET_TYPE,
            AdminAuditLog.event_metadata["idempotency_key"].astext == idempotency_key,
        )
        .order_by(AdminAuditLog.created_at.desc())
        .limit(1)
    )
    row = (await db.execute(statement)).scalar_one_or_none()
    if row is not None and row.target_id != quarter.label:
        raise AccessReviewConflict(
            "idempotency_key_reused",
            "This idempotency key was already used for a different quarter.",
            details={"existing_quarter": row.target_id, "quarter": quarter.label},
        )
    return row


async def record_access_review_attestation(
    db: AsyncSession,
    *,
    actor: AdminActor,
    quarter_label: str,
    expected_snapshot_hash: str,
    expected_accounts: Optional[Sequence[Mapping[str, Any]]],
    decision: str,
    note: str,
    confirm: bool,
    idempotency_key: Optional[str] = None,
    request=None,
) -> dict[str, Any]:
    """Append one quarterly attestation after verifying the reviewed snapshot.

    Raises :class:`AccessReviewConflict` (HTTP 409) when the roster or security
    posture changed since the client loaded the review. Nothing is written in
    that case, and no account is demoted or modified on success either.
    """
    if confirm is not True:
        raise AccessReviewConflict(
            "confirmation_required",
            "Attestation requires confirm=true.",
            status_code=422,
        )
    if decision not in ATTESTATION_DECISIONS:
        raise ValueError(f"decision must be one of {ATTESTATION_DECISIONS}")
    cleaned_note = " ".join(str(note or "").split())
    if len(cleaned_note) < MIN_NOTE_LENGTH:
        raise ValueError(f"note must contain at least {MIN_NOTE_LENGTH} characters of review rationale")
    if len(cleaned_note) > MAX_NOTE_LENGTH:
        raise ValueError(f"note must not exceed {MAX_NOTE_LENGTH} characters")
    idempotency_key = (idempotency_key or "").strip() or None
    if idempotency_key and len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ValueError(f"idempotency_key must not exceed {MAX_IDEMPOTENCY_KEY_LENGTH} characters")
    expected = _expected_roster(expected_accounts) if expected_accounts is not None else None

    now = datetime.now(timezone.utc)
    quarter = _quarter_for(now)
    if quarter_label != quarter.label:
        raise AccessReviewConflict(
            "quarter_changed",
            f"The review quarter changed; the current quarter is {quarter.label}.",
            details={"quarter": quarter.label, "submitted_quarter": quarter_label},
        )

    # Serialize duplicate submissions for one actor/key (and any future
    # concurrent attestations) before reading or appending the audit record.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": ATTESTATION_LOCK_ID},
    )

    if idempotency_key:
        existing = await _find_idempotent_attestation(
            db,
            actor=actor,
            idempotency_key=idempotency_key,
            quarter=quarter,
        )
        if existing is not None:
            return {
                "quarter": quarter.label,
                "duplicate": True,
                "automatic_demotion": False,
                "attestation": _attestation_summary(existing),
            }

    snapshot = await access_review_snapshot(db, now=now)
    # A clock tick across a quarter boundary is effectively impossible here,
    # but keep the quarter label and snapshot consistent if it happens.
    if snapshot["quarter"] != quarter.label:
        raise AccessReviewConflict(
            "quarter_changed",
            f"The review quarter changed; the current quarter is {snapshot['quarter']}.",
            details={"quarter": snapshot["quarter"], "submitted_quarter": quarter_label},
        )

    conflicts = _roster_conflicts(expected, snapshot["accounts"]) if expected is not None else None
    if conflicts is not None:
        raise AccessReviewConflict(
            "roster_changed",
            "The privileged roster changed after this review was loaded; reload and review the current accounts.",
            details={
                **conflicts,
                "loaded_snapshot_hash": expected_snapshot_hash,
                "current_snapshot_hash": snapshot["snapshot_hash"],
            },
        )

    if expected_snapshot_hash != snapshot["snapshot_hash"]:
        raise AccessReviewConflict(
            "roster_changed" if expected is None else "review_changed",
            (
                "The reviewed snapshot changed after it was loaded; reload and review the current privileged accounts."
                if expected is None
                else "Two-factor or passkey posture changed after this review was loaded; reload and review the current accounts."
            ),
            details={
                "loaded_snapshot_hash": expected_snapshot_hash,
                "current_snapshot_hash": snapshot["snapshot_hash"],
            },
        )

    summary = snapshot["summary"]
    metadata: dict[str, Any] = {
        "quarter": quarter.label,
        "decision": decision,
        "snapshot_hash": snapshot["snapshot_hash"],
        "expected_snapshot_hash": expected_snapshot_hash,
        "roster_size": summary["total"],
        "admins": summary["admins"],
        "support": summary["support"],
        "admins_without_2fa": summary["admins_without_2fa"],
        "support_without_2fa": summary["support_without_2fa"],
        "stale": summary["stale"],
        "never_used": summary["never_used"],
        "active_sessions": summary["active_sessions"],
        "automatic_demotion": False,
        "read_only": True,
    }
    if idempotency_key:
        metadata["idempotency_key"] = idempotency_key

    row = await record_admin_audit(
        db,
        actor=actor,
        action=AUDIT_ACTION,
        target_type=AUDIT_TARGET_TYPE,
        target_id=quarter.label,
        reason=cleaned_note,
        before={"snapshot_hash": expected_snapshot_hash},
        after={
            "snapshot_hash": snapshot["snapshot_hash"],
            "decision": decision,
        },
        metadata=metadata,
        request=request,
        commit=True,
    )
    return {
        "quarter": quarter.label,
        "duplicate": False,
        "automatic_demotion": False,
        "attestation": _attestation_summary(row),
    }


__all__ = [
    "AccessReviewConflict",
    "CSV_COLUMNS",
    "HISTORY_LIMIT",
    "MAX_EXPECTED_ACCOUNTS",
    "MIN_NOTE_LENGTH",
    "STALE_AFTER_DAYS",
    "access_review_snapshot",
    "record_access_review_attestation",
    "to_csv",
]
