"""Share/portfolio performance analytics: privacy, suppression, and funnels.

Coverage:
  * viewer-key hashing is deterministic and never stores raw IP/user-agent;
  * capture endpoints require explicit analytics consent;
  * portfolio view -> contact -> signup funnel with explicit denominators;
  * five-viewer suppression for summaries, groups, and funnel cells;
  * admin-only access and per-resume/per-portfolio drill-downs;
  * aggregate responses never contain viewer, PII, token, or document fields;
  * the feature uses existing tables and adds no migration.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database import models
from app.services.share_portfolio_analytics_service import (
    MIN_COHORT_SIZE,
    PORTFOLIO_CONTACT_ACTION,
    PORTFOLIO_SIGNUP_ACTION,
    PORTFOLIO_VIEW_ACTION,
    hash_viewer_key,
)

UTC = timezone.utc
REPORT_ENDPOINT = "/admin/analytics/share-portfolio"
VIEW_ENDPOINT = "/portfolio/{username}/analytics/view"
CONTACT_ENDPOINT = "/portfolio/{username}/analytics/contact"
CLAIM_ENDPOINT = "/portfolio/analytics/claim-signup"


def _hex() -> str:
    return uuid.uuid4().hex[:10]


def _anchor() -> datetime:
    """A future, isolated window so shared-database activity cannot overlap."""

    return datetime(2034, 1, 1, tzinfo=UTC) + timedelta(
        days=uuid.uuid4().int % 900
    )


async def _user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
    portfolio: str | None = None,
    enabled: bool = True,
    created_at: datetime | None = None,
    name: str = "Analytics User",
) -> models.User:
    user = models.User(
        id=str(uuid.uuid4()),
        email=f"wave8_portfolio_{uuid.uuid4().hex}@example.org",
        name=name,
        role=role,
        email_verified=True,
        subscription_plan=plan,
        subscription_status="active",
        trial_used=False,
        public_username=portfolio,
        portfolio_enabled=enabled,
        created_at=created_at or datetime.now(UTC),
    )
    db.add(user)
    await db.commit()
    return user


async def _headers(db: AsyncSession, user: models.User) -> dict[str, str]:
    token = f"wave8_sess_{uuid.uuid4().hex}"
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
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
    token: str | None = None,
    token_created_at: datetime | None = None,
    title: str = "Analytics Resume",
    latex: str = "SECRET_LATEX_CONTENT",
) -> models.Resume:
    resume = models.Resume(
        id=str(uuid.uuid4()),
        user_id=str(user.id),
        title=title,
        latex_content=latex,
        is_template=False,
        share_token=token,
        share_token_created_at=token_created_at,
        portfolio_visible=True,
    )
    db.add(resume)
    await db.commit()
    return resume


async def _view(
    db: AsyncSession,
    *,
    resume: models.Resume,
    session_id: str,
    viewed_at: datetime,
    country: str | None = "IN",
    referrer: str | None = "https://news.ycombinator.com/item?id=SECRET_QUERY",
) -> None:
    db.add(
        models.ResumeView(
            id=str(uuid.uuid4()),
            resume_id=str(resume.id),
            share_token=str(resume.share_token or "token"),
            viewed_at=viewed_at,
            country_code=country,
            user_agent="SECRET_USER_AGENT",
            referrer=referrer,
            session_id=session_id,
        )
    )
    await db.commit()


async def _event(
    db: AsyncSession,
    *,
    action: str,
    owner: models.User,
    viewer_key: str,
    created_at: datetime,
    country: str | None = "IN",
    referrer: str | None = "news.ycombinator.com",
    signup_user_id: str | None = None,
) -> None:
    metadata = {
        "source": "public_portfolio",
        "portfolio_username": owner.public_username,
        "portfolio_owner_id": str(owner.id),
        "viewer_key": viewer_key,
    }
    if country:
        metadata["country"] = country
    if referrer:
        metadata["referrer_host"] = referrer
    db.add(
        models.UsageAnalytics(
            id=str(uuid.uuid4()),
            user_id=str(owner.id) if signup_user_id is None else signup_user_id,
            device_fingerprint=None,
            action=action,
            resource_type="portfolio",
            event_metadata=metadata,
            ip_address=None,
            user_agent=None,
            created_at=created_at,
        )
    )
    await db.commit()


class TestViewerKeyHashing:
    def test_hash_is_short_deterministic_hex(self) -> None:
        first = hash_viewer_key("203.0.113.9", "Browser/1")
        second = hash_viewer_key("203.0.113.9", "Browser/1")
        assert first == second
        assert len(first) == 16
        assert all(character in "0123456789abcdef" for character in first)

    def test_ip_or_user_agent_change_changes_the_key(self) -> None:
        base = hash_viewer_key("203.0.113.9", "Browser/1")
        assert hash_viewer_key("203.0.113.10", "Browser/1") != base
        assert hash_viewer_key("203.0.113.9", "Browser/2") != base

    def test_missing_inputs_still_produce_an_opaque_key(self) -> None:
        key = hash_viewer_key(None, None)
        assert len(key) == 16
        assert "unknown" not in key


class TestPortfolioCapture:
    async def test_consent_is_required_before_any_row_is_written(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        owner = await _user(db_session, portfolio=f"pf_{_hex()}")
        username = str(owner.public_username)
        before = (
            await db_session.execute(
                select(func.count(models.UsageAnalytics.id)).where(
                    models.UsageAnalytics.action == PORTFOLIO_VIEW_ACTION
                )
            )
        ).scalar_one()

        response = await client.post(
            VIEW_ENDPOINT.format(username=username),
            json={},
            headers={"User-Agent": "NoConsentBrowser"},
        )

        assert response.status_code == 202
        assert response.json()["recorded"] is False
        assert response.json()["reason"] == "consent_required"
        after = (
            await db_session.execute(
                select(func.count(models.UsageAnalytics.id)).where(
                    models.UsageAnalytics.action == PORTFOLIO_VIEW_ACTION
                )
            )
        ).scalar_one()
        assert after == before

    async def test_view_stores_only_hashed_server_derived_fields(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        owner = await _user(db_session, portfolio=f"pf_{_hex()}")
        username = str(owner.public_username)
        headers = {
            "User-Agent": "SECRET_USER_AGENT_BROWSER",
            "Referer": "https://news.ycombinator.com/item?id=SECRET_QUERY#frag",
            "X-Real-IP": "203.0.113.9",
            "CF-IPCountry": "in",
        }

        response = await client.post(
            VIEW_ENDPOINT.format(username=username),
            json={"analytics_consent": True},
            headers=headers,
        )

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["recorded"] is True
        assert "viewer_key" not in json.dumps(body)
        assert "SECRET_USER_AGENT" not in json.dumps(body)

        row = (
            await db_session.execute(
                select(models.UsageAnalytics).where(
                    models.UsageAnalytics.action == PORTFOLIO_VIEW_ACTION,
                    models.UsageAnalytics.event_metadata["portfolio_username"]
                    .as_string()
                    == username,
                )
            )
        ).scalars().first()
        assert row is not None
        assert row.ip_address is None
        assert row.user_agent is None
        assert row.device_fingerprint is None
        assert row.event_metadata["viewer_key"] == hash_viewer_key(
            "203.0.113.9", "SECRET_USER_AGENT_BROWSER"
        )
        assert row.event_metadata["referrer_host"] == "news.ycombinator.com"
        assert row.event_metadata["country"] == "IN"
        serialized = json.dumps(row.event_metadata)
        assert "203.0.113.9" not in serialized
        assert "SECRET_USER_AGENT" not in serialized
        assert "SECRET_QUERY" not in serialized

    async def test_view_is_debounced_per_viewer(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        owner = await _user(db_session, portfolio=f"pf_{_hex()}")
        username = str(owner.public_username)
        headers = {"User-Agent": "DebounceBrowser"}
        payload = {"analytics_consent": True}

        first = await client.post(
            VIEW_ENDPOINT.format(username=username), json=payload, headers=headers
        )
        second = await client.post(
            VIEW_ENDPOINT.format(username=username), json=payload, headers=headers
        )

        assert first.json()["recorded"] is True
        assert second.json()["recorded"] is False
        assert second.json()["reason"] == "debounced"
        count = (
            await db_session.execute(
                select(func.count(models.UsageAnalytics.id)).where(
                    models.UsageAnalytics.action == PORTFOLIO_VIEW_ACTION,
                    models.UsageAnalytics.event_metadata["portfolio_username"]
                    .as_string()
                    == username,
                )
            )
        ).scalar_one()
        assert count == 1

    async def test_contact_records_no_message_content(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        owner = await _user(db_session, portfolio=f"pf_{_hex()}")
        username = str(owner.public_username)

        response = await client.post(
            CONTACT_ENDPOINT.format(username=username),
            json={"analytics_consent": True},
            headers={"User-Agent": "ContactBrowser"},
        )

        assert response.status_code == 202, response.text
        assert response.json()["recorded"] is True
        row = (
            await db_session.execute(
                select(models.UsageAnalytics).where(
                    models.UsageAnalytics.action == PORTFOLIO_CONTACT_ACTION,
                    models.UsageAnalytics.event_metadata["portfolio_username"]
                    .as_string()
                    == username,
                )
            )
        ).scalars().first()
        assert row is not None
        assert row.ip_address is None
        assert row.user_agent is None
        metadata = row.event_metadata
        for forbidden in ("email", "name", "message", "ip_address", "user_agent"):
            assert forbidden not in metadata

    async def test_unknown_portfolio_returns_404_with_consent(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            VIEW_ENDPOINT.format(username=f"pf_{_hex()}"),
            json={"analytics_consent": True},
            headers={"User-Agent": "UnknownBrowser"},
        )
        assert response.status_code == 404


class TestSignupClaim:
    async def test_claim_links_one_account_to_one_view_without_pii(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        owner = await _user(db_session, portfolio=f"pf_{_hex()}")
        viewer = f"198.51.100.{uuid.uuid4().int % 200 + 1}"
        user_agent = f"ClaimBrowser/{uuid.uuid4().hex}"
        viewer_key = hash_viewer_key(viewer, user_agent)
        await _event(
            db_session,
            action=PORTFOLIO_VIEW_ACTION,
            owner=owner,
            viewer_key=viewer_key,
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
        signup = await _user(db_session, plan="free")
        headers = {
            **await _headers(db_session, signup),
            "User-Agent": user_agent,
            "X-Real-IP": viewer,
        }

        response = await client.post(
            CLAIM_ENDPOINT,
            json={"analytics_consent": True},
            headers=headers,
        )

        assert response.status_code == 202, response.text
        assert response.json()["recorded"] is True
        row = (
            await db_session.execute(
                select(models.UsageAnalytics).where(
                    models.UsageAnalytics.action == PORTFOLIO_SIGNUP_ACTION,
                    models.UsageAnalytics.user_id == str(signup.id),
                )
            )
        ).scalars().first()
        assert row is not None
        assert row.event_metadata["portfolio_owner_id"] == str(owner.id)
        assert row.event_metadata["portfolio_username"] == owner.public_username
        assert row.event_metadata["viewer_key"] == viewer_key
        serialized = json.dumps(row.event_metadata)
        assert viewer not in serialized
        assert user_agent not in serialized
        assert row.ip_address is None
        assert row.user_agent is None

        duplicate = await client.post(
            CLAIM_ENDPOINT,
            json={"analytics_consent": True},
            headers=headers,
        )
        assert duplicate.json()["recorded"] is False
        assert duplicate.json()["reason"] == "already_attributed"

    async def test_claim_requires_consent(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        signup = await _user(db_session, plan="free")
        response = await client.post(
            CLAIM_ENDPOINT,
            json={},
            headers=await _headers(db_session, signup),
        )
        assert response.status_code == 202
        assert response.json()["reason"] == "consent_required"

    async def test_claim_does_not_use_a_view_after_signup(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        owner = await _user(db_session, portfolio=f"pf_{_hex()}")
        suffix = uuid.uuid4().hex[:8]
        viewer = f"198.51.100.{uuid.uuid4().int % 200 + 1}"
        user_agent = f"AfterSignupBrowser/{suffix}"
        signup = await _user(
            db_session,
            plan="free",
            created_at=datetime.now(UTC) - timedelta(hours=2),
        )
        await _event(
            db_session,
            action=PORTFOLIO_VIEW_ACTION,
            owner=owner,
            viewer_key=hash_viewer_key(viewer, user_agent),
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
        response = await client.post(
            CLAIM_ENDPOINT,
            json={"analytics_consent": True},
            headers={
                **await _headers(db_session, signup),
                "User-Agent": user_agent,
                "X-Real-IP": viewer,
            },
        )
        assert response.status_code == 202
        assert response.json()["reason"] == "no_portfolio_view"

    async def test_claim_rejects_old_accounts_and_missing_views(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
        suffix = uuid.uuid4().hex[:8]
        old_user = await _user(
            db_session,
            plan="free",
            created_at=datetime.now(UTC) - timedelta(days=30),
        )
        old_response = await client.post(
            CLAIM_ENDPOINT,
            json={"analytics_consent": True},
            headers={
                **await _headers(db_session, old_user),
                "User-Agent": f"OldBrowser/{suffix}",
                "X-Real-IP": "198.51.100.8",
            },
        )
        assert old_response.json()["reason"] == "outside_signup_window"

        new_user = await _user(db_session, plan="free")
        no_view = await client.post(
            CLAIM_ENDPOINT,
            json={"analytics_consent": True},
            headers={
                **await _headers(db_session, new_user),
                "User-Agent": f"NoViewBrowser/{suffix}",
                "X-Real-IP": "198.51.100.9",
            },
        )
        assert no_view.json()["reason"] == "no_portfolio_view"


class TestAdminReport:
    @pytest.fixture
    async def report_seed(self, db_session: AsyncSession) -> dict[str, object]:
        anchor = _anchor()
        start = anchor.date()
        end = (anchor + timedelta(days=9)).date()
        token_time = anchor + timedelta(days=1)
        plan_a = f"wave8pro{uuid.uuid4().hex[:8]}"
        plan_b = f"wave8free{uuid.uuid4().hex[:8]}"

        owner_a = await _user(
            db_session, plan=plan_a, portfolio=f"pf_a_{_hex()}"
        )
        owner_b = await _user(
            db_session, plan=plan_b, portfolio=f"pf_b_{_hex()}"
        )
        owner_c = await _user(
            db_session, plan=plan_b, portfolio=f"pf_c_{_hex()}"
        )
        admin = await _user(db_session, role="admin")
        normal = await _user(db_session, role="user")

        r_a1 = await _resume(
            db_session,
            user=owner_a,
            token=f"SECRET_SHARE_TOKEN_{_hex()}",
            token_created_at=token_time,
            title="SECRET_RESUME_TITLE_A1",
        )
        r_a2 = await _resume(
            db_session,
            user=owner_a,
            token=f"SECRET_SHARE_TOKEN_{_hex()}",
            token_created_at=token_time,
            title="SECRET_RESUME_TITLE_A2",
        )
        r_b1 = await _resume(
            db_session,
            user=owner_b,
            token=f"SECRET_SHARE_TOKEN_{_hex()}",
            token_created_at=token_time,
            title="SECRET_RESUME_TITLE_B1",
        )
        r_c1 = await _resume(
            db_session,
            user=owner_c,
            token=f"SECRET_SHARE_TOKEN_{_hex()}",
            token_created_at=token_time,
            title="SECRET_RESUME_TITLE_C1",
        )

        # Owner A: one link above the suppression floor, one below it.
        for index in range(1, 6):
            await _view(
                db_session,
                resume=r_a1,
                session_id=f"SECRET_SESSION_A1_{index}",
                viewed_at=anchor + timedelta(hours=2, minutes=index),
                country="IN",
                referrer="https://news.ycombinator.com/item?id=SECRET_QUERY",
            )
        await _view(
            db_session,
            resume=r_a1,
            session_id="SECRET_SESSION_A1_1",
            viewed_at=anchor + timedelta(hours=3),
            country="IN",
            referrer="https://news.ycombinator.com/item?id=SECRET_QUERY",
        )
        for index in range(1, 3):
            await _view(
                db_session,
                resume=r_a2,
                session_id=f"SECRET_SESSION_A2_{index}",
                viewed_at=anchor + timedelta(hours=2, minutes=index),
                country="US",
                referrer="https://www.google.com/search?q=SECRET_QUERY",
            )

        # Owner B is the full five-contact/five-signup funnel.
        for index in range(1, 6):
            await _view(
                db_session,
                resume=r_b1,
                session_id=f"SECRET_SESSION_B1_{index}",
                viewed_at=anchor + timedelta(hours=2, minutes=index),
                country="GB",
                referrer="https://www.google.com/search?q=SECRET_QUERY",
            )

        # Owner C is below the suppression floor.
        for index in range(1, 5):
            await _view(
                db_session,
                resume=r_c1,
                session_id=f"SECRET_SESSION_C1_{index}",
                viewed_at=anchor + timedelta(hours=2, minutes=index),
                country="US",
                referrer="https://www.google.com/search?q=SECRET_QUERY",
            )

        # Portfolio A: 5 viewers, 3 contacts, 1 signup (contact/signup suppressed).
        for index in range(1, 6):
            await _event(
                db_session,
                action=PORTFOLIO_VIEW_ACTION,
                owner=owner_a,
                viewer_key=hash_viewer_key(f"10.0.0.{index}", "PortfolioA"),
                created_at=anchor + timedelta(hours=4, minutes=index),
            )
        for index in range(1, 4):
            await _event(
                db_session,
                action=PORTFOLIO_CONTACT_ACTION,
                owner=owner_a,
                viewer_key=hash_viewer_key(f"10.0.0.{index}", "PortfolioA"),
                created_at=anchor + timedelta(hours=5, minutes=index),
            )
        await _event(
            db_session,
            action=PORTFOLIO_SIGNUP_ACTION,
            owner=owner_a,
            viewer_key=hash_viewer_key("10.0.0.1", "PortfolioA"),
            created_at=anchor + timedelta(hours=6),
            signup_user_id=str((await _user(db_session, plan="free")).id),
        )

        # Portfolio B: full funnel, 5 viewers / 5 contacts / 5 signups.
        signup_b = await _user(db_session, plan="free")
        for index in range(1, 6):
            await _event(
                db_session,
                action=PORTFOLIO_VIEW_ACTION,
                owner=owner_b,
                viewer_key=hash_viewer_key(f"10.1.0.{index}", "PortfolioB"),
                created_at=anchor + timedelta(hours=4, minutes=index),
                country="GB",
                referrer="www.google.com",
            )
            await _event(
                db_session,
                action=PORTFOLIO_CONTACT_ACTION,
                owner=owner_b,
                viewer_key=hash_viewer_key(f"10.1.0.{index}", "PortfolioB"),
                created_at=anchor + timedelta(hours=5, minutes=index),
                country="GB",
                referrer="www.google.com",
            )
            await _event(
                db_session,
                action=PORTFOLIO_SIGNUP_ACTION,
                owner=owner_b,
                viewer_key=hash_viewer_key(f"10.1.0.{index}", "PortfolioB"),
                created_at=anchor + timedelta(hours=6, minutes=index),
                country="GB",
                referrer="www.google.com",
                signup_user_id=str(signup_b.id),
            )

        # Portfolio C: 4 viewers, 2 contacts, 1 signup.
        signup_c = await _user(db_session, plan="free")
        for index in range(1, 5):
            await _event(
                db_session,
                action=PORTFOLIO_VIEW_ACTION,
                owner=owner_c,
                viewer_key=hash_viewer_key(f"10.2.0.{index}", "PortfolioC"),
                created_at=anchor + timedelta(hours=4, minutes=index),
                country="US",
                referrer="www.google.com",
            )
        for index in range(1, 3):
            await _event(
                db_session,
                action=PORTFOLIO_CONTACT_ACTION,
                owner=owner_c,
                viewer_key=hash_viewer_key(f"10.2.0.{index}", "PortfolioC"),
                created_at=anchor + timedelta(hours=5, minutes=index),
                country="US",
                referrer="www.google.com",
            )
        await _event(
            db_session,
            action=PORTFOLIO_SIGNUP_ACTION,
            owner=owner_c,
            viewer_key=hash_viewer_key("10.2.0.1", "PortfolioC"),
            created_at=anchor + timedelta(hours=6),
            country="US",
            referrer="www.google.com",
            signup_user_id=str(signup_c.id),
        )

        return {
            "anchor": anchor,
            "start": start,
            "end": end,
            "owner_a": owner_a,
            "owner_b": owner_b,
            "owner_c": owner_c,
            "plan_a": plan_a,
            "plan_b": plan_b,
            "admin_headers": await _headers(db_session, admin),
            "normal_headers": await _headers(db_session, normal),
            "r_a1": r_a1,
            "r_b1": r_b1,
        }

    @staticmethod
    def _params(seed: dict[str, object], **extra: object) -> dict[str, object]:
        params: dict[str, object] = {
            "start_date": seed["start"],
            "end_date": seed["end"],
        }
        params.update(extra)
        return params

    async def test_summary_uniques_conversion_and_breakdowns(
        self,
        client: AsyncClient,
        report_seed: dict[str, object],
    ) -> None:
        response = await client.get(
            REPORT_ENDPOINT,
            params=self._params(report_seed, plan=report_seed["plan_a"]),
            headers=report_seed["admin_headers"],  # type: ignore[arg-type]
        )
        assert response.status_code == 200, response.text
        body = response.json()
        share = body["share"]

        assert share["summary"]["views"] == 8
        assert share["summary"]["unique_viewers"] == 7
        assert share["summary"]["repeat_views"] == 1
        assert share["summary"]["repeat_view_rate_pct"] == 12.5
        assert share["summary"]["active_share_links"] == 2
        assert share["summary"]["viewed_share_links"] == 2
        assert share["conversion"]["rate_pct"] == 100.0
        assert [row["resume_id"] for row in share["by_resume"]] == [
            str(report_seed["r_a1"].id)
        ]
        assert share["suppressed_groups"]["resume"] == 1
        assert share["by_referrer"] == [
            {
                "referrer": "news.ycombinator.com",
                "views": 6,
                "unique_viewers": 5,
            }
        ]
        assert share["suppressed_groups"]["referrer"] == 1
        assert share["by_country"][0]["country_code"] == "IN"
        assert share["by_country"][0]["unique_viewers"] == 5

    async def test_plan_filter_limits_every_metric(
        self,
        client: AsyncClient,
        report_seed: dict[str, object],
    ) -> None:
        response = await client.get(
            REPORT_ENDPOINT,
            params=self._params(report_seed, plan=report_seed["plan_b"]),
            headers=report_seed["admin_headers"],  # type: ignore[arg-type]
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["filters"]["plan"] == report_seed["plan_b"]
        # Owner B (5) and owner C (4) are the only free-plan viewers.
        assert body["share"]["summary"]["unique_viewers"] == 9
        assert body["portfolio"]["summary"]["unique_viewers"] == 9
        assert body["portfolio"]["summary"]["unique_contact_viewers"] == 7
        assert body["portfolio"]["summary"]["unique_signup_viewers"] == 6
        assert body["portfolio"]["by_portfolio"][0]["portfolio_username"] == str(
            report_seed["owner_b"].public_username
        )
        assert body["portfolio"]["suppressed_groups"]["portfolio"] == 1

    async def test_funnel_reports_explicit_denominators(
        self,
        client: AsyncClient,
        report_seed: dict[str, object],
    ) -> None:
        response = await client.get(
            REPORT_ENDPOINT,
            params=self._params(report_seed, plan=report_seed["plan_b"]),
            headers=report_seed["admin_headers"],  # type: ignore[arg-type]
        )
        body = response.json()
        funnel = body["portfolio"]["funnel"]
        steps = {step["step"]: step for step in funnel["steps"]}

        assert steps["portfolio_views"]["count"] == 9
        assert steps["portfolio_views"]["denominator"] == "portfolio page views"
        assert steps["contact"]["denominator"] == "unique portfolio viewers"
        assert steps["contact"]["denominator_value"] == 9
        assert steps["contact"]["count"] == 7
        assert steps["contact"]["unique_viewers"] == 7
        assert steps["contact"]["conversion_from_previous_pct"] == 77.78
        assert steps["signup"]["denominator"] == "unique contact viewers"
        assert steps["signup"]["denominator_value"] == 7
        assert steps["signup"]["count"] == 6
        assert steps["signup"]["unique_viewers"] == 6
        assert steps["signup"]["conversion_from_previous_pct"] == 85.71
        assert steps["signup"]["conversion_from_start_pct"] == 66.67
        assert funnel["denominators"]["unique_viewers"]["value"] == 9

    async def test_small_cohorts_are_suppressed(
        self,
        client: AsyncClient,
        report_seed: dict[str, object],
    ) -> None:
        response = await client.get(
            REPORT_ENDPOINT,
            params=self._params(
                report_seed,
                portfolio=str(report_seed["owner_a"].public_username),
            ),
            headers=report_seed["admin_headers"],  # type: ignore[arg-type]
        )
        assert response.status_code == 200, response.text
        body = response.json()
        portfolio = body["portfolio"]

        assert portfolio["summary"]["unique_viewers"] == MIN_COHORT_SIZE
        assert portfolio["summary"]["contact_events"] is None
        assert portfolio["summary"]["unique_contact_viewers"] is None
        assert portfolio["summary"]["signups"] is None
        assert "contact_events" in portfolio["summary"]["suppressed_cells"]
        funnel = {step["step"]: step for step in portfolio["funnel"]["steps"]}
        assert funnel["contact"]["suppressed"] is True
        assert funnel["signup"]["suppressed"] is True
        assert funnel["contact"]["count"] is None
        # The 5-viewer portfolio row is visible, but its 1-4 contact cells are not.
        row = portfolio["by_portfolio"][0]
        assert row["unique_viewers"] == 5
        assert row["contact_events"] is None
        assert "contact_events" in row["suppressed_cells"]

        below = await client.get(
            REPORT_ENDPOINT,
            params=self._params(
                report_seed,
                portfolio=str(report_seed["owner_c"].public_username),
            ),
            headers=report_seed["admin_headers"],  # type: ignore[arg-type]
        )
        below_body = below.json()
        assert below_body["portfolio"]["summary"]["views"] is None
        assert below_body["portfolio"]["summary"]["suppressed"] is True
        assert below_body["portfolio"]["by_portfolio"] == []
        assert below_body["portfolio"]["suppressed_groups"]["portfolio"] == 1

    async def test_privacy_boundary_returns_no_viewer_or_document_fields(
        self,
        client: AsyncClient,
        report_seed: dict[str, object],
    ) -> None:
        response = await client.get(
            REPORT_ENDPOINT,
            params=self._params(report_seed, plan=report_seed["plan_a"]),
            headers=report_seed["admin_headers"],  # type: ignore[arg-type]
        )
        assert response.status_code == 200, response.text
        body = response.json()
        serialized = json.dumps(body)

        for forbidden in (
            "SECRET_SESSION_",
            "SECRET_SHARE_TOKEN_",
            "SECRET_LATEX_CONTENT",
            "SECRET_RESUME_TITLE",
            "SECRET_USER_AGENT",
            "SECRET_QUERY",
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
            "session_id",
            "viewer_key",
            "user_agent",
            "ip_address",
            "device_fingerprint",
            "latex_content",
            "email",
            "share_token",
            "portfolio_owner_id",
            "user_id",
        ):
            assert forbidden_key not in response_keys

    async def test_admin_only(
        self,
        client: AsyncClient,
        report_seed: dict[str, object],
    ) -> None:
        params = self._params(report_seed)
        anonymous = await client.get(REPORT_ENDPOINT, params=params)
        assert anonymous.status_code in (401, 403)

        normal = await client.get(
            REPORT_ENDPOINT,
            params=params,
            headers=report_seed["normal_headers"],  # type: ignore[arg-type]
        )
        assert normal.status_code in (401, 403)

    async def test_per_resume_and_per_portfolio_drilldowns(
        self,
        client: AsyncClient,
        report_seed: dict[str, object],
    ) -> None:
        admin_headers = report_seed["admin_headers"]
        resume = await client.get(
            f"{REPORT_ENDPOINT}/resumes/{report_seed['r_a1'].id}",
            params={"start_date": report_seed["start"], "end_date": report_seed["end"]},
            headers=admin_headers,  # type: ignore[arg-type]
        )
        assert resume.status_code == 200, resume.text
        resume_body = resume.json()
        assert resume_body["share"]["summary"]["unique_viewers"] == 5
        assert resume_body["share"]["summary"]["views"] == 6

        portfolio = await client.get(
            f"{REPORT_ENDPOINT}/portfolios/{report_seed['owner_b'].public_username}",
            params={"start_date": report_seed["start"], "end_date": report_seed["end"]},
            headers=admin_headers,  # type: ignore[arg-type]
        )
        assert portfolio.status_code == 200, portfolio.text
        portfolio_body = portfolio.json()
        assert portfolio_body["portfolio"]["summary"]["views"] == 5
        assert portfolio_body["portfolio"]["summary"]["unique_contact_viewers"] == 5
        assert portfolio_body["portfolio"]["summary"]["unique_signup_viewers"] == 5

        missing_resume = await client.get(
            f"{REPORT_ENDPOINT}/resumes/{uuid.uuid4()}",
            headers=admin_headers,  # type: ignore[arg-type]
        )
        assert missing_resume.status_code == 404
        invalid_resume = await client.get(
            f"{REPORT_ENDPOINT}/resumes/not-a-uuid",
            headers=admin_headers,  # type: ignore[arg-type]
        )
        assert invalid_resume.status_code == 422
        invalid_filter = await client.get(
            REPORT_ENDPOINT,
            params={"resume_id": "not-a-uuid"},
            headers=admin_headers,  # type: ignore[arg-type]
        )
        assert invalid_filter.status_code == 422
        missing_portfolio = await client.get(
            f"{REPORT_ENDPOINT}/portfolios/pf_missing_{_hex()}",
            headers=admin_headers,  # type: ignore[arg-type]
        )
        assert missing_portfolio.status_code == 404

    async def test_empty_period_returns_zeroes_without_suppression(
        self,
        client: AsyncClient,
        report_seed: dict[str, object],
    ) -> None:
        response = await client.get(
            REPORT_ENDPOINT,
            params={
                "start_date": "2045-01-01",
                "end_date": "2045-01-10",
                "plan": report_seed["plan_a"],
            },
            headers=report_seed["admin_headers"],  # type: ignore[arg-type]
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["share"]["summary"]["views"] == 0
        assert body["share"]["summary"]["unique_viewers"] == 0
        assert body["share"]["summary"]["suppressed"] is False
        assert body["portfolio"]["summary"]["views"] == 0
        assert body["portfolio"]["summary"]["suppressed"] is False
        assert body["portfolio"]["funnel"]["steps"][0]["count"] == 0


def test_no_share_portfolio_migration_was_added() -> None:
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    names = [path.name for path in versions.glob("*.py")]
    assert names
    assert not any(
        "share_portfolio" in name
        or "portfolio_analytics" in name
        or "2082" in name
        for name in names
    )
