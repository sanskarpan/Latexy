"""D14 insert-only source contract and disposable-PostgreSQL preservation tests.

The database tests use only conftest's verified isolated *_test database and
restore every entitlement row. No live provider, user or subscription is changed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import delete, insert, select, update

from app.core.feature_registry import CAPABILITY_ROLES, CAPABILITY_SUBFEATURES, FEATURE_REGISTRY, PLAN_MATRIX_KEYS
from app.database.models import FeatureFlag, PlanFeature, RoleFeature
from app.services.entitlement_service import _blob_from_rows, _snapshot_query, entitlement_service

MODELS = (FeatureFlag, PlanFeature, RoleFeature)
CHILDREN = tuple(row["key"] for row in CAPABILITY_SUBFEATURES)


def migration(filename="0073_d14_subfeatures.py"):
    path = Path(__file__).parents[1] / "alembic/versions" / filename
    spec = importlib.util.spec_from_file_location("d14_seed_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_d14_seed_is_frozen_insert_only_and_downgrade_preserves_choices():
    seed = migration()
    assert seed.down_revision == "0072_capability_roles"
    assert tuple(seed.KEYS) == CHILDREN
    assert set(seed.PLAN_KEYS) == set(PLAN_MATRIX_KEYS)
    assert len(seed.PLAN_KEYS) == len(PLAN_MATRIX_KEYS) == 11
    assert seed.ROLES == CAPABILITY_ROLES
    calls = []
    choices = {("feature_flags", "d14_latex"): False, ("plan_features", "pro", "d14_math_text"): False,
               ("role_features", "admin", "d14_table_image"): False}
    class Connection:
        def execute(self, statement, params):
            sql = str(statement)
            assert sql.startswith("INSERT INTO ")
            assert "ON CONFLICT" in sql and sql.endswith("DO NOTHING")
            table = sql.split()[2]
            identity = (table, *([params["plan"]] if "plan" in params else [params["role"]] if "role" in params else []), params["key"])
            choices.setdefault(identity, True)
            calls.append(identity)
    seed.op = SimpleNamespace(get_bind=lambda: Connection())
    seed.upgrade()
    assert len(calls) == 5 * (1 + 11 + 4) == 80
    assert len(set(calls)) == 80
    assert all(identity[-1] in CHILDREN for identity in calls)
    assert sum(not enabled for enabled in choices.values()) == 3
    snapshot = choices.copy()
    seed.op = SimpleNamespace(get_bind=lambda: pytest.fail("downgrade must not use a destructive database operation"))
    seed.downgrade()
    assert choices == snapshot
    seed.op = SimpleNamespace(get_bind=lambda: Connection())
    seed.upgrade()
    assert choices == snapshot


async def run_migrations(db, *operations):
    def apply(connection):
        with Operations.context(MigrationContext.configure(connection)):
            for operation in operations:
                operation()
    await (await db.connection()).run_sync(apply)
    await db.commit()


async def rows(db, model):
    return [dict(row) for row in (await db.execute(select(model.__table__).order_by(*model.__table__.primary_key.columns))).mappings()]


async def blob(db):
    return _blob_from_rows((await db.execute(_snapshot_query())).all())


@pytest.fixture
async def original_catalog(db_session):
    saved = {model: await rows(db_session, model) for model in MODELS}
    try:
        for model in MODELS:
            await db_session.execute(delete(model))
        await db_session.commit()
        await run_migrations(db_session, migration("0069_capability_catalog.py").upgrade, migration("0072_capability_roles.py").upgrade)
        yield db_session
    finally:
        await db_session.rollback()
        for model in reversed(MODELS):
            await db_session.execute(delete(model))
            if saved[model]:
                await db_session.execute(insert(model.__table__), saved[model])
        await db_session.commit()


async def write_denial(db, axis, key, enabled=False):
    if axis == "global":
        await db.execute(update(FeatureFlag).where(FeatureFlag.key == key).values(enabled=enabled))
    elif axis == "role":
        await db.execute(update(RoleFeature).where(RoleFeature.role == "admin", RoleFeature.feature_key == key).values(enabled=enabled))
    else:
        plan = "pro" if axis == "family" else "pro_annual"
        await db.execute(update(PlanFeature).where(PlanFeature.plan_family == plan, PlanFeature.feature_key == key).values(enabled=enabled))
    await db.commit()


@pytest.mark.parametrize("ancestor", ["d14", "ai_writing"])
@pytest.mark.parametrize("axis", ["global", "role", "family", "sku"])
async def test_d14_upgrade_preserves_each_ancestor_denial_and_unrelated_rows(original_catalog, ancestor, axis):
    db = original_catalog
    await write_denial(db, axis, ancestor)
    before = {model: await rows(db, model) for model in MODELS}
    seed = migration()
    await run_migrations(db, seed.upgrade)
    after = {model: await rows(db, model) for model in MODELS}
    for model in MODELS:
        key_column = "key" if model is FeatureFlag else "feature_key"
        assert [row for row in after[model] if row[key_column] not in CHILDREN] == before[model]
        added = [row for row in after[model] if row[key_column] in CHILDREN]
        assert all(row["enabled"] is True for row in added)
        assert len(added) == 5 * (1 if model is FeatureFlag else 11 if model is PlanFeature else 4)
    state = await blob(db)
    for child in CHILDREN:
        assert entitlement_service._decide(state, child, "pro_annual", "admin") is False
    assert entitlement_service._decide(state, "c03", "pro_annual", "admin") is True
    baselines = [feature for feature in FEATURE_REGISTRY if not feature.gateable]
    assert len(baselines) == 16
    assert all(entitlement_service._decide(state, feature.key, "pro_annual", "admin") for feature in baselines)


async def test_d14_child_denial_survives_downgrade_reupgrade_and_siblings_stay_enabled(original_catalog):
    db = original_catalog
    seed = migration()
    await run_migrations(db, seed.upgrade)
    child = "d14_math_text"
    for axis in ["global", "role", "family", "sku"]:
        await write_denial(db, axis, child)
    before = {model: await rows(db, model) for model in MODELS}
    await run_migrations(db, seed.downgrade, seed.upgrade)
    assert {model: await rows(db, model) for model in MODELS} == before
    state = await blob(db)
    assert not entitlement_service._decide(state, child, "pro_annual", "admin")
    assert all(entitlement_service._decide(state, sibling, "pro_annual", "admin") for sibling in CHILDREN if sibling != child)
    for ancestor in ["d14", "ai_writing"]:
        for axis in ["global", "role", "family", "sku"]:
            await write_denial(db, axis, ancestor)
            state = await blob(db)
            assert not any(entitlement_service._decide(state, sibling, "pro_annual", "admin") for sibling in CHILDREN)
            await write_denial(db, axis, ancestor, True)
    # Ancestors restored ON do not override the child's stored denials.
    assert not entitlement_service._decide(await blob(db), child, "pro_annual", "admin")


@pytest.mark.parametrize("axis", ["global", "role", "family", "sku"])
async def test_d14_missing_leaf_row_fails_closed_after_upgrade(original_catalog, axis):
    db = original_catalog
    await run_migrations(db, migration().upgrade)
    child = CHILDREN[0]
    if axis == "global":
        statement = delete(FeatureFlag).where(FeatureFlag.key == child)
    elif axis == "role":
        statement = delete(RoleFeature).where(RoleFeature.role == "admin", RoleFeature.feature_key == child)
    else:
        plan = "pro" if axis == "family" else "pro_annual"
        statement = delete(PlanFeature).where(PlanFeature.plan_family == plan, PlanFeature.feature_key == child)
    await db.execute(statement)
    await db.commit()
    state = await blob(db)
    assert not entitlement_service._decide(state, child, "pro_annual", "admin")
    assert not entitlement_service._decide(state, "d14_unknown", "pro_annual", "admin")
    assert all(entitlement_service._decide(state, sibling, "pro_annual", "admin") for sibling in CHILDREN[1:])


@pytest.mark.parametrize("axis", ["global", "role", "family", "sku"])
async def test_d14_admin_expected_state_conflict_preserves_operator_choice(original_catalog, axis):
    db = original_catalog
    await run_migrations(db, migration().upgrade)
    child = CHILDREN[0]
    async def write(enabled):
        if axis == "global":
            await entitlement_service.set_kill_switch(child, enabled, db, expected_enabled=True)
        elif axis == "role":
            await entitlement_service.set_role_cell("admin", child, enabled, db, expected_enabled=True)
        else:
            await entitlement_service.set_matrix_cell("pro" if axis == "family" else "pro_annual", child, enabled, db, expected_enabled=True)
    await write(False)
    with pytest.raises(HTTPException) as error:
        await write(True)
    assert error.value.status_code == 409
    assert not entitlement_service._decide(await blob(db), child, "pro_annual", "admin")
    assert entitlement_service._decide(await blob(db), CHILDREN[1], "pro_annual", "admin")
