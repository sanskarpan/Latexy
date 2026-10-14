"""Disabled PostgreSQL quota ledger for a future, reconciled cutover.

No API or worker calls this module. The caller owns and commits the transaction;
an uncommitted return value grants no right to dispatch work. After an uncertain
commit, read the same reservation ID in a fresh transaction before retrying.
Opening balances require a fenced legacy source and independently reviewed
evidence; this module cannot manufacture a balance from an unavailable Redis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import BigInteger, Column, DateTime, MetaData, String, Table, func, insert, select, update


class QuotaBalanceUnknown(RuntimeError):
    """The existing balance has not been reconciled; admission is closed."""


class QuotaReplayConflict(RuntimeError):
    """A reservation ID was reused with different immutable inputs."""


class QuotaReservationUnknown(RuntimeError):
    """A refund has no confirmed reservation to compensate."""


class QuotaLedgerInvariantError(RuntimeError):
    """The persisted ledger is inconsistent; admission is closed."""


@dataclass(frozen=True)
class QuotaDecision:
    reservation_id: str
    state: str
    used_after: int
    allowed: bool


class _Session(Protocol):
    async def execute(self, statement: object): ...


_metadata = MetaData()
_accounts = Table(
    "quota_ledger_accounts", _metadata,
    Column("user_id", String(36), primary_key=True),
    Column("dimension", String(64), primary_key=True),
    Column("period", String(8), primary_key=True),
    Column("status", String(16)),
    Column("used", BigInteger),
    Column("opening_used", BigInteger),
    Column("source_ref", String(255)),
    Column("source_sha256", String(64)),
    Column("reconciled_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
_reservations = Table(
    "quota_ledger_reservations", _metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36)),
    Column("dimension", String(64)),
    Column("period", String(8)),
    Column("cost", BigInteger),
    Column("limit_value", BigInteger),
    Column("state", String(16)),
    Column("used_after", BigInteger),
    Column("refunded_at", DateTime(timezone=True)),
)


def _identity(user_id: str, dimension: str, period: str) -> dict[str, str]:
    if not isinstance(user_id, str) or not user_id or len(user_id) > 36:
        raise ValueError("invalid user_id")
    if not isinstance(dimension, str) or not dimension or len(dimension) > 64:
        raise ValueError("invalid quota dimension")
    if not isinstance(period, str) or not re.fullmatch(r"\d{6}(?:\d{2})?", period):
        raise ValueError("invalid quota period")
    return {"user_id": user_id, "dimension": dimension, "period": period}


def _account_where(identity: dict[str, str]):
    return (
        (_accounts.c.user_id == identity["user_id"])
        & (_accounts.c.dimension == identity["dimension"])
        & (_accounts.c.period == identity["period"])
    )


async def stage_unknown_account(session: _Session, *, user_id: str, dimension: str, period: str) -> None:
    """Stage an account with no assumed balance; duplicate staging must fail."""
    identity = _identity(user_id, dimension, period)
    await session.execute(insert(_accounts).values(**identity, status="unknown"))


async def record_reconciled_opening(
    session: _Session, *, user_id: str, dimension: str, period: str,
    opening_used: int, source_ref: str, source_sha256: str,
) -> None:
    """Record operator-verified opening usage after all legacy writes are fenced.

    A digest and opaque reference are provenance fields, not automatic proof.
    The migration runbook must verify both balances and outstanding receipts.
    """
    identity = _identity(user_id, dimension, period)
    if isinstance(opening_used, bool) or not isinstance(opening_used, int) or opening_used < 0:
        raise ValueError("invalid opening usage")
    if not isinstance(source_ref, str) or not source_ref.strip() or len(source_ref) > 255:
        raise ValueError("invalid evidence reference")
    if not isinstance(source_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ValueError("invalid evidence digest")
    row = (await session.execute(
        select(_accounts).where(_account_where(identity)).with_for_update()
    )).mappings().first()
    if row is None or row["status"] != "unknown":
        raise QuotaBalanceUnknown("account is missing or already reconciled")
    await session.execute(
        update(_accounts).where(_account_where(identity)).values(
            status="reconciled", used=opening_used, opening_used=opening_used,
            source_ref=source_ref, source_sha256=source_sha256,
            reconciled_at=func.now(),
            updated_at=func.now(),
        )
    )


def _validated_reservation_id(reservation_id: UUID) -> str:
    if not isinstance(reservation_id, UUID):
        raise ValueError("reservation_id must be a UUID")
    return str(reservation_id)


def _decision(row) -> QuotaDecision:
    state = row["state"]
    if state not in {"allowed", "denied", "refunded"} or row["used_after"] < 0:
        raise QuotaLedgerInvariantError("reservation state is incompatible")
    return QuotaDecision(row["id"], state, row["used_after"], state == "allowed")


async def read_quota_reservation(session: _Session, reservation_id: UUID) -> QuotaDecision | None:
    """Resolve an ambiguous commit by ID, using a fresh primary DB transaction."""
    key = _validated_reservation_id(reservation_id)
    row = (await session.execute(
        select(_reservations).where(_reservations.c.id == key)
    )).mappings().first()
    return _decision(row) if row is not None else None


async def reserve_quota(
    session: _Session, *, reservation_id: UUID, user_id: str, dimension: str,
    period: str, cost: int, limit: int | None,
) -> QuotaDecision:
    """Debit once under the account row lock; denied attempts are also sticky."""
    key = _validated_reservation_id(reservation_id)
    identity = _identity(user_id, dimension, period)
    if isinstance(cost, bool) or not isinstance(cost, int) or cost < 1:
        raise ValueError("cost must be positive")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
        raise ValueError("limit must be nonnegative or unlimited")

    account = (await session.execute(
        select(_accounts).where(_account_where(identity)).with_for_update()
    )).mappings().first()
    if account is None or account["status"] != "reconciled" or account["used"] is None:
        raise QuotaBalanceUnknown("quota balance is missing or unreconciled")
    used = account["used"]
    if used < 0:
        raise QuotaLedgerInvariantError("negative quota balance")

    prior = (await session.execute(
        select(_reservations).where(_reservations.c.id == key)
    )).mappings().first()
    if prior is not None:
        if any(prior[name] != value for name, value in {
            "user_id": user_id, "dimension": dimension, "period": period,
            "cost": cost, "limit_value": limit,
        }.items()):
            raise QuotaReplayConflict("reservation ID has different inputs")
        return _decision(prior)

    allowed = limit is None or used + cost <= limit
    new_used = used + cost if allowed else used
    await session.execute(insert(_reservations).values(
        id=key, **identity, cost=cost, limit_value=limit,
        state="allowed" if allowed else "denied", used_after=new_used,
    ))
    if allowed:
        await session.execute(update(_accounts).where(_account_where(identity)).values(
            used=new_used, updated_at=func.now(),
        ))
    return QuotaDecision(key, "allowed" if allowed else "denied", new_used, allowed)


async def refund_quota_reservation(session: _Session, reservation_id: UUID) -> bool:
    """Refund the exact original cost once; a missing receipt never refunds."""
    key = _validated_reservation_id(reservation_id)
    receipt = (await session.execute(
        select(_reservations).where(_reservations.c.id == key)
    )).mappings().first()
    if receipt is None:
        raise QuotaReservationUnknown("reservation is missing")
    identity = {name: receipt[name] for name in ("user_id", "dimension", "period")}
    account = (await session.execute(
        select(_accounts).where(_account_where(identity)).with_for_update()
    )).mappings().first()
    if account is None or account["status"] != "reconciled" or account["used"] is None:
        raise QuotaBalanceUnknown("quota balance is missing or unreconciled")
    receipt = (await session.execute(
        select(_reservations).where(_reservations.c.id == key)
    )).mappings().first()
    if receipt is None:
        raise QuotaReservationUnknown("reservation disappeared")
    if receipt["state"] in {"denied", "refunded"}:
        return False
    if receipt["state"] != "allowed" or account["used"] < receipt["cost"]:
        raise QuotaLedgerInvariantError("refund would corrupt quota balance")
    await session.execute(update(_accounts).where(_account_where(identity)).values(
        used=account["used"] - receipt["cost"],
        updated_at=func.now(),
    ))
    await session.execute(update(_reservations).where(_reservations.c.id == key).values(
        state="refunded", refunded_at=func.now(),
    ))
    return True
