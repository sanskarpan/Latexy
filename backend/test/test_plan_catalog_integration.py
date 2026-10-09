"""Database/API catalog regression tests; no live payment provider is used."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PlanCatalog, PlanCatalogRevision, Subscription, User
from app.services.plan_catalog_service import PlanCatalogService


@pytest.fixture(autouse=True)
async def clean_catalog(db_session: AsyncSession):
    # This dedicated local test DB has no production subscriptions or catalog.
    await db_session.execute(delete(PlanCatalogRevision))
    await db_session.execute(delete(PlanCatalog))
    await db_session.commit()
    yield
    await db_session.rollback()
    await db_session.execute(delete(PlanCatalogRevision))
    await db_session.execute(delete(PlanCatalog))
    await db_session.commit()


async def headers(db, role="admin"):
    user_id = str(uuid4())
    token = f"test_catalog_{uuid4().hex}"
    db.add(User(id=user_id, email=f"test_{uuid4().hex}@example.com", name="Catalog Test", role=role, subscription_plan="pro", subscription_status="active"))
    await db.commit()
    await db.execute(text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'), {
        "id": str(uuid4()), "uid": user_id, "exp": datetime.now(timezone.utc) + timedelta(days=1), "tok": token,
    })
    await db.commit()
    return user_id, {"Authorization": f"Bearer {token}"}


async def test_admin_catalog_roundtrip_and_public_consistency(client: AsyncClient, db_session: AsyncSession):
    admin_id, auth = await headers(db_session)
    response = await client.patch("/admin/plan-catalog/pro", json={"version": 1, "name": "Professional", "description": "One coherent catalog", "display_order": 1}, headers=auth)
    assert response.status_code == 200, response.text
    admin_plan = response.json()["plans"]["pro"]
    assert admin_plan["version"] == 2
    public = await client.get("/subscription/plans")
    assert public.status_code == 200, public.text
    public_plan = public.json()["plans"]["pro"]
    for field in ("name", "description", "price", "currency", "features", "capabilities"):
        assert public_plan[field] == admin_plan[field]
    revision = (await db_session.execute(select(PlanCatalogRevision).where(PlanCatalogRevision.sku == "pro"))).scalar_one()
    assert revision.changed_by == admin_id
    assert revision.snapshot["name"] == "Professional"


async def test_stale_update_rejected_and_free_recovery_preserved(client: AsyncClient, db_session: AsyncSession):
    _, auth = await headers(db_session)
    first = await client.patch("/admin/plan-catalog/pro", json={"version": 1, "name": "Current"}, headers=auth)
    assert first.status_code == 200, first.text
    stale = await client.patch("/admin/plan-catalog/pro", json={"version": 1, "name": "Stale"}, headers=auth)
    assert stale.status_code == 409
    free = await client.patch("/admin/plan-catalog/free", json={"version": 1, "purchase_enabled": False}, headers=auth)
    assert free.status_code == 422
    unknown = await client.patch("/admin/plan-catalog/made_up", json={"version": 1, "name": "Unknown"}, headers=auth)
    assert unknown.status_code == 404
    price = await client.patch("/admin/plan-catalog/pro", json={"version": 2, "price": 1}, headers=auth)
    assert price.status_code == 422


async def test_non_admin_cannot_read_or_change_catalog(client: AsyncClient, db_session: AsyncSession):
    _, auth = await headers(db_session, "user")
    response = await client.get("/admin/plan-catalog", headers=auth)
    assert response.status_code == 403
    response = await client.patch("/admin/plan-catalog/pro", json={"version": 1, "purchase_enabled": False}, headers=auth)
    assert response.status_code == 403


async def test_retired_sku_preserves_existing_subscription_and_entitlement(db_session: AsyncSession):
    admin_id, _ = await headers(db_session)
    customer = User(id=str(uuid4()), email=f"test_{uuid4().hex}@example.com", subscription_plan="pro", subscription_status="active", subscription_id="sub_test_existing")
    db_session.add(customer)
    await db_session.flush()
    subscription = Subscription(user_id=customer.id, plan_id="pro", razorpay_subscription_id="sub_test_existing", status="active", current_period_start=datetime.now(timezone.utc), current_period_end=datetime.now(timezone.utc) + timedelta(days=30))
    db_session.add(subscription)
    await db_session.commit()
    original_end = subscription.current_period_end
    await PlanCatalogService().update(db_session, "pro", {"purchase_enabled": False, "visible": False}, version=1, admin_id=admin_id)
    await db_session.refresh(customer)
    await db_session.refresh(subscription)
    assert customer.subscription_plan == "pro"
    assert customer.subscription_id == "sub_test_existing"
    assert subscription.status == "active"
    assert subscription.plan_id == "pro"
    assert subscription.current_period_end == original_end


async def test_paused_plan_blocks_direct_checkout_and_student_verification(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    from unittest.mock import AsyncMock

    from app.services.feature_flag_service import feature_flag_service
    from app.services.payment_service import payment_service

    admin_id, auth = await headers(db_session)
    service = PlanCatalogService()
    await service.update(db_session, "pro", {"purchase_enabled": False}, version=1, admin_id=admin_id)
    await service.update(db_session, "student", {"purchase_enabled": False}, version=1, admin_id=admin_id)
    provider_checkout = AsyncMock()
    student_verify = AsyncMock()
    monkeypatch.setattr(feature_flag_service, "get_flag", AsyncMock(return_value=True))
    monkeypatch.setattr(payment_service, "create_subscription", provider_checkout)
    monkeypatch.setattr(payment_service, "verify_student_subscription", student_verify)
    result = await client.post("/subscription/create", json={"planId": "pro", "customerEmail": "ignored@example.com", "customerName": "Ignored"}, headers=auth)
    assert result.status_code == 409, result.text
    result = await client.get("/subscription/student/verify/test-token")
    assert result.status_code == 409, result.text
    provider_checkout.assert_not_awaited()
    student_verify.assert_not_awaited()


async def test_concurrent_admin_edits_have_one_winner(db_session: AsyncSession):
    import asyncio

    from app.database.connection import get_async_db_session
    from app.services.plan_catalog_service import CatalogConflict

    admin_id, _ = await headers(db_session)
    service = PlanCatalogService()
    await service.update(db_session, "pro", {"description": "Original"}, version=1, admin_id=admin_id)

    async def change(name):
        async with get_async_db_session() as independent_db:
            await service.update(independent_db, "pro", {"name": name}, version=2, admin_id=admin_id)
        return name

    results = await asyncio.gather(change("First"), change("Second"), return_exceptions=True)
    assert sum(isinstance(result, CatalogConflict) for result in results) == 1
    winner = next(result for result in results if isinstance(result, str))
    row = (await db_session.execute(select(PlanCatalog).where(PlanCatalog.sku == "pro").execution_options(populate_existing=True))).scalar_one()
    assert row.version == 3
    assert row.name == winner
    revisions = (await db_session.execute(select(PlanCatalogRevision).where(PlanCatalogRevision.sku == "pro"))).scalars().all()
    assert [revision.version for revision in revisions] == [2, 3]


async def test_catalog_migration_roundtrip_preserves_edits_and_audit(db_session: AsyncSession):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    admin_id, _ = await headers(db_session)
    await PlanCatalogService().update(db_session, "pro", {"name": "Preserved", "purchase_enabled": False}, version=1, admin_id=admin_id)
    path = Path(__file__).parents[1] / "alembic/versions/0061_plan_catalog.py"
    spec = importlib.util.spec_from_file_location("plan_catalog_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def roundtrip(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()

    connection = await db_session.connection()
    await connection.run_sync(roundtrip)
    row = (await db_session.execute(select(PlanCatalog).where(PlanCatalog.sku == "pro"))).scalar_one()
    assert row.name == "Preserved"
    assert not row.purchase_enabled
    assert row.version == 2
    snapshot = (await db_session.execute(select(PlanCatalogRevision).where(PlanCatalogRevision.sku == "pro"))).scalar_one()
    assert snapshot.snapshot["name"] == "Preserved"
    assert snapshot.changed_by == admin_id


async def test_current_subscription_uses_catalog_copy_and_survives_outage(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    from unittest.mock import AsyncMock

    from app.services.plan_catalog_service import plan_catalog_service

    admin_id, auth = await headers(db_session)
    await plan_catalog_service.update(db_session, "pro", {"name": "Professional", "purchase_enabled": False}, version=1, admin_id=admin_id)
    response = await client.get("/subscription/current", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["planName"] == "Professional"
    assert response.json()["planId"] == "pro"
    assert response.json()["status"] == "active"
    monkeypatch.setattr(plan_catalog_service, "list_plans", AsyncMock(side_effect=RuntimeError("Catalog offline")))
    response = await client.get("/subscription/current", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["planId"] == "pro"
    assert response.json()["status"] == "active"
    assert response.json()["features"]["availabilityUnknown"] is True


async def test_billing_sales_flag_off_does_not_block_cancellation(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    from unittest.mock import AsyncMock

    from app.services.feature_flag_service import feature_flag_service
    from app.services.payment_service import payment_service

    user_id, auth = await headers(db_session, "user")
    monkeypatch.setattr(feature_flag_service, "get_flag", AsyncMock(return_value=False))
    cancel = AsyncMock(return_value={"success": True, "message": "Cancellation scheduled"})
    monkeypatch.setattr(payment_service, "cancel_subscription", cancel)
    response = await client.post("/subscription/cancel", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    cancel.assert_awaited_once_with(db_session, user_id)
    # Actual provider failure is still communicated, rather than pretending a
    # payment was cancelled just because sales are paused.
    cancel.return_value = {"success": False, "error": payment_service.get_status()["message"]}
    response = await client.post("/subscription/cancel", headers=auth)
    assert response.status_code == 503, response.text
