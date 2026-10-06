"""
Tests for Feature 85 — White-Label Multi-Tenancy.

Coverage map:
  85T-01  Create tenant → 201, slug unique; duplicate slug → 409
  85T-02  Middleware resolves tenant from X-Tenant-Slug header
  85T-03  Middleware resolves from Host: <slug>.latexy.io subdomain
  85T-04  Non-owner cannot PATCH tenant → 403
  85T-05  Invite member → TenantMember row created → 201
  85T-06  Remove member → row deleted → 204
  85T-07  Stats endpoint returns correct member count
  85T-08  Custom domain stored and retrievable via PATCH
  85T-09  primary_color validation — invalid hex → 422
  85T-10  GET /tenants/my returns all owned + member-of tenants
  85T-11  GET /tenants/current-context returns None when no tenant resolved
  85T-12  GET /tenants/{id}/members requires membership
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.tenant_routes import (
    InviteRequest,
    TenantCreate,
    TenantUpdate,
    accept_invitation,
    create_tenant,
    invite_member,
    leave_tenant,
    list_members,
    list_my_tenants,
    remove_member,
    tenant_stats,
    update_tenant,
    verify_domain,
)
from app.database.models import Tenant, TenantMember, User

# ── Helpers ────────────────────────────────────────────────────────────────────


def _uid() -> str:
    return str(uuid.uuid4())


def make_tenant(
    owner_id: str,
    slug: str = 'test-agency',
    name: str = 'Test Agency',
    primary_color: str | None = '#6d28d9',
    custom_domain: str | None = None,
    active: bool = True,
) -> Tenant:
    t = MagicMock(spec=Tenant)
    t.id = _uid()
    t.slug = slug
    t.name = name
    t.logo_url = None
    t.primary_color = primary_color
    t.custom_domain = custom_domain
    t.domain_verified_at = None
    t.plan_id = 'agency'
    t.max_members = 50
    t.active = active
    t.owner_id = owner_id
    t.created_at = datetime.now(timezone.utc)
    return t


def make_member(
    tenant_id: str,
    user_id: str,
    role: str = 'member',
) -> TenantMember:
    m = MagicMock(spec=TenantMember)
    m.tenant_id = tenant_id
    m.user_id = user_id
    m.role = role
    m.joined_at = datetime.now(timezone.utc)
    return m


def make_user(email: str | None = None, name: str = 'Test User') -> User:
    u = MagicMock(spec=User)
    u.id = _uid()
    u.email = email or f'test_{_uid().replace("-", "")}@example.com'
    u.name = name
    return u


def _mock_db() -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _admin_result() -> MagicMock:
    row = MagicMock(role="admin", subscription_plan="free")
    return MagicMock(one_or_none=MagicMock(return_value=row))


# ── 85T-01  Create tenant — slug unique; duplicate → 409 ─────────────────────


class TestCreateTenant:
    @pytest.mark.asyncio
    async def test_create_tenant_success(self):
        """POST /tenants → 201, slug unique check passes, commit called."""
        owner_id = _uid()
        body = TenantCreate(name='Acme Recruiting', slug='acme-recruiting')

        db = _mock_db()
        # 1) per-user tenant count (0 owned), 2) slug uniqueness check (None = not taken)
        count_result = MagicMock(scalar=MagicMock(return_value=0))
        no_result = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        db.execute = AsyncMock(side_effect=[_admin_result(), count_result, no_result])

        # db.refresh populates the id that the DB would normally assign
        async def mock_refresh(obj):
            if hasattr(obj, 'slug'):
                obj.id = _uid()
                obj.created_at = datetime.now(timezone.utc)
                obj.active = True
                obj.max_members = 50
                obj.plan_id = 'agency'
        db.refresh = AsyncMock(side_effect=mock_refresh)

        result = await create_tenant(body=body, db=db, user_id=owner_id)

        assert result.slug == 'acme-recruiting'
        assert result.owner_id == owner_id
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_max_members_derived_from_plan_not_client(self):
        """max_members is derived server-side from plan_id, ignoring the DB default."""
        owner_id = _uid()
        body = TenantCreate(name='Uni Careers', slug='uni-careers', plan_id='university')

        db = _mock_db()
        count_result = MagicMock(scalar=MagicMock(return_value=0))
        no_result = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        db.execute = AsyncMock(side_effect=[_admin_result(), count_result, no_result])

        # db.refresh populates the DB-assigned fields the response serializer needs,
        # without clobbering the server-derived plan_id / max_members.
        async def mock_refresh(obj):
            if hasattr(obj, 'slug'):
                obj.id = _uid()
                obj.created_at = datetime.now(timezone.utc)
                obj.active = True
        db.refresh = AsyncMock(side_effect=mock_refresh)

        captured = {}

        def capture_add(obj):
            if hasattr(obj, 'slug'):
                captured['tenant'] = obj
        db.add = MagicMock(side_effect=capture_add)

        await create_tenant(body=body, db=db, user_id=owner_id)
        assert captured['tenant'].plan_id == 'university'
        assert captured['tenant'].max_members == 200

    @pytest.mark.asyncio
    async def test_unknown_plan_falls_back_to_agency(self):
        """A client-supplied plan_id outside the whitelist falls back to 'agency'."""
        owner_id = _uid()
        body = TenantCreate(name='Sneaky', slug='sneaky-org', plan_id='enterprise-unlimited')

        db = _mock_db()
        count_result = MagicMock(scalar=MagicMock(return_value=0))
        no_result = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        db.execute = AsyncMock(side_effect=[_admin_result(), count_result, no_result])

        # db.refresh populates the DB-assigned fields the response serializer needs.
        async def mock_refresh(obj):
            if hasattr(obj, 'slug'):
                obj.id = _uid()
                obj.created_at = datetime.now(timezone.utc)
                obj.active = True
        db.refresh = AsyncMock(side_effect=mock_refresh)

        captured = {}
        db.add = MagicMock(side_effect=lambda obj: captured.__setitem__('t', obj) if hasattr(obj, 'slug') else None)

        await create_tenant(body=body, db=db, user_id=owner_id)
        assert captured['t'].plan_id == 'agency'
        assert captured['t'].max_members == 50

    @pytest.mark.asyncio
    async def test_per_user_tenant_limit_enforced(self):
        """Creating more than the per-user tenant cap → 403."""
        from app.api.tenant_routes import _MAX_TENANTS_PER_USER

        owner_id = _uid()
        body = TenantCreate(name='Too Many', slug='too-many')

        db = _mock_db()
        count_result = MagicMock(scalar=MagicMock(return_value=_MAX_TENANTS_PER_USER))
        db.execute = AsyncMock(side_effect=[_admin_result(), count_result])

        with pytest.raises(HTTPException) as exc:
            await create_tenant(body=body, db=db, user_id=owner_id)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_duplicate_slug_raises_409(self):
        """Duplicate slug → HTTP 409."""
        owner_id = _uid()
        body = TenantCreate(name='Acme', slug='acme-recruiting')
        existing_tenant = make_tenant(owner_id, slug='acme-recruiting')

        db = _mock_db()
        taken_result = MagicMock()
        taken_result.scalar_one_or_none = MagicMock(return_value=existing_tenant)
        db.execute = AsyncMock(side_effect=[_admin_result(), taken_result, taken_result])

        with pytest.raises(HTTPException) as exc:
            await create_tenant(body=body, db=db, user_id=owner_id)
        assert exc.value.status_code == 409
        assert 'already taken' in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_concurrent_slug_conflict_is_stable_409(self):
        """A uniqueness race must not leak as an internal server error."""
        owner_id = _uid()
        body = TenantCreate(name='Acme', slug='acme-race')

        db = _mock_db()
        count_result = MagicMock(scalar=MagicMock(return_value=0))
        no_result = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        db.execute = AsyncMock(side_effect=[_admin_result(), count_result, no_result])
        db.commit.side_effect = IntegrityError(
            "INSERT INTO tenants", {}, Exception("duplicate key")
        )

        with pytest.raises(HTTPException) as exc:
            await create_tenant(body=body, db=db, user_id=owner_id)

        assert exc.value.status_code == 409
        db.rollback.assert_awaited_once()


# ── 85T-02  Middleware resolves from X-Tenant-Slug header ────────────────────


class TestMiddlewareSlugHeader:
    @pytest.mark.asyncio
    async def test_resolves_from_x_tenant_slug(self):
        """TenantMiddleware sets request.state.tenant when X-Tenant-Slug header is present."""
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse

        from app.middleware.tenant_middleware import TenantMiddleware

        fake_tenant = {
            'id': _uid(), 'slug': 'acme', 'name': 'Acme', 'logo_url': None,
            'primary_color': '#6d28d9', 'custom_domain': None,
            'plan_id': 'agency', 'max_members': 50,
        }

        scope = {
            'type': 'http',
            'method': 'GET',
            'path': '/ctx',
            'headers': [(b'x-tenant-slug', b'acme')],
            'query_string': b'',
        }
        request = StarletteRequest(scope)

        async def mock_call_next(req):
            return JSONResponse({'ok': True})

        with patch.object(TenantMiddleware, '_resolve_by_slug', new=AsyncMock(return_value=fake_tenant)):
            mw = TenantMiddleware(app=MagicMock())
            await mw.dispatch(request, mock_call_next)

        assert request.state.tenant is not None
        assert request.state.tenant['slug'] == 'acme'


# ── 85T-03  Middleware resolves from Host subdomain ───────────────────────────


class TestMiddlewareSubdomain:
    @pytest.mark.asyncio
    async def test_resolves_from_subdomain(self):
        """TenantMiddleware resolves slug from <slug>.latexy.io Host header."""
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse

        from app.middleware.tenant_middleware import TenantMiddleware

        fake_tenant = {
            'id': _uid(), 'slug': 'myuni', 'name': 'My University', 'logo_url': None,
            'primary_color': None, 'custom_domain': None,
            'plan_id': 'agency', 'max_members': 50,
        }

        scope = {
            'type': 'http',
            'method': 'GET',
            'path': '/ctx',
            'headers': [(b'host', b'myuni.latexy.io')],
            'query_string': b'',
        }
        request = StarletteRequest(scope)

        async def mock_call_next(req):
            return JSONResponse({'ok': True})

        with patch.object(TenantMiddleware, '_resolve_by_slug', new=AsyncMock(return_value=fake_tenant)):
            mw = TenantMiddleware(app=MagicMock())
            await mw.dispatch(request, mock_call_next)

        assert request.state.tenant is not None
        assert request.state.tenant['slug'] == 'myuni'


# ── 85T-04  Non-owner cannot PATCH → 403 ─────────────────────────────────────


class TestNonOwnerCannotPatch:
    @pytest.mark.asyncio
    async def test_non_owner_gets_403(self):
        """PATCH /tenants/{id} by a non-owner, non-admin user → 403."""
        owner_id = _uid()
        stranger_id = _uid()
        tenant = make_tenant(owner_id)

        body = TenantUpdate(name='Renamed')

        db = _mock_db()
        # First query: fetch tenant by id
        tenant_result = MagicMock()
        tenant_result.scalar_one_or_none = MagicMock(return_value=tenant)
        # Second query: membership check (no admin row)
        no_member = MagicMock()
        no_member.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(side_effect=[tenant_result, no_member])

        with pytest.raises(HTTPException) as exc:
            await update_tenant(tenant_id=tenant.id, body=body, db=db, user_id=stranger_id)
        assert exc.value.status_code == 403


# ── 85T-05  Invite member → TenantMember row created ─────────────────────────


class TestInviteMember:
    @pytest.mark.asyncio
    async def test_invite_member_created(self):
        """POST creates a pending token and does not grant membership."""
        owner_id = _uid()
        invitee = make_user()
        tenant = make_tenant(owner_id)

        body = InviteRequest(email=invitee.email, role='member')

        db = _mock_db()
        # db.execute calls: find invitee user, count members, existing membership check
        user_result = MagicMock(scalar_one_or_none=MagicMock(return_value=invitee))
        count_result = MagicMock(scalar=MagicMock(return_value=1))
        existing_result = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

        db.execute = AsyncMock(side_effect=[user_result, count_result, existing_result])

        redis = AsyncMock()
        with (
            patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)),
            patch('app.api.tenant_routes.get_redis_cache_client', new=AsyncMock(return_value=redis)),
            patch('app.api.tenant_routes.email_service.send_email', new=AsyncMock(return_value=True)),
            patch('app.api.tenant_routes.secrets.token_urlsafe', return_value='safe-token'),
        ):
            result = await invite_member(tenant_id=tenant.id, body=body, db=db, user_id=owner_id)

        assert result.email == invitee.email
        assert result.role == 'member'
        redis.set.assert_awaited_once_with(
            'tenant_invite:safe-token',
            json.dumps(
                {
                    'tenant_id': tenant.id,
                    'role': 'member',
                    'email': invitee.email,
                    'cohort_id': None,
                },
                separators=(',', ':'),
            ),
            ex=7 * 24 * 3600,
        )
        db.add.assert_not_called()
        db.commit.assert_not_called()


# ── 85T-06  Remove member → row deleted ──────────────────────────────────────


class TestRemoveMember:
    @pytest.mark.asyncio
    async def test_remove_member_deleted(self):
        """DELETE /tenants/{id}/members/{user_id} → member row deleted, 204."""
        owner_id = _uid()
        target_id = _uid()
        tenant = make_tenant(owner_id)
        member_row = make_member(tenant.id, target_id)

        db = _mock_db()
        member_result = MagicMock(scalar_one_or_none=MagicMock(return_value=member_row))
        db.execute = AsyncMock(return_value=member_result)

        with patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)):
            await remove_member(tenant_id=tenant.id, target_user_id=target_id, db=db, user_id=owner_id)

        db.delete.assert_called_once_with(member_row)
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_nonexistent_member_raises_404(self):
        """DELETE on a non-existent member → 404."""
        owner_id = _uid()
        tenant = make_tenant(owner_id)

        db = _mock_db()
        no_result = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        db.execute = AsyncMock(return_value=no_result)

        with patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)):
            with pytest.raises(HTTPException) as exc:
                await remove_member(tenant_id=tenant.id, target_user_id=_uid(), db=db, user_id=owner_id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cannot_remove_owner(self):
        """Removing the tenant owner's own membership → 403."""
        owner_id = _uid()
        tenant = make_tenant(owner_id)

        db = _mock_db()
        with patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)):
            with pytest.raises(HTTPException) as exc:
                await remove_member(tenant_id=tenant.id, target_user_id=owner_id, db=db, user_id=owner_id)
        assert exc.value.status_code == 403
        db.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_cannot_remove_another_admin(self):
        """A non-owner admin cannot remove another admin → 403."""
        owner_id = _uid()
        admin_caller = _uid()
        target_admin = _uid()
        tenant = make_tenant(owner_id)
        target_row = make_member(tenant.id, target_admin, role='admin')

        db = _mock_db()
        member_result = MagicMock(scalar_one_or_none=MagicMock(return_value=target_row))
        db.execute = AsyncMock(return_value=member_result)

        with patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)):
            with pytest.raises(HTTPException) as exc:
                await remove_member(
                    tenant_id=tenant.id, target_user_id=target_admin, db=db, user_id=admin_caller
                )
        assert exc.value.status_code == 403
        db.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_owner_can_remove_admin(self):
        """The owner can remove an admin member → 204."""
        owner_id = _uid()
        target_admin = _uid()
        tenant = make_tenant(owner_id)
        target_row = make_member(tenant.id, target_admin, role='admin')

        db = _mock_db()
        member_result = MagicMock(scalar_one_or_none=MagicMock(return_value=target_row))
        db.execute = AsyncMock(return_value=member_result)

        with patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)):
            await remove_member(
                tenant_id=tenant.id, target_user_id=target_admin, db=db, user_id=owner_id
            )
        db.delete.assert_called_once_with(target_row)


# ── Member-limit and domain-uniqueness edge cases ─────────────────────────────


class TestInviteMemberLimit:
    @pytest.mark.asyncio
    async def test_member_limit_returns_409(self):
        """Reaching max_members returns 409 (capacity), not 429 (rate limit)."""
        owner_id = _uid()
        invitee = make_user()
        tenant = make_tenant(owner_id)
        tenant.max_members = 2

        body = InviteRequest(email=invitee.email, role='member')

        db = _mock_db()
        user_result = MagicMock(scalar_one_or_none=MagicMock(return_value=invitee))
        count_result = MagicMock(scalar=MagicMock(return_value=2))
        db.execute = AsyncMock(side_effect=[user_result, count_result])

        with patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)):
            with pytest.raises(HTTPException) as exc:
                await invite_member(tenant_id=tenant.id, body=body, db=db, user_id=owner_id)
        assert exc.value.status_code == 409


class TestCustomDomainUniqueness:
    @pytest.mark.asyncio
    async def test_domain_clash_returns_409(self):
        """PATCH custom_domain already claimed by another tenant → 409."""
        owner_id = _uid()
        tenant = make_tenant(owner_id, custom_domain=None)
        other = make_tenant(_uid(), slug='other', custom_domain='resumes.acme.com')

        body = TenantUpdate(custom_domain='resumes.acme.com')

        db = _mock_db()
        clash_result = MagicMock(scalar_one_or_none=MagicMock(return_value=other))
        db.execute = AsyncMock(return_value=clash_result)

        with patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)):
            with pytest.raises(HTTPException) as exc:
                await update_tenant(tenant_id=tenant.id, body=body, db=db, user_id=owner_id)
        assert exc.value.status_code == 409
        db.commit.assert_not_called()


# ── 85T-07  Stats returns correct member count ────────────────────────────────


class TestTenantStats:
    @pytest.mark.asyncio
    async def test_stats_member_count(self):
        """GET /tenants/{id}/stats → correct member_count."""
        owner_id = _uid()
        tenant = make_tenant(owner_id)

        db = _mock_db()
        count_result = MagicMock(scalar=MagicMock(return_value=3))
        db.execute = AsyncMock(side_effect=[count_result])

        with patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)):
            result = await tenant_stats(tenant_id=tenant.id, db=db, user_id=owner_id)

        assert result.member_count == 3
        assert not hasattr(result, 'total_resumes')
        assert db.execute.await_count == 1


# ── 85T-08  Custom domain stored via PATCH ────────────────────────────────────


class TestCustomDomain:
    @pytest.mark.asyncio
    async def test_custom_domain_patch(self):
        """PATCH /tenants/{id} with custom_domain → stored correctly."""
        owner_id = _uid()
        tenant = make_tenant(owner_id, custom_domain=None)

        body = TenantUpdate(custom_domain='resumes.acme.com')

        db = _mock_db()
        # Domain-uniqueness pre-check returns no clashing tenant
        no_clash = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        db.execute = AsyncMock(return_value=no_clash)
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        with patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)):
            await update_tenant(tenant_id=tenant.id, body=body, db=db, user_id=owner_id)

        assert tenant.custom_domain == 'resumes.acme.com'
        db.commit.assert_called_once()


# ── 85T-09  Invalid hex color → 422 ──────────────────────────────────────────


class TestColorValidation:
    def test_invalid_hex_color_raises(self):
        """primary_color: 'not-a-hex' → Pydantic ValidationError (HTTP 422)."""
        import pydantic
        with pytest.raises(pydantic.ValidationError) as exc:
            TenantCreate(name='Acme', slug='acme', primary_color='not-a-hex')
        errors = exc.value.errors()
        assert any('primary_color' in str(e) for e in errors)

    def test_valid_hex_color_accepted(self):
        """primary_color: '#6d28d9' → valid."""
        body = TenantCreate(name='Acme', slug='acme', primary_color='#6d28d9')
        assert body.primary_color == '#6d28d9'

    def test_short_hex_rejected(self):
        """primary_color: '#fff' (3-char) → ValidationError."""
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            TenantCreate(name='Acme', slug='acme', primary_color='#fff')


class TestLogoUrlValidation:
    @pytest.mark.parametrize("schema", [TenantCreate, TenantUpdate])
    @pytest.mark.parametrize(
        "url",
        ["javascript:alert(1)", "data:image/svg+xml,<svg/>", "file:///etc/passwd"],
    )
    def test_rejects_non_http_logo_urls(self, schema, url):
        import pydantic

        fields = {"name": "Acme", "slug": "acme", "logo_url": url}
        if schema is TenantUpdate:
            fields = {"logo_url": url}
        with pytest.raises(pydantic.ValidationError):
            schema(**fields)

    @pytest.mark.parametrize("schema", [TenantCreate, TenantUpdate])
    @pytest.mark.parametrize(
        "url",
        [
            "http://cdn.example.com/logo.png",
            "https://localhost/logo.png",
            "https://127.0.0.1/logo.png",
            "https://10.0.0.1/logo.png",
            "https://metadata.internal/logo.png",
        ],
    )
    def test_rejects_insecure_or_local_network_logo_urls(self, schema, url):
        import pydantic

        fields = {"name": "Acme", "slug": "acme", "logo_url": url}
        if schema is TenantUpdate:
            fields = {"logo_url": url}
        with pytest.raises(pydantic.ValidationError):
            schema(**fields)

    @pytest.mark.parametrize("schema", [TenantCreate, TenantUpdate])
    def test_accepts_and_normalizes_https_logo_url(self, schema):
        fields = {
            "name": "Acme",
            "slug": "acme",
            "logo_url": "https://cdn.example.com/logo.png",
        }
        if schema is TenantUpdate:
            fields = {"logo_url": "https://cdn.example.com/logo.png"}
        body = schema(**fields)
        assert body.logo_url == "https://cdn.example.com/logo.png"


# ── 85T-10  GET /tenants/my returns owned + member-of ────────────────────────


class TestListMyTenants:
    @pytest.mark.asyncio
    async def test_list_my_tenants_includes_member_of(self):
        """GET /tenants/my returns tenants owned and tenants where user is a member."""
        user_id = _uid()
        owned = make_tenant(user_id, slug='owned-one')
        other_owner = _uid()
        membered = make_tenant(other_owner, slug='membered-org')
        membership = make_member(membered.id, user_id)

        db = _mock_db()
        # 1) Owned tenants query
        owned_result = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[owned]))))
        # 2) TenantMember query (memberships)
        member_result = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[membership]))))
        # 3) Bulk-fetch membered tenants by id (uses .scalars().all())
        membered_result = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[membered]))))

        db.execute = AsyncMock(side_effect=[owned_result, member_result, membered_result])

        result = await list_my_tenants(db=db, user_id=user_id)
        slugs = {r.slug for r in result}
        assert 'owned-one' in slugs
        assert 'membered-org' in slugs


# ── 85T-11  /current-context returns None when no tenant ─────────────────────


class TestCurrentContext:
    @pytest.mark.asyncio
    async def test_no_tenant_returns_none(self):
        """GET /tenants/current-context → tenant: None when middleware resolved nothing."""
        from starlette.requests import Request as StarletteRequest

        from app.api.tenant_routes import current_context

        scope = {
            'type': 'http',
            'method': 'GET',
            'path': '/tenants/current-context',
            'headers': [],
            'query_string': b'',
        }
        request = StarletteRequest(scope)
        request.state.tenant = None

        result = await current_context(request=request)
        assert result.tenant is None

    @pytest.mark.asyncio
    async def test_tenant_in_state_returned(self):
        """GET /tenants/current-context → returns tenant dict from request.state."""
        from starlette.requests import Request as StarletteRequest

        from app.api.tenant_routes import current_context

        scope = {
            'type': 'http',
            'method': 'GET',
            'path': '/tenants/current-context',
            'headers': [],
            'query_string': b'',
        }
        request = StarletteRequest(scope)
        request.state.tenant = {
            'id': _uid(), 'slug': 'demo', 'name': 'Demo Corp',
            'logo_url': None, 'primary_color': '#ff0000',
            'custom_domain': None, 'plan_id': 'agency', 'max_members': 50,
        }

        result = await current_context(request=request)
        assert result.tenant is not None
        assert result.tenant['slug'] == 'demo'


# ── 85T-12  list_members requires membership ──────────────────────────────────


class TestListMembersAuth:
    @pytest.mark.asyncio
    async def test_non_member_gets_403(self):
        """GET /tenants/{id}/members by a non-member → 403."""
        owner_id = _uid()
        stranger_id = _uid()
        tenant = make_tenant(owner_id)

        db = _mock_db()
        tenant_result = MagicMock(scalar_one_or_none=MagicMock(return_value=tenant))
        no_membership = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        db.execute = AsyncMock(side_effect=[tenant_result, no_membership])

        with pytest.raises(HTTPException) as exc:
            await list_members(tenant_id=tenant.id, db=db, user_id=stranger_id)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_member_can_list(self):
        """GET /tenants/{id}/members by a member → returns member list."""
        owner_id = _uid()
        member_user = make_user()
        tenant = make_tenant(owner_id)
        membership = make_member(tenant.id, member_user.id)

        db = _mock_db()
        tenant_result = MagicMock(scalar_one_or_none=MagicMock(return_value=tenant))
        membership_result = MagicMock(scalar_one_or_none=MagicMock(return_value=membership))
        # Implementation uses a JOIN query → result.all() returns (TenantMember, User) tuples
        members_list = MagicMock(all=MagicMock(return_value=[(membership, member_user)]))

        db.execute = AsyncMock(side_effect=[tenant_result, membership_result, members_list])

        result = await list_members(tenant_id=tenant.id, db=db, user_id=member_user.id)
        assert len(result) == 1
        assert result[0].user_id == member_user.id


# ── BUG-03 (F85): PATCH /tenants/{id} can clear optional branding fields ──────


class TestUpdateTenantNullClearing:
    """Tests for BUG-03: update_tenant PATCH must clear nullable fields when sent as null."""

    def test_exclude_unset_includes_explicit_none(self):
        """TenantUpdate.model_dump(exclude_unset=True) includes fields explicitly set to null."""
        body = TenantUpdate.model_validate({'logo_url': None})
        dumped = body.model_dump(exclude_unset=True)
        assert 'logo_url' in dumped
        assert dumped['logo_url'] is None

    def test_exclude_unset_omits_missing_fields(self):
        """TenantUpdate.model_dump(exclude_unset=True) omits fields absent from request."""
        body = TenantUpdate.model_validate({'name': 'New Name'})
        dumped = body.model_dump(exclude_unset=True)
        assert 'name' in dumped
        assert 'logo_url' not in dumped

    @pytest.mark.asyncio
    async def test_null_logo_url_clears_field(self):
        """PATCH with logo_url=null clears the tenant's logo_url (BUG-03 fix)."""
        owner_id = _uid()
        tenant = make_tenant(owner_id)
        tenant.logo_url = 'https://old.example.com/logo.png'

        # Simulate JSON body: {"logo_url": null}
        body = TenantUpdate.model_validate({'logo_url': None})

        db = _mock_db()
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        with patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)):
            await update_tenant(tenant_id=tenant.id, body=body, db=db, user_id=owner_id)

        assert tenant.logo_url is None
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_null_primary_color_clears_field(self):
        """PATCH with primary_color=null clears the tenant's primary_color (BUG-03 fix)."""
        owner_id = _uid()
        tenant = make_tenant(owner_id, primary_color='#6d28d9')

        body = TenantUpdate.model_validate({'primary_color': None})

        db = _mock_db()
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        with patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)):
            await update_tenant(tenant_id=tenant.id, body=body, db=db, user_id=owner_id)

        assert tenant.primary_color is None


# ── Institutional tenancy security contracts ────────────────────────────────


class TestTenantProvisioningGate:
    @pytest.mark.asyncio
    async def test_free_user_cannot_self_provision_enterprise_tenant(self):
        body = TenantCreate(name='Free Org', slug='free-org')
        db = _mock_db()
        row = MagicMock(role='user', subscription_plan='free')
        db.execute = AsyncMock(
            return_value=MagicMock(one_or_none=MagicMock(return_value=row))
        )

        with pytest.raises(HTTPException) as exc:
            await create_tenant(body=body, db=db, user_id=_uid())

        assert exc.value.status_code == 403
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_team_user_cannot_self_provision_university_plan(self):
        body = TenantCreate(name='University', slug='a-university', plan_id='university')
        db = _mock_db()
        row = MagicMock(role='user', subscription_plan='team')
        db.execute = AsyncMock(
            return_value=MagicMock(one_or_none=MagicMock(return_value=row))
        )

        with pytest.raises(HTTPException) as exc:
            await create_tenant(body=body, db=db, user_id=_uid())

        assert exc.value.status_code == 403
        assert 'administrator' in exc.value.detail.lower()


class TestTenantInvitationSecurity:
    @pytest.mark.asyncio
    async def test_admin_cannot_invite_peer_admin(self):
        owner_id = _uid()
        caller_id = _uid()
        tenant = make_tenant(owner_id)
        db = _mock_db()

        with (
            patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)),
            pytest.raises(HTTPException) as exc,
        ):
            await invite_member(
                tenant_id=tenant.id,
                body=InviteRequest(email='person@example.com', role='admin'),
                db=db,
                user_id=caller_id,
            )

        assert exc.value.status_code == 403
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_accept_is_email_bound_and_single_use(self):
        user = make_user('invitee@example.com')
        tenant = make_tenant(_uid())
        db = _mock_db()
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps({
            'tenant_id': tenant.id,
            'role': 'member',
            'email': user.email,
            'cohort_id': None,
        }))
        user_result = MagicMock(scalar_one_or_none=MagicMock(return_value=user))
        tenant_result = MagicMock(scalar_one_or_none=MagicMock(return_value=tenant))
        count_result = MagicMock(scalar=MagicMock(return_value=1))
        no_member = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        db.execute = AsyncMock(side_effect=[user_result, tenant_result, count_result, no_member])

        async def refresh(member):
            member.joined_at = datetime.now(timezone.utc)

        db.refresh = AsyncMock(side_effect=refresh)
        with patch(
            'app.api.tenant_routes.get_redis_cache_client',
            new=AsyncMock(return_value=redis),
        ):
            result = await accept_invitation(
                token='token', db=db, user_id=user.id
            )

        assert result.email == user.email
        assert result.role == 'member'
        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        redis.delete.assert_awaited_once_with('tenant_invite:token')

    @pytest.mark.asyncio
    async def test_accept_rejects_different_account_email(self):
        user = make_user('attacker@example.com')
        tenant_id = _uid()
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps({
            'tenant_id': tenant_id,
            'role': 'member',
            'email': 'victim@example.com',
            'cohort_id': None,
        }))
        db = _mock_db()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=user))
        )

        with (
            patch('app.api.tenant_routes.get_redis_cache_client', new=AsyncMock(return_value=redis)),
            pytest.raises(HTTPException) as exc,
        ):
            await accept_invitation(token='token', db=db, user_id=user.id)

        assert exc.value.status_code == 403
        db.add.assert_not_called()
        redis.delete.assert_not_awaited()


class TestLeaveTenant:
    @pytest.mark.asyncio
    async def test_member_can_leave(self):
        member_id = _uid()
        tenant = make_tenant(_uid())
        member = make_member(tenant.id, member_id)
        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=tenant)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=member)),
                MagicMock(
                    scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
                ),
            ]
        )

        await leave_tenant(tenant_id=tenant.id, db=db, user_id=member_id)

        db.delete.assert_awaited_once_with(member)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_owner_cannot_leave(self):
        owner_id = _uid()
        tenant = make_tenant(owner_id)
        db = _mock_db()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=tenant))
        )

        with pytest.raises(HTTPException) as exc:
            await leave_tenant(tenant_id=tenant.id, db=db, user_id=owner_id)

        assert exc.value.status_code == 403


class TestDomainOwnershipVerification:
    def test_domain_is_normalized_and_first_party_hosts_are_rejected(self):
        assert TenantUpdate(custom_domain='CV.Example.edu.').custom_domain == 'cv.example.edu'
        with pytest.raises(ValueError):
            TenantUpdate(custom_domain='latexy.xyz')
        with pytest.raises(ValueError):
            TenantUpdate(custom_domain='evil.vercel.app')
        with pytest.raises(ValueError):
            TenantUpdate(custom_domain='https://example.edu/path')

    @pytest.mark.asyncio
    async def test_dns_proof_activates_domain_and_invalidates_cache(self):
        owner_id = _uid()
        tenant = make_tenant(owner_id, custom_domain='cv.example.edu')
        db = _mock_db()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            'Answer': [{'type': 16, 'data': f'"latexy-verify={tenant.id}"'}]
        }
        client = AsyncMock()
        client.get = AsyncMock(return_value=response)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=None)

        with (
            patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)),
            patch('app.api.tenant_routes.httpx.AsyncClient', return_value=context),
            patch('app.api.tenant_routes.invalidate_tenant_cache', new=AsyncMock()) as invalidate,
        ):
            result = await verify_domain(tenant_id=tenant.id, db=db, user_id=owner_id)

        assert result['verified'] is True
        assert tenant.domain_verified_at is not None
        db.commit.assert_awaited_once()
        invalidate.assert_awaited_once_with(
            slug=tenant.slug, current_domain=tenant.custom_domain
        )

    @pytest.mark.asyncio
    async def test_missing_dns_proof_keeps_domain_inactive(self):
        tenant = make_tenant(_uid(), custom_domain='cv.example.edu')
        db = _mock_db()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {'Answer': []}
        client = AsyncMock()
        client.get = AsyncMock(return_value=response)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=None)

        with (
            patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)),
            patch('app.api.tenant_routes.httpx.AsyncClient', return_value=context),
        ):
            result = await verify_domain(tenant_id=tenant.id, db=db, user_id=tenant.owner_id)

        assert result['verified'] is False
        assert tenant.domain_verified_at is None
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_removed_dns_proof_revokes_previously_verified_domain(self):
        tenant = make_tenant(_uid(), custom_domain='cv.example.edu')
        tenant.domain_verified_at = datetime.now(timezone.utc)
        db = _mock_db()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {'Answer': []}
        client = AsyncMock()
        client.get = AsyncMock(return_value=response)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=None)

        with (
            patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)),
            patch('app.api.tenant_routes.httpx.AsyncClient', return_value=context),
            patch('app.api.tenant_routes.invalidate_tenant_cache', new=AsyncMock()) as invalidate,
        ):
            result = await verify_domain(tenant_id=tenant.id, db=db, user_id=tenant.owner_id)

        assert result['verified'] is False
        assert tenant.domain_verified_at is None
        db.commit.assert_awaited_once()
        invalidate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dns_provider_failure_is_retryable_without_changing_state(self):
        tenant = make_tenant(_uid(), custom_domain='cv.example.edu')
        tenant.domain_verified_at = datetime.now(timezone.utc)
        db = _mock_db()
        context = MagicMock()
        context.__aenter__ = AsyncMock(side_effect=httpx.ConnectError('offline'))
        context.__aexit__ = AsyncMock(return_value=None)

        with (
            patch('app.api.tenant_routes._require_tenant_owner_or_admin', new=AsyncMock(return_value=tenant)),
            patch('app.api.tenant_routes.httpx.AsyncClient', return_value=context),
            pytest.raises(HTTPException) as exc,
        ):
            await verify_domain(tenant_id=tenant.id, db=db, user_id=tenant.owner_id)

        assert exc.value.status_code == 503
        assert tenant.domain_verified_at is not None
        db.commit.assert_not_awaited()


class TestVerifiedTenantCors:
    @pytest.mark.asyncio
    async def test_verified_tenant_origin_receives_credentialed_cors(self):
        from starlette.requests import Request as StarletteRequest

        from app.middleware.tenant_middleware import VerifiedTenantCORSMiddleware

        scope = {
            'type': 'http',
            'method': 'OPTIONS',
            'path': '/tenants/my',
            'headers': [
                (b'origin', b'https://cv.example.edu'),
                (b'access-control-request-method', b'GET'),
                (b'access-control-request-headers', b'authorization,x-tenant-slug'),
            ],
            'query_string': b'',
        }
        request = StarletteRequest(scope)
        next_handler = AsyncMock()
        with patch(
            'app.middleware.tenant_middleware.resolve_tenant_origin_hostname',
            new=AsyncMock(return_value={'slug': 'example'}),
        ):
            response = await VerifiedTenantCORSMiddleware(MagicMock()).dispatch(
                request, next_handler
            )

        assert response.status_code == 200
        assert response.headers['access-control-allow-origin'] == 'https://cv.example.edu'
        assert response.headers['access-control-allow-credentials'] == 'true'
        next_handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unverified_origin_is_not_dynamically_allowed(self):
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import Response

        from app.middleware.tenant_middleware import VerifiedTenantCORSMiddleware

        request = StarletteRequest({
            'type': 'http',
            'method': 'GET',
            'path': '/health',
            'headers': [(b'origin', b'https://attacker.example')],
            'query_string': b'',
        })
        next_handler = AsyncMock(return_value=Response(status_code=200))
        with patch(
            'app.middleware.tenant_middleware.resolve_tenant_origin_hostname',
            new=AsyncMock(return_value=None),
        ):
            response = await VerifiedTenantCORSMiddleware(MagicMock()).dispatch(
                request, next_handler
            )

        assert 'access-control-allow-origin' not in response.headers
        next_handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unapproved_preflight_header_is_rejected(self):
        from starlette.requests import Request as StarletteRequest

        from app.middleware.tenant_middleware import VerifiedTenantCORSMiddleware

        request = StarletteRequest({
            'type': 'http',
            'method': 'OPTIONS',
            'path': '/health',
            'headers': [
                (b'origin', b'https://cv.example.edu'),
                (b'access-control-request-method', b'GET'),
                (b'access-control-request-headers', b'x-unapproved'),
            ],
            'query_string': b'',
        })
        with patch(
            'app.middleware.tenant_middleware.resolve_tenant_origin_hostname',
            new=AsyncMock(return_value={'slug': 'example'}),
        ):
            response = await VerifiedTenantCORSMiddleware(MagicMock()).dispatch(
                request, AsyncMock()
            )

        assert response.status_code == 400


class TestTenantNegativeCache:
    @pytest.mark.asyncio
    async def test_domain_resolver_uses_runtime_session_factory(self):
        """The resolver must not capture ``SessionLocal=None`` at import time."""
        from app.middleware import tenant_middleware

        domain = f"missing-{uuid.uuid4().hex}.example"

        class Result:
            @staticmethod
            def scalar_one_or_none():
                return None

        class Session:
            async def execute(self, _statement):
                return Result()

        @asynccontextmanager
        async def session_context():
            yield Session()

        with patch.object(tenant_middleware, 'get_async_db_session', session_context):
            result = await tenant_middleware.resolve_verified_tenant_domain(domain)

        assert result is None
        tenant_middleware._INPROC_CACHE.pop(f'tenant:domain:{domain}', None)

    @pytest.mark.asyncio
    async def test_negative_domain_cache_prevents_repeated_database_lookup(self):
        import time

        from app.middleware import tenant_middleware

        key = 'tenant:domain:missing.example'
        tenant_middleware._INPROC_CACHE[key] = (None, time.monotonic() + 30)
        session_factory = MagicMock()
        try:
            with patch.object(tenant_middleware, 'get_async_db_session', session_factory):
                result = await tenant_middleware.resolve_verified_tenant_domain(
                    'missing.example'
                )
            assert result is None
            session_factory.assert_not_called()
        finally:
            tenant_middleware._INPROC_CACHE.pop(key, None)


@pytest.mark.asyncio
class TestCohortInvitationIntegration:
    async def test_invited_student_accepts_into_tenant_and_cohort(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict,
        auth_headers2: dict,
    ):
        async def user_for(headers: dict) -> tuple[str, str]:
            token = headers['Authorization'].removeprefix('Bearer ')
            row = await db_session.execute(
                text(
                    'SELECT u.id, u.email FROM users u JOIN session s '
                    'ON s."userId"::uuid = u.id WHERE s.token = :token'
                ),
                {'token': token},
            )
            user_id, email = row.one()
            return str(user_id), str(email)

        owner_id, _ = await user_for(auth_headers)
        student_id, student_email = await user_for(auth_headers2)
        tenant_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO tenants (id, slug, name, owner_id, plan_id, max_members) "
                "VALUES (:id, :slug, 'Test Careers Centre', :owner, 'university', 200)"
            ),
            {'id': tenant_id, 'slug': f'test-{uuid.uuid4().hex[:10]}', 'owner': owner_id},
        )
        await db_session.execute(
            text(
                "INSERT INTO tenant_members (tenant_id, user_id, role) "
                "VALUES (:tenant, :owner, 'admin')"
            ),
            {'tenant': tenant_id, 'owner': owner_id},
        )
        await db_session.commit()

        created = await client.post(
            f'/tenants/{tenant_id}/cohorts',
            headers=auth_headers,
            json={'name': 'Class of 2027'},
        )
        assert created.status_code == 201, created.text
        cohort_id = created.json()['id']

        invitation = await client.post(
            f'/tenants/{tenant_id}/members/invite',
            headers=auth_headers,
            json={'email': student_email, 'role': 'member', 'cohort_id': cohort_id},
        )
        assert invitation.status_code == 201, invitation.text
        preview_url = invitation.json()['invite_preview_url']
        assert preview_url
        token = parse_qs(urlsplit(preview_url).query)['token'][0]

        accepted = await client.post(
            f'/tenants/invitations/{token}/accept', headers=auth_headers2
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()['user_id'] == student_id

        rows = await db_session.execute(
            text(
                "SELECT tm.role, wm.role FROM tenant_members tm "
                "JOIN workspace_members wm ON wm.user_id = tm.user_id "
                "WHERE tm.tenant_id = :tenant AND tm.user_id = :student "
                "AND wm.workspace_id = :cohort"
            ),
            {'tenant': tenant_id, 'student': student_id, 'cohort': cohort_id},
        )
        assert rows.one() == ('member', 'viewer')

        replay = await client.post(
            f'/tenants/invitations/{token}/accept', headers=auth_headers2
        )
        assert replay.status_code == 404

        listed = await client.get(
            f'/tenants/{tenant_id}/cohorts', headers=auth_headers
        )
        assert listed.status_code == 200
        assert listed.json()[0]['member_count'] == 2

        left = await client.delete(
            f'/tenants/{tenant_id}/membership', headers=auth_headers2
        )
        assert left.status_code == 204
        remaining = await db_session.execute(
            text(
                'SELECT count(*) FROM workspace_members '
                'WHERE workspace_id = :cohort AND user_id = :student'
            ),
            {'cohort': cohort_id, 'student': student_id},
        )
        assert remaining.scalar_one() == 0

    async def test_new_tenant_admin_is_added_to_existing_cohort_as_editor(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict,
        auth_headers2: dict,
    ):
        async def user_for(headers: dict) -> tuple[str, str]:
            token = headers['Authorization'].removeprefix('Bearer ')
            row = await db_session.execute(
                text(
                    'SELECT u.id, u.email FROM users u JOIN session s '
                    'ON s."userId"::uuid = u.id WHERE s.token = :token'
                ),
                {'token': token},
            )
            user_id, email = row.one()
            return str(user_id), str(email)

        owner_id, _ = await user_for(auth_headers)
        admin_id, admin_email = await user_for(auth_headers2)
        tenant_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO tenants (id, slug, name, owner_id, plan_id, max_members) "
                "VALUES (:id, :slug, 'Admin Access Test', :owner, 'university', 200)"
            ),
            {'id': tenant_id, 'slug': f'test-{uuid.uuid4().hex[:10]}', 'owner': owner_id},
        )
        await db_session.execute(
            text(
                "INSERT INTO tenant_members (tenant_id, user_id, role) "
                "VALUES (:tenant, :owner, 'admin')"
            ),
            {'tenant': tenant_id, 'owner': owner_id},
        )
        await db_session.commit()
        cohort = await client.post(
            f'/tenants/{tenant_id}/cohorts', headers=auth_headers, json={'name': 'Admin Cohort'}
        )
        assert cohort.status_code == 201, cohort.text

        invitation = await client.post(
            f'/tenants/{tenant_id}/members/invite',
            headers=auth_headers,
            json={'email': admin_email, 'role': 'admin'},
        )
        token = parse_qs(urlsplit(invitation.json()['invite_preview_url']).query)['token'][0]
        accepted = await client.post(
            f'/tenants/invitations/{token}/accept', headers=auth_headers2
        )
        assert accepted.status_code == 200, accepted.text

        role = await db_session.execute(
            text(
                'SELECT role FROM workspace_members '
                'WHERE workspace_id = :cohort AND user_id = :admin'
            ),
            {'cohort': cohort.json()['id'], 'admin': admin_id},
        )
        assert role.scalar_one() == 'editor'
        detail = await client.get(
            f"/workspaces/{cohort.json()['id']}", headers=auth_headers2
        )
        assert detail.status_code == 200
