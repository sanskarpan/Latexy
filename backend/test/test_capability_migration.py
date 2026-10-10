"""Real upgrade preservation for the frozen capability/SKU seed migration."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, insert, select, update

from app.core.feature_registry import FEATURE_REGISTRY, PLAN_MATRIX_KEYS, gateable_keys
from app.database.models import FeatureFlag, PlanFeature
from app.services.entitlement_service import entitlement_service


async def test_capability_upgrade_preserves_denials_and_baselines(db_session):
    flags = [dict(row) for row in (await db_session.execute(select(FeatureFlag.__table__))).mappings()]
    matrix = [dict(row) for row in (await db_session.execute(select(PlanFeature.__table__))).mappings()]
    path = Path(__file__).parents[1] / "alembic/versions/0060_capability_catalog.py"
    spec = importlib.util.spec_from_file_location("capability_seed_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    async def run(*operations):
        def apply(connection):
            with Operations.context(MigrationContext.configure(connection)):
                for operation in operations:
                    operation()
        await (await db_session.connection()).run_sync(apply)
        await db_session.commit()

    try:
        await db_session.execute(delete(PlanFeature))
        await db_session.execute(delete(FeatureFlag))
        db_session.add(FeatureFlag(key="llm_optimize", enabled=False, label="Existing admin label"))
        db_session.add(PlanFeature(plan_family="free", feature_key="llm_optimize", enabled=False))
        await db_session.commit()
        await run(migration.upgrade)

        switches = dict((await db_session.execute(select(FeatureFlag.key, FeatureFlag.enabled))).all())
        grants = {(row.plan_family, row.feature_key): row.enabled for row in (await db_session.execute(select(PlanFeature))).scalars()}
        assert set(switches) == set(gateable_keys())
        assert set(grants) == {(plan, key) for plan in PLAN_MATRIX_KEYS for key in gateable_keys()}
        assert not switches["llm_optimize"] and not grants["free", "llm_optimize"]
        assert all(feature.key not in switches for feature in FEATURE_REGISTRY if not feature.gateable)
        assert await db_session.scalar(select(FeatureFlag.label).where(FeatureFlag.key == "llm_optimize")) == "Existing admin label"
        assert not await entitlement_service.has_feature("d01", user=None)
        assert await entitlement_service.has_feature("compile", user=None)
        assert await entitlement_service.has_feature("a04", user=None)

        await db_session.execute(update(FeatureFlag).where(FeatureFlag.key == "d18").values(enabled=False))
        await db_session.execute(update(PlanFeature).where(PlanFeature.plan_family == "student", PlanFeature.feature_key == "d01").values(enabled=False))
        await db_session.commit()
        await run(migration.downgrade, migration.upgrade)
        assert await db_session.scalar(select(FeatureFlag.enabled).where(FeatureFlag.key == "d18")) is False
        assert await db_session.scalar(select(PlanFeature.enabled).where(PlanFeature.plan_family == "student", PlanFeature.feature_key == "d01")) is False
        assert await db_session.scalar(select(FeatureFlag.enabled).where(FeatureFlag.key == "llm_optimize")) is False
    finally:
        # This test uses only the isolated test DB and restores prior settings so
        # module order cannot affect unrelated admissions in the aggregate suite.
        await db_session.rollback()
        await db_session.execute(delete(PlanFeature))
        await db_session.execute(delete(FeatureFlag))
        if flags:
            await db_session.execute(insert(FeatureFlag.__table__), flags)
        if matrix:
            await db_session.execute(insert(PlanFeature.__table__), matrix)
        await db_session.commit()
