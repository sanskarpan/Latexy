"""Admin trial health: aggregation, suppression, privacy and bounds (issue #2067)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import trial_health_service
from app.services.trial_health_service import (
    MAX_REJECTION_REASONS,
    MIN_COHORT_SIZE,
    REPEAT_DEVICE_BUCKETS,
    USAGE_BUCKETS,
    AttributionSignalRow,
    DeepAnalysisSignalRow,
    TrialSignalRow,
    build_snapshot,
)

PREFIX = "test_th_"
USER_EMAIL_PREFIX = "test_th_%@example.com"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    token = f"test_sess_th_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Trial Health User', :role, true, 'free', 'active', false)"
        ),
        {
            "id": user_id,
            "email": f"test_th_{user_id.replace('-', '')}@example.com",
            "role": role,
        },
    )
    await db.execute(
        text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": _now() + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return user_id, {"Authorization": f"Bearer {token}"}


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    _user_id, headers = await _create_user(db, role="admin")
    return headers


async def _clean_trial_health_rows(db: AsyncSession) -> None:
    await db.execute(
        text(
            "DELETE FROM trial_attributions WHERE trial_id IN ("
            "SELECT id FROM device_trials WHERE device_fingerprint LIKE :prefix)"
        ),
        {"prefix": f"{PREFIX}%"},
    )
    await db.execute(
        text("DELETE FROM device_trials WHERE device_fingerprint LIKE :prefix"),
        {"prefix": f"{PREFIX}%"},
    )
    await db.execute(
        text("DELETE FROM deep_analysis_trials WHERE device_fingerprint LIKE :prefix"),
        {"prefix": f"{PREFIX}%"},
    )
    await db.execute(
        text('DELETE FROM session WHERE "userId" IN (SELECT id::text FROM users WHERE email LIKE :email)'),
        {"email": USER_EMAIL_PREFIX},
    )
    await db.execute(
        text("DELETE FROM users WHERE email LIKE :email"),
        {"email": USER_EMAIL_PREFIX},
    )
    await db.commit()


@pytest.fixture(autouse=True)
async def _clean_trial_health(db_session: AsyncSession):
    await _clean_trial_health_rows(db_session)
    yield
    await _clean_trial_health_rows(db_session)


async def _seed_trial(
    db: AsyncSession,
    *,
    fingerprint: str,
    created_at: datetime,
    usage_count: int = 1,
    blocked: bool = False,
    ip_address: str | None = None,
) -> str:
    trial_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO device_trials "
            "(id, device_fingerprint, ip_address, usage_count, blocked, last_used, created_at) "
            "VALUES (:id, :fp, CAST(:ip AS inet), :usage, :blocked, :created, :created)"
        ),
        {
            "id": trial_id,
            "fp": fingerprint,
            "ip": ip_address,
            "usage": usage_count,
            "blocked": blocked,
            "created": created_at,
        },
    )
    await db.commit()
    return trial_id


async def _seed_deep_trial(
    db: AsyncSession,
    *,
    fingerprint: str,
    usage_count: int,
    last_used: datetime,
) -> None:
    await db.execute(
        text(
            "INSERT INTO deep_analysis_trials "
            "(id, device_fingerprint, usage_count, last_used) "
            "VALUES (:id, :fp, :usage, :last_used)"
        ),
        {
            "id": str(uuid.uuid4()),
            "fp": fingerprint,
            "usage": usage_count,
            "last_used": last_used,
        },
    )
    await db.commit()


async def _seed_attribution(
    db: AsyncSession,
    *,
    trial_id: str,
    user_id: str,
    trial_started_at: datetime,
    paid: bool,
) -> None:
    await db.execute(
        text(
            "INSERT INTO trial_attributions "
            "(id, trial_id, user_id, consent_granted, trial_started_at, "
            "signup_at, paid_at, created_at, updated_at) "
            "VALUES (:id, :trial_id, :uid, true, :started, :started, :paid_at, :started, :started)"
        ),
        {
            "id": str(uuid.uuid4()),
            "trial_id": trial_id,
            "uid": user_id,
            "started": trial_started_at,
            "paid_at": trial_started_at + timedelta(days=1) if paid else None,
        },
    )
    await db.commit()


def _signal_row(
    index: int,
    *,
    usage_count: int = 1,
    blocked: bool = False,
    ip_key: str | None = None,
    created_at: datetime | None = None,
) -> TrialSignalRow:
    return TrialSignalRow(
        device_key=f"device-key-{index}",
        ip_key=ip_key,
        usage_count=usage_count,
        blocked=blocked,
        created_at=created_at or (_now() - timedelta(hours=1)),
    )


def _bucket(distribution: dict, label: str) -> dict:
    return next(item for item in distribution["buckets"] if item["label"] == label)


def _reason(window: dict, key: str) -> dict:
    return next(item for item in window["rejection_reasons"]["items"] if item["key"] == key)


def test_usage_histogram_is_bounded_and_suppresses_small_buckets():
    distribution = trial_health_service.build_usage_distribution([1, 1, 1, 1, 1, 1, 8, 8])
    assert distribution["hidden"] is False
    assert _bucket(distribution, "1")["devices"] == 6
    assert _bucket(distribution, "6-10")["devices"] is None
    assert _bucket(distribution, "6-10")["suppressed"] is True
    assert distribution["suppressed_buckets"] == 1
    assert len(distribution["buckets"]) == len(USAGE_BUCKETS)


def test_usage_histogram_hides_nonzero_buckets_for_a_tiny_window():
    distribution = trial_health_service.build_usage_distribution([8, 8, 8])
    assert distribution["hidden"] is True
    bucket = _bucket(distribution, "6-10")
    assert bucket["devices"] is None
    assert bucket["suppressed"] is True
    assert distribution["suppressed_buckets"] == 1


def test_repeat_device_distribution_uses_hashed_ip_clusters():
    visible = trial_health_service.build_repeat_distribution(
        {
            "ip-a": 5,
            "ip-b": 5,
            "ip-c": 5,
            "ip-d": 5,
            "ip-e": 5,
        },
        devices_with_ip=25,
        total_devices=25,
    )
    assert visible["hidden"] is False
    assert visible["clusters"] == 5
    assert visible["repeat_clusters"] == 5
    assert visible["abuse_clusters"] == 5
    assert _bucket(visible, "5-9 devices")["clusters"] == 5
    assert len(visible["buckets"]) == len(REPEAT_DEVICE_BUCKETS)

    tiny = trial_health_service.build_repeat_distribution(
        {"ip-a": 2, "ip-b": 2, "ip-c": 1},
        devices_with_ip=5,
        total_devices=6,
    )
    assert tiny["hidden"] is True
    assert tiny["clusters"] is None
    assert tiny["repeat_clusters"] is None
    assert tiny["devices_without_ip"] == 1


def test_conversion_and_reasons_apply_min_cohort_suppression():
    now = _now()
    rows = [_signal_row(index, blocked=index < 3, created_at=now - timedelta(hours=1)) for index in range(6)]
    attribution_rows = [
        AttributionSignalRow(
            device_key=f"device-key-{index}",
            trial_created_at=now - timedelta(hours=1),
            user_linked=True,
            paid=index == 0,
        )
        for index in range(3)
    ]
    snapshot = build_snapshot(
        rows=rows,
        deep_rows=[],
        attribution_rows=attribution_rows,
        now=now,
    )
    window = snapshot["windows"][0]
    assert window["days"] == 7
    assert window["conversion"]["attributed_trials"] is None
    assert window["conversion"]["paid_trials"] is None
    assert window["conversion"]["suppressed"] is True
    blocked = _reason(window, "blocked_device")
    assert blocked["devices"] is None
    assert blocked["suppressed"] is True
    assert window["rejection_reasons"]["overlap"] is True


def test_empty_snapshot_has_three_windows_and_zeroed_distributions():
    snapshot = build_snapshot(
        rows=[],
        deep_rows=[],
        attribution_rows=[],
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert snapshot["windows_days"] == [7, 30, 90]
    for window in snapshot["windows"]:
        assert window["trial_starts"] == 0
        assert window["unique_devices"] == 0
        assert window["blocked_devices"] == 0
        assert window["usage_distribution"]["hidden"] is False
        assert all(bucket["devices"] == 0 for bucket in window["usage_distribution"]["buckets"])
        assert window["repeat_device_distribution"]["clusters"] == 0
        assert window["conversion"]["attributed_trials"] == 0
        assert window["conversion"]["paid_trials"] == 0
        assert len(window["rejection_reasons"]["items"]) <= MAX_REJECTION_REASONS
    assert snapshot["reconciliation"]["trial_starts_90d"] == 0
    assert snapshot["reconciliation"]["window_sum_equals_90d"] is True


def test_high_cardinality_snapshot_keeps_buckets_and_payload_bounded():
    now = _now()
    rows = [_signal_row(index, created_at=now - timedelta(hours=1)) for index in range(10_000)]
    rows = [
        TrialSignalRow(
            device_key=row.device_key,
            ip_key=f"ip-key-{index}",
            usage_count=row.usage_count,
            blocked=row.blocked,
            created_at=row.created_at,
        )
        for index, row in enumerate(rows)
    ]
    snapshot = build_snapshot(
        rows=rows,
        deep_rows=[
            DeepAnalysisSignalRow(
                device_key=f"device-key-{index}",
                usage_count=2,
                last_used=now - timedelta(hours=1),
            )
            for index in range(5)
        ],
        attribution_rows=[],
        now=now,
    )
    window = snapshot["windows"][0]
    assert window["trial_starts"] == 10_000
    assert len(window["usage_distribution"]["buckets"]) == len(USAGE_BUCKETS)
    assert len(window["repeat_device_distribution"]["buckets"]) == len(REPEAT_DEVICE_BUCKETS)
    assert len(window["rejection_reasons"]["items"]) <= MAX_REJECTION_REASONS
    payload = json.dumps(snapshot)
    assert "device-key-" not in payload
    assert "ip-key-" not in payload
    assert "device_key" not in payload
    assert "ip_key" not in payload


class TestTrialHealthEndpoint:
    async def test_admin_only_access(self, client: AsyncClient, db_session: AsyncSession):
        _user_id, user_headers = await _create_user(db_session, role="user")
        denied = await client.get("/admin/analytics/trial-health", headers=user_headers)
        assert denied.status_code == 403

        _support_id, support_headers = await _create_user(db_session, role="support")
        support_denied = await client.get("/admin/analytics/trial-health", headers=support_headers)
        assert support_denied.status_code == 403

        anonymous = await client.get("/admin/analytics/trial-health")
        assert anonymous.status_code == 401

        admin = await _admin_headers(db_session)
        allowed = await client.get("/admin/analytics/trial-health", headers=admin)
        assert allowed.status_code == 200, allowed.text

    async def test_aggregates_reconcile_and_never_return_raw_keys(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        caplog: pytest.LogCaptureFixture,
    ):
        admin = await _admin_headers(db_session)
        baseline_response = await client.get("/admin/analytics/trial-health", headers=admin)
        assert baseline_response.status_code == 200
        baseline = baseline_response.json()

        now = _now()
        raw_fingerprints: list[str] = []
        raw_ips: list[str] = []
        trial_ids: list[str] = []

        # Five hashed-IP clusters of five devices in the last seven days, so the
        # repeat-device and abuse-cluster buckets are publishable.
        for cluster in range(5):
            ip_address = f"198.51.100.{10 + cluster}"
            raw_ips.append(ip_address)
            for member in range(5):
                fingerprint = f"{PREFIX}fp_{cluster}_{member}_{uuid.uuid4().hex}"
                raw_fingerprints.append(fingerprint)
                trial_ids.append(
                    await _seed_trial(
                        db_session,
                        fingerprint=fingerprint,
                        usage_count=1,
                        created_at=now - timedelta(hours=6),
                        ip_address=ip_address,
                    )
                )

        for index in range(2):
            fingerprint = f"{PREFIX}fp_usage2_{index}_{uuid.uuid4().hex}"
            raw_fingerprints.append(fingerprint)
            await _seed_trial(
                db_session,
                fingerprint=fingerprint,
                usage_count=2,
                created_at=now - timedelta(hours=5),
                ip_address=f"198.51.100.{30 + index}",
            )
        for index in range(5):
            fingerprint = f"{PREFIX}fp_blocked_{index}_{uuid.uuid4().hex}"
            raw_fingerprints.append(fingerprint)
            await _seed_trial(
                db_session,
                fingerprint=fingerprint,
                usage_count=3,
                blocked=True,
                created_at=now - timedelta(hours=4),
                ip_address=f"198.51.100.{40 + index}",
            )
        fingerprint = f"{PREFIX}fp_zero_{uuid.uuid4().hex}"
        raw_fingerprints.append(fingerprint)
        await _seed_trial(
            db_session,
            fingerprint=fingerprint,
            usage_count=0,
            created_at=now - timedelta(hours=3),
            ip_address="198.51.100.50",
        )

        for index in range(5):
            fingerprint = f"{PREFIX}fp_30d_{index}_{uuid.uuid4().hex}"
            raw_fingerprints.append(fingerprint)
            await _seed_trial(
                db_session,
                fingerprint=fingerprint,
                created_at=now - timedelta(days=20),
                ip_address=f"198.51.100.{60 + index}",
            )
        for index in range(4):
            fingerprint = f"{PREFIX}fp_90d_{index}_{uuid.uuid4().hex}"
            raw_fingerprints.append(fingerprint)
            await _seed_trial(
                db_session,
                fingerprint=fingerprint,
                created_at=now - timedelta(days=60),
                ip_address=f"198.51.100.{70 + index}",
            )

        for trial_index in range(6):
            user_id, _headers = await _create_user(db_session)
            await _seed_attribution(
                db_session,
                trial_id=trial_ids[trial_index],
                user_id=user_id,
                trial_started_at=now - timedelta(hours=6),
                paid=trial_index < 5,
            )

        for index in range(5):
            await _seed_deep_trial(
                db_session,
                fingerprint=raw_fingerprints[index * 5],
                usage_count=2,
                last_used=now - timedelta(hours=2),
            )

        caplog.clear()
        response = await client.get("/admin/analytics/trial-health", headers=admin)
        assert response.status_code == 200, response.text
        body = response.json()
        by_days = {window["days"]: window for window in body["windows"]}
        baseline_by_days = {window["days"]: window for window in baseline["windows"]}

        expected = {7: 33, 30: 38, 90: 42}
        for days, expected_starts in expected.items():
            window = by_days[days]
            before = baseline_by_days[days]
            assert window["trial_starts"] - before["trial_starts"] == expected_starts
            assert window["unique_devices"] - before["unique_devices"] == expected_starts
            assert window["blocked_devices"] - before["blocked_devices"] == 5
            assert (
                window["usage_distribution"]["total_devices"] - before["usage_distribution"]["total_devices"]
                == expected_starts
            )

        seven = by_days[7]
        assert _reason(seven, "repeat_device_cluster")["devices"] >= 25
        assert _reason(seven, "deep_analysis_limit_reached")["devices"] >= 5
        assert _reason(seven, "blocked_device")["devices"] >= 5
        assert seven["conversion"]["attributed_trials"] >= 6
        assert seven["conversion"]["paid_trials"] >= 5
        assert seven["conversion"]["trial_to_paid_pct"] is not None

        reconciliation = body["reconciliation"]
        assert reconciliation["window_sum_equals_90d"] is True
        assert (
            reconciliation["trial_starts_7d"]
            + reconciliation["trial_starts_8_to_30d"]
            + reconciliation["trial_starts_31_to_90d"]
            == reconciliation["trial_starts_90d"]
        )
        assert reconciliation["scanned_rows"] >= 39
        assert reconciliation["rows_truncated"] is False

        payload = response.text
        for raw_value in raw_fingerprints + raw_ips:
            assert raw_value not in payload
            assert raw_value not in caplog.text
        assert "device_fingerprint" not in payload
        assert "ip_address" not in payload

    async def test_scan_is_capped_for_high_cardinality(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        now = _now()
        for index in range(6):
            await _seed_trial(
                db_session,
                fingerprint=f"{PREFIX}cap_{index}_{uuid.uuid4().hex}",
                created_at=now - timedelta(hours=1),
                ip_address=f"198.51.100.{90 + index}",
            )
        monkeypatch.setattr(trial_health_service, "MAX_SCANNED_ROWS", 5)
        snapshot = await trial_health_service.snapshot(db_session)
        assert snapshot["reconciliation"]["rows_truncated"] is True
        assert snapshot["reconciliation"]["scanned_rows"] <= 5
        assert len(USAGE_BUCKETS) == len(snapshot["windows"][0]["usage_distribution"]["buckets"])
        assert MIN_COHORT_SIZE == snapshot["minimum_cohort_size"]
