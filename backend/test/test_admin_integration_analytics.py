"""Integration adoption/failure analytics: emission, buckets, suppression, RBAC.

Coverage:
  * connect_started / connected / disconnected / sync_succeeded / sync_failed
    are emitted from every provider route without credentials or payloads;
  * stable error classification never reads a provider response body;
  * provider, plan, OAuth, sync-failure and disconnect buckets aggregate
    correctly and reconcile with token/status columns;
  * five-user suppression hides small provider and plan cohorts;
  * missing-telemetry labels appear when connections exist without events;
  * the admin endpoint is owner/admin-only and aggregate-only;
  * existing tables are reused, so no migration is added.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database import models
from app.services.encryption_service import encryption_service
from app.services.google_drive_service import GOOGLE_DRIVE_SCOPE
from app.services.integration_analytics_service import (
    DISCONNECT_REASONS,
    ERROR_CLASSES,
    INTEGRATION_ACTIONS,
    INTEGRATION_CONNECT_STARTED,
    INTEGRATION_CONNECTED,
    INTEGRATION_DISCONNECTED,
    INTEGRATION_RESOURCE_TYPE,
    INTEGRATION_SYNC_FAILED,
    INTEGRATION_SYNC_SUCCEEDED,
    MIN_GROUP_SIZE,
    PROVIDERS,
    classify_integration_exception,
    normalize_plan,
    record_integration_event,
    snapshot,
)

UTC = timezone.utc
ENDPOINT = "/admin/analytics/integrations"
BACKEND = Path(__file__).resolve().parents[1]
SAMPLE_BIBTEX = """\
@article{smith2020,
  title={Example Article},
  author={Smith, John},
  year={2020},
}

@book{jones2019,
  title={A Great Book},
  author={Jones, Alice},
  year={2019},
}
"""


def _hex() -> str:
    return uuid.uuid4().hex[:10]


def _anchor() -> datetime:
    return datetime(2035, 1, 1, tzinfo=UTC) + timedelta(days=uuid.uuid4().int % 900)


def _set_stream_body(response: MagicMock, body: str) -> None:
    raw = body.encode()
    response.headers = dict(getattr(response, "headers", {}) or {})

    async def aiter_bytes(*, chunk_size: int | None = None):
        del chunk_size
        yield raw

    response.aiter_bytes = aiter_bytes


def _stream_context(response: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


async def _user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
    github: bool = False,
    dropbox: bool = False,
    drive: bool = False,
    zotero: bool = False,
    mendeley: bool = False,
) -> models.User:
    user = models.User(
        id=str(uuid.uuid4()),
        email=f"test_integration_{uuid.uuid4().hex}@example.org",
        name="Integration User",
        role=role,
        email_verified=True,
        subscription_plan=plan,
        subscription_status="active",
        trial_used=False,
        user_metadata={},
        created_at=datetime.now(UTC),
    )
    if github:
        user.github_access_token = encryption_service.encrypt(f"gh_{_hex()}")
        user.github_username = f"gh_{_hex()}"
    if dropbox:
        user.dropbox_access_token = encryption_service.encrypt(f"dbx_{_hex()}")
    if drive:
        user.user_metadata = {
            "google_drive_oauth": {
                "access_token": encryption_service.encrypt(f"gd_{_hex()}"),
                "refresh_token": encryption_service.encrypt(f"gdr_{_hex()}"),
                "scopes": [GOOGLE_DRIVE_SCOPE],
            }
        }
    if zotero:
        user.user_metadata = {
            "zotero_token": encryption_service.encrypt(f"zo_{_hex()}"),
            "zotero_user_id": str(uuid.uuid4().int % 100000),
            "zotero_username": f"zo_{_hex()}",
        }
    if mendeley:
        user.user_metadata = {
            "mendeley_token": encryption_service.encrypt(f"me_{_hex()}"),
            "mendeley_name": f"me_{_hex()}",
        }
    db.add(user)
    await db.commit()
    return user


async def _headers(db: AsyncSession, user: models.User) -> dict[str, str]:
    token = f"test_sess_{uuid.uuid4().hex}"
    await db.execute(
        text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
        {
            "id": str(uuid.uuid4()),
            "uid": str(user.id),
            "exp": datetime.now(UTC) + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _resume(
    db: AsyncSession,
    *,
    user: models.User,
    github_sync: bool = False,
    dropbox_sync: bool = False,
) -> models.Resume:
    resume = models.Resume(
        id=str(uuid.uuid4()),
        user_id=str(user.id),
        title="Integration Resume",
        latex_content="SECRET_LATEX_BODY",
        github_sync_enabled=github_sync,
        github_repo_name="resume-sync" if github_sync else None,
        dropbox_sync_enabled=dropbox_sync,
        dropbox_folder_path="/Latexy/resume.tex" if dropbox_sync else None,
    )
    db.add(resume)
    await db.commit()
    return resume


async def _event(
    db: AsyncSession,
    *,
    user: models.User,
    provider: str,
    action: str,
    created_at: datetime,
    operation: str | None = None,
    error_class: str | None = None,
    reason: str | None = None,
) -> None:
    metadata: dict[str, object] = {
        "provider": provider,
        "plan": normalize_plan(user.subscription_plan),
    }
    if action in (INTEGRATION_SYNC_SUCCEEDED, INTEGRATION_SYNC_FAILED):
        metadata["operation"] = operation or "push"
    if action == INTEGRATION_SYNC_FAILED:
        metadata["error_class"] = error_class or "unknown"
    if action == INTEGRATION_DISCONNECTED:
        metadata["disconnect_reason"] = reason or "user_requested"
    db.add(
        models.UsageAnalytics(
            id=str(uuid.uuid4()),
            user_id=str(user.id),
            device_fingerprint=None,
            action=action,
            resource_type=INTEGRATION_RESOURCE_TYPE,
            event_metadata=metadata,
            ip_address=None,
            user_agent=None,
            created_at=created_at,
        )
    )
    await db.commit()


async def _events_for(
    db: AsyncSession,
    *,
    user: models.User,
    provider: str | None = None,
    action: str | None = None,
) -> list[models.UsageAnalytics]:
    stmt = select(models.UsageAnalytics).where(
        models.UsageAnalytics.user_id == str(user.id),
        models.UsageAnalytics.resource_type == INTEGRATION_RESOURCE_TYPE,
    )
    if provider is not None:
        stmt = stmt.where(models.UsageAnalytics.event_metadata["provider"].as_string() == provider)
    if action is not None:
        stmt = stmt.where(models.UsageAnalytics.action == action)
    return list((await db.execute(stmt)).scalars().all())


def _zotero_client(response: MagicMock) -> MagicMock:
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.stream = MagicMock(return_value=_stream_context(response))
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


class TestEventEmission:
    async def test_connect_started_is_emitted_for_every_provider(self, db_session: AsyncSession) -> None:
        from app.api import dropbox_routes, github_routes, google_drive_routes, mendeley_routes, zotero_routes

        user = await _user(db_session, plan=f"emit{_hex()}")
        uid = str(user.id)

        with (
            patch.object(settings, "GITHUB_CLIENT_ID", "gh-client"),
            patch.object(settings, "GITHUB_CLIENT_SECRET", "gh-secret"),
            patch("app.api.github_routes.cache_manager") as cache,
        ):
            cache.set = AsyncMock()
            await github_routes.github_connect(user_id=uid, db=db_session)

        with (
            patch.object(settings, "DROPBOX_APP_KEY", "dbx-key"),
            patch.object(settings, "DROPBOX_APP_SECRET", "dbx-secret"),
            patch("app.api.dropbox_routes.cache_manager") as cache,
        ):
            cache.set = AsyncMock()
            await dropbox_routes.dropbox_connect(user_id=uid, db=db_session)

        with (
            patch.object(settings, "GOOGLE_DRIVE_CLIENT_ID", "gd-client"),
            patch.object(settings, "GOOGLE_DRIVE_CLIENT_SECRET", "gd-secret"),
            patch.object(settings, "GOOGLE_DRIVE_REDIRECT_URI", "http://localhost/cb"),
            patch("app.api.google_drive_routes.cache_manager") as cache,
        ):
            cache.set = AsyncMock()
            await google_drive_routes.google_drive_connect(user_id=uid, db=db_session)

        request_response = MagicMock()
        request_response.text = "oauth_token=req&oauth_token_secret=sec"
        request_response.raise_for_status = MagicMock()
        with (
            patch.object(settings, "ZOTERO_CLIENT_KEY", "zo-key"),
            patch.object(settings, "ZOTERO_CLIENT_SECRET", "zo-secret"),
            patch.object(settings, "ZOTERO_REDIRECT_URI", "http://localhost/zotero"),
            patch("app.api.zotero_routes.cache_manager") as cache,
            patch(
                "app.api.zotero_routes.guarded_async_client",
                return_value=_zotero_client(request_response),
            ),
        ):
            cache.set = AsyncMock()
            await zotero_routes.zotero_connect(user_id=uid, db=db_session)

        with (
            patch.object(settings, "MENDELEY_CLIENT_ID", "me-client"),
            patch.object(settings, "MENDELEY_CLIENT_SECRET", "me-secret"),
            patch.object(settings, "MENDELEY_REDIRECT_URI", "http://localhost/mendeley"),
            patch("app.api.mendeley_routes.cache_manager") as cache,
        ):
            cache.set = AsyncMock()
            await mendeley_routes.mendeley_connect(user_id=uid, db=db_session)

        rows = await _events_for(db_session, user=user, action=INTEGRATION_CONNECT_STARTED)
        assert {row.event_metadata["provider"] for row in rows} == set(PROVIDERS)
        assert len(rows) == len(PROVIDERS)

    async def test_disconnected_is_emitted_once_per_actual_disconnect(self, db_session: AsyncSession) -> None:
        from app.api import dropbox_routes, github_routes, google_drive_routes, mendeley_routes, zotero_routes

        cases = []
        for provider in PROVIDERS:
            user = await _user(
                db_session,
                plan=f"disc{_hex()}",
                github=provider == "github",
                dropbox=provider == "dropbox",
                drive=provider == "google_drive",
                zotero=provider == "zotero",
                mendeley=provider == "mendeley",
            )
            uid = str(user.id)
            if provider == "github":
                with patch(
                    "app.api.github_routes.github_sync_service.revoke_oauth_grant",
                    AsyncMock(),
                ):
                    await github_routes.github_disconnect(db_session, uid)
            elif provider == "dropbox":
                await dropbox_routes.dropbox_disconnect(db_session, uid)
            elif provider == "google_drive":
                with patch(
                    "app.api.google_drive_routes.google_drive_service.revoke_token",
                    AsyncMock(),
                ):
                    await google_drive_routes.google_drive_disconnect(db_session, uid)
            elif provider == "zotero":
                await zotero_routes.zotero_disconnect(db_session, uid)
            else:
                await mendeley_routes.mendeley_disconnect(db_session, uid)
            cases.append((provider, user))

            # Idempotent second disconnect must not create a second event.
            if provider == "dropbox":
                await dropbox_routes.dropbox_disconnect(db_session, uid)
            elif provider == "zotero":
                await zotero_routes.zotero_disconnect(db_session, uid)
            elif provider == "mendeley":
                await mendeley_routes.mendeley_disconnect(db_session, uid)

        for provider, user in cases:
            rows = await _events_for(
                db_session,
                user=user,
                provider=provider,
                action=INTEGRATION_DISCONNECTED,
            )
            assert len(rows) == 1, provider
            assert rows[0].event_metadata["disconnect_reason"] == "user_requested"

    async def test_sync_success_and_failure_are_bucketed(self, db_session: AsyncSession) -> None:
        from app.api import zotero_routes

        user = await _user(db_session, plan=f"sync{_hex()}", zotero=True)
        resume = await _resume(db_session, user=user)

        success = MagicMock()
        success.status_code = 200
        success.headers = {"Total-Results": "2"}
        success.raise_for_status = MagicMock()
        _set_stream_body(success, SAMPLE_BIBTEX)
        with (
            patch("app.api.zotero_routes.guarded_async_client", return_value=_zotero_client(success)),
        ):
            await zotero_routes.zotero_import(
                zotero_routes.ZoteroImportRequest(resume_id=str(resume.id)),
                db=db_session,
                user_id=str(user.id),
            )

        failure = MagicMock()
        failure.status_code = 500
        failure.headers = {}
        failure.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "SECRET_PROVIDER_ERROR_BODY",
                request=MagicMock(),
                response=failure,
            )
        )
        with (
            patch("app.api.zotero_routes.guarded_async_client", return_value=_zotero_client(failure)),
        ):
            with pytest.raises(HTTPException):
                await zotero_routes.zotero_import(
                    zotero_routes.ZoteroImportRequest(resume_id=str(resume.id)),
                    db=db_session,
                    user_id=str(user.id),
                )

        success_rows = await _events_for(
            db_session,
            user=user,
            provider="zotero",
            action=INTEGRATION_SYNC_SUCCEEDED,
        )
        failure_rows = await _events_for(
            db_session,
            user=user,
            provider="zotero",
            action=INTEGRATION_SYNC_FAILED,
        )
        assert len(success_rows) == 1
        assert success_rows[0].event_metadata["operation"] == "import"
        assert len(failure_rows) == 1
        assert failure_rows[0].event_metadata["operation"] == "import"
        assert failure_rows[0].event_metadata["error_class"] == "provider_unavailable"
        serialized = json.dumps(failure_rows[0].event_metadata)
        assert "SECRET_PROVIDER_ERROR_BODY" not in serialized
        assert "SECRET_LATEX_BODY" not in serialized
        assert set(failure_rows[0].event_metadata) <= {
            "provider",
            "plan",
            "operation",
            "error_class",
        }

    async def test_every_provider_module_wires_connect_and_sync_events(self) -> None:
        modules = (
            "github_routes.py",
            "dropbox_routes.py",
            "google_drive_routes.py",
            "zotero_routes.py",
            "mendeley_routes.py",
        )
        for name in modules:
            source = (BACKEND / "app" / "api" / name).read_text(encoding="utf-8")
            for constant in (
                "INTEGRATION_CONNECT_STARTED",
                "INTEGRATION_CONNECTED",
                "INTEGRATION_DISCONNECTED",
                "INTEGRATION_SYNC_SUCCEEDED",
                "INTEGRATION_SYNC_FAILED",
            ):
                assert constant in source, f"{name} missing {constant}"
            assert "record_integration_event" in source
            assert "classify_integration_exception" in source


class TestPrivacyPayloads:
    async def test_stored_metadata_is_allowlisted(self, db_session: AsyncSession) -> None:
        user = await _user(
            db_session,
            plan=f"pay{_hex()}",
            github=True,
        )
        recorded = await record_integration_event(
            db_session,
            provider="github",
            action=INTEGRATION_SYNC_FAILED,
            user_id=str(user.id),
            plan=user.subscription_plan,
            operation="push",
            error_class="auth",
        )
        assert recorded is True
        rows = await _events_for(db_session, user=user, action=INTEGRATION_SYNC_FAILED)
        assert len(rows) == 1
        row = rows[0]
        assert row.ip_address is None
        assert row.user_agent is None
        assert row.device_fingerprint is None
        assert row.event_metadata == {
            "provider": "github",
            "plan": normalize_plan(user.subscription_plan),
            "operation": "push",
            "error_class": "auth",
        }
        serialized = json.dumps(row.event_metadata)
        for forbidden in ("SECRET", "token", "email", "@", "filename"):
            assert forbidden not in serialized

    async def test_event_recorder_never_accepts_free_form_metadata(self, db_session: AsyncSession) -> None:
        user = await _user(db_session, plan=f"pay2{_hex()}")
        assert (
            await record_integration_event(
                db_session,
                provider="not-a-provider",
                action=INTEGRATION_CONNECTED,
                user_id=str(user.id),
            )
            is False
        )
        assert (
            await record_integration_event(
                db_session,
                provider="github",
                action="user_email_captured",
                user_id=str(user.id),
            )
            is False
        )

    def test_error_classification_does_not_read_response_bodies(self) -> None:
        response = MagicMock()
        response.status_code = 429
        response.text = "SECRET_PROVIDER_BODY"
        exc = httpx.HTTPStatusError("SECRET_PROVIDER_BODY", request=MagicMock(), response=response)
        assert classify_integration_exception(exc) == "rate_limited"
        assert classify_integration_exception(httpx.ConnectError("SECRET")) == "network"
        assert classify_integration_exception(ValueError("SECRET")) == "invalid_response"
        assert classify_integration_exception(HTTPException(status_code=403)) == "permission"
        assert classify_integration_exception(None) == "unknown"
        assert "auth" in ERROR_CLASSES
        assert "user_requested" in DISCONNECT_REASONS
        assert set(INTEGRATION_ACTIONS) == {
            INTEGRATION_CONNECT_STARTED,
            INTEGRATION_CONNECTED,
            INTEGRATION_DISCONNECTED,
            INTEGRATION_SYNC_SUCCEEDED,
            INTEGRATION_SYNC_FAILED,
        }


@pytest.fixture
async def report_seed(db_session: AsyncSession) -> dict[str, object]:
    anchor = _anchor()
    start = anchor.date()
    end = (anchor + timedelta(days=9)).date()
    plan = f"intg{_hex()}"
    admin = await _user(db_session, role="admin", plan="pro")
    normal = await _user(db_session, role="user", plan="pro")

    github_users = [await _user(db_session, plan=plan, github=True) for _ in range(6)]
    dropbox_users = [await _user(db_session, plan=plan, dropbox=True) for _ in range(5)]
    drive_users = [await _user(db_session, plan=plan, drive=True) for _ in range(5)]
    zotero_users = [await _user(db_session, plan=plan, zotero=True) for _ in range(4)]
    mendeley_users = [await _user(db_session, plan=plan, mendeley=True) for _ in range(5)]

    for index, user in enumerate(github_users):
        await _event(
            db_session,
            user=user,
            provider="github",
            action=INTEGRATION_CONNECT_STARTED,
            created_at=anchor + timedelta(hours=1, minutes=index),
        )
        await _event(
            db_session,
            user=user,
            provider="github",
            action=INTEGRATION_CONNECTED,
            created_at=anchor + timedelta(hours=2, minutes=index),
        )
        if index < 8:
            await _event(
                db_session,
                user=user,
                provider="github",
                action=INTEGRATION_SYNC_SUCCEEDED,
                created_at=anchor + timedelta(hours=3, minutes=index),
                operation="push" if index % 2 else "pull",
            )
    await _event(
        db_session,
        user=github_users[0],
        provider="github",
        action=INTEGRATION_DISCONNECTED,
        created_at=anchor + timedelta(hours=4),
        reason="user_requested",
    )
    await _event(
        db_session,
        user=github_users[1],
        provider="github",
        action=INTEGRATION_SYNC_FAILED,
        created_at=anchor + timedelta(hours=5),
        operation="push",
        error_class="provider_unavailable",
    )
    await _event(
        db_session,
        user=github_users[2],
        provider="github",
        action=INTEGRATION_SYNC_FAILED,
        created_at=anchor + timedelta(hours=6),
        operation="pull",
        error_class="auth",
    )
    for index in range(2):
        await _event(
            db_session,
            user=github_users[index],
            provider="github",
            action=INTEGRATION_SYNC_SUCCEEDED,
            created_at=anchor + timedelta(hours=7, minutes=index),
            operation="push",
        )
    for index in range(3):
        await _resume(db_session, user=github_users[index], github_sync=True)

    for index, user in enumerate(dropbox_users):
        await _event(
            db_session,
            user=user,
            provider="dropbox",
            action=INTEGRATION_CONNECT_STARTED,
            created_at=anchor + timedelta(hours=1, minutes=index),
        )
        await _event(
            db_session,
            user=user,
            provider="dropbox",
            action=INTEGRATION_CONNECTED,
            created_at=anchor + timedelta(hours=2, minutes=index),
        )
        await _event(
            db_session,
            user=user,
            provider="dropbox",
            action=INTEGRATION_SYNC_SUCCEEDED,
            created_at=anchor + timedelta(hours=3, minutes=index),
            operation="push",
        )
    for index in range(2):
        await _resume(db_session, user=dropbox_users[index], dropbox_sync=True)

    for index, user in enumerate(drive_users):
        await _event(
            db_session,
            user=user,
            provider="google_drive",
            action=INTEGRATION_CONNECT_STARTED,
            created_at=anchor + timedelta(hours=1, minutes=index),
        )
        if index < 4:
            await _event(
                db_session,
                user=user,
                provider="google_drive",
                action=INTEGRATION_CONNECTED,
                created_at=anchor + timedelta(hours=2, minutes=index),
            )
            await _event(
                db_session,
                user=user,
                provider="google_drive",
                action=INTEGRATION_SYNC_SUCCEEDED,
                created_at=anchor + timedelta(hours=3, minutes=index),
                operation="export",
            )
    await _event(
        db_session,
        user=drive_users[4],
        provider="google_drive",
        action=INTEGRATION_SYNC_FAILED,
        created_at=anchor + timedelta(hours=4),
        operation="export",
        error_class="auth",
    )

    for index, user in enumerate(zotero_users):
        await _event(
            db_session,
            user=user,
            provider="zotero",
            action=INTEGRATION_CONNECT_STARTED,
            created_at=anchor + timedelta(hours=1, minutes=index),
        )
        await _event(
            db_session,
            user=user,
            provider="zotero",
            action=INTEGRATION_CONNECTED,
            created_at=anchor + timedelta(hours=2, minutes=index),
        )

    return {
        "anchor": anchor,
        "start": start,
        "end": end,
        "plan": plan,
        "admin_headers": await _headers(db_session, admin),
        "normal_headers": await _headers(db_session, normal),
        "github_users": github_users,
        "dropbox_users": dropbox_users,
        "drive_users": drive_users,
        "zotero_users": zotero_users,
        "mendeley_users": mendeley_users,
    }


class TestAdminReport:
    @staticmethod
    def _params(seed: dict[str, object], **extra: object) -> dict[str, object]:
        params: dict[str, object] = {
            "start_date": seed["start"],
            "end_date": seed["end"],
            "plan": seed["plan"],
        }
        params.update(extra)
        return params

    async def test_provider_buckets_and_reconciliation(self, client, report_seed: dict[str, object]) -> None:
        response = await client.get(
            ENDPOINT,
            params=self._params(report_seed),
            headers=report_seed["admin_headers"],
        )
        assert response.status_code == 200, response.text
        body = response.json()
        providers = {row["provider"]: row for row in body["providers"]}

        github = providers["github"]
        assert github["connected_accounts"] == 6
        assert github["connect_started"] == 6
        assert github["connected"] == 6
        assert github["disconnected"] == 1
        assert github["oauth_success_rate_pct"] == 100.0
        assert github["sync_succeeded"] == 8
        assert github["sync_failed"] == 2
        assert github["sync_failure_rate_pct"] == 20.0
        assert github["disconnect_reasons"] == [{"reason": "user_requested", "label": "User requested", "count": 1}]
        assert {row["error_class"] for row in github["sync_error_classes"]} == {
            "provider_unavailable",
            "auth",
        }
        assert github["reconciliation"]["current_connected_accounts"] == 6
        assert github["reconciliation"]["period_net_connection_events"] == 5
        assert github["reconciliation"]["sync_enabled_resources"] == 3
        assert github["telemetry_state"] == "ok"
        assert github["by_plan"][0]["plan"] == report_seed["plan"]
        assert github["by_plan"][0]["connected_accounts"] == 6
        assert github["by_plan"][0]["distinct_users"] == 6

        drive = providers["google_drive"]
        assert drive["oauth_success_rate_pct"] == 80.0
        assert drive["sync_succeeded"] == 4
        assert drive["sync_failed"] == 1
        assert drive["sync_failure_rate_pct"] == 20.0

        mendeley = providers["mendeley"]
        assert mendeley["connected_accounts"] == 5
        assert mendeley["telemetry_state"] == "missing_telemetry"
        assert mendeley["telemetry_state_label"] == "Telemetry missing"
        assert mendeley["connect_started"] == 0
        assert mendeley["reconciliation"]["sync_enabled_resources"] is None
        assert mendeley["by_plan"][0]["telemetry_state"] == "missing_telemetry"

        # A provider with four users is fully suppressed, including its plan row.
        zotero = providers["zotero"]
        assert zotero["suppressed"] is True
        assert zotero["connected_accounts"] is None
        assert zotero["telemetry_state"] == "suppressed"
        assert zotero["by_plan"] == []
        assert zotero["suppressed_plan_rows"] == 1

        # Complementary suppression hides the summary because Zotero is hidden.
        assert body["summary"]["suppressed"] is True
        assert body["summary"]["connected_accounts"] is None

    async def test_provider_filter_scopes_summary_and_rows(self, client, report_seed: dict[str, object]) -> None:
        response = await client.get(
            ENDPOINT,
            params=self._params(report_seed, provider="github"),
            headers=report_seed["admin_headers"],
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["filters"]["provider"] == "github"
        assert [row["provider"] for row in body["providers"]] == ["github"]
        assert body["summary"]["suppressed"] is False
        assert body["summary"]["connected_accounts"] == 6
        assert body["summary"]["oauth_success_rate_pct"] == 100.0
        assert body["summary"]["sync_failure_rate_pct"] == 20.0
        assert body["summary"]["distinct_users"] == 6

    async def test_small_provider_and_summary_are_suppressed(self, client, db_session: AsyncSession) -> None:
        anchor = _anchor()
        plan = f"small{_hex()}"
        for _ in range(4):
            await _user(db_session, plan=plan, zotero=True)
        admin = await _user(db_session, role="admin", plan="pro")
        headers = await _headers(db_session, admin)

        response = await client.get(
            ENDPOINT,
            params={
                "start_date": anchor.date(),
                "end_date": (anchor + timedelta(days=1)).date(),
                "plan": plan,
                "provider": "zotero",
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["summary"]["suppressed"] is True
        assert body["summary"]["distinct_users"] is None
        assert body["providers"][0]["suppressed"] is True
        assert body["providers"][0]["connected_accounts"] is None

    async def test_hidden_plan_cohort_withholds_the_plan_breakdown(self, client, db_session: AsyncSession) -> None:
        anchor = _anchor()
        large_plan = f"lg{_hex()}"
        small_plan = f"sm{_hex()}"
        for _ in range(5):
            await _user(db_session, plan=large_plan, dropbox=True)
        for _ in range(4):
            await _user(db_session, plan=small_plan, dropbox=True)
        admin = await _user(db_session, role="admin", plan="pro")
        headers = await _headers(db_session, admin)

        response = await client.get(
            ENDPOINT,
            params={
                "start_date": anchor.date(),
                "end_date": (anchor + timedelta(days=1)).date(),
                "provider": "dropbox",
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        provider = response.json()["providers"][0]
        assert provider["suppressed"] is False
        assert provider["telemetry_state"] == "missing_telemetry"
        assert provider["plan_breakdown_suppressed"] is True
        assert provider["suppressed_plan_rows"] >= 1
        assert provider["by_plan"] == []

    async def test_privacy_boundary_returns_no_credentials_or_payloads(
        self, client, report_seed: dict[str, object]
    ) -> None:
        response = await client.get(
            ENDPOINT,
            params=self._params(report_seed, provider="github"),
            headers=report_seed["admin_headers"],
        )
        assert response.status_code == 200, response.text
        body = response.json()
        serialized = json.dumps(body)
        for forbidden in (
            "@example.org",
            "test_integration_",
            "SECRET_LATEX_BODY",
            "gh_",
            "dbx_",
            "gd_",
            "zo_",
            "me_",
        ):
            assert forbidden not in serialized

        def keys(value: object) -> set[str]:
            found: set[str] = set()
            if isinstance(value, dict):
                for key, child in value.items():
                    found.add(str(key))
                    found.update(keys(child))
            elif isinstance(value, list):
                for child in value:
                    found.update(keys(child))
            return found

        response_keys = keys(body)
        for forbidden_key in (
            "access_token",
            "refresh_token",
            "email",
            "filename",
            "user_agent",
            "ip_address",
            "user_id",
            "latex_content",
        ):
            assert forbidden_key not in response_keys

    async def test_admin_only(self, client, report_seed: dict[str, object]) -> None:
        params = self._params(report_seed)
        anonymous = await client.get(ENDPOINT, params=params)
        assert anonymous.status_code in (401, 403)
        normal = await client.get(
            ENDPOINT,
            params=params,
            headers=report_seed["normal_headers"],
        )
        assert normal.status_code in (401, 403)

    async def test_invalid_filters_are_422(self, client, report_seed: dict[str, object]) -> None:
        bad_plan = await client.get(
            ENDPOINT,
            params={"plan": "NOT A PLAN"},
            headers=report_seed["admin_headers"],
        )
        assert bad_plan.status_code == 422
        bad_provider = await client.get(
            ENDPOINT,
            params={"provider": "ftp"},
            headers=report_seed["admin_headers"],
        )
        assert bad_provider.status_code == 422

    async def test_empty_period_returns_zeroes_without_suppression(
        self, client, report_seed: dict[str, object]
    ) -> None:
        response = await client.get(
            ENDPOINT,
            params={
                "start_date": "2045-01-01",
                "end_date": "2045-01-10",
                "plan": report_seed["plan"],
                "provider": "github",
            },
            headers=report_seed["admin_headers"],
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["summary"]["suppressed"] is False
        assert body["summary"]["connected_accounts"] == 6
        assert body["summary"]["telemetry_state"] == "missing_telemetry"
        assert body["providers"][0]["connect_started"] == 0
        assert body["providers"][0]["sync_failed"] == 0

    async def test_snapshot_is_callable_without_http(
        self, db_session: AsyncSession, report_seed: dict[str, object]
    ) -> None:
        result = await snapshot(
            db_session,
            start_date=report_seed["start"],
            end_date=report_seed["end"],
            plan=report_seed["plan"],
            provider="github",
        )
        assert result["minimum_cohort_size"] == MIN_GROUP_SIZE
        assert result["providers"][0]["provider"] == "github"
        assert result["reconciliation"]["telemetry_source"].startswith("usage_analytics")


def test_no_integration_analytics_migration_was_added() -> None:
    versions = BACKEND / "alembic" / "versions"
    names = [path.name for path in versions.glob("*.py")]
    assert names
    assert not any("admin_integration" in name or "integration_analytics" in name or "2081" in name for name in names)
