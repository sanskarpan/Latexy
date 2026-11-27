"""Verify audit residue in production before/after cleanup."""
import asyncio
import json
import os
import ssl
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(r"C:\Users\Sansk\Projects\Latexy")
load_dotenv(ROOT / ".env")

import asyncpg

MATRIX = ROOT / "audit/plans/identity-matrix.json"


def dsn() -> str:
    return os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)


async def main():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    suffix = matrix["suffix"]
    user_ids = [v["user_id"] for v in matrix["identities"].values() if "user_id" in v]
    conn = await asyncpg.connect(dsn=dsn(), ssl=ssl.create_default_context(), timeout=30)
    result = {"suffix": suffix, "user_ids": len(user_ids), "counts": {}}
    try:
        result["counts"]["users_by_email"] = await conn.fetchval(
            "SELECT count(*) FROM users WHERE email LIKE $1", f"audit+%{suffix}@example.test"
        )
        result["counts"]["users_by_id"] = await conn.fetchval(
            "SELECT count(*) FROM users WHERE id = ANY($1::uuid[])", user_ids
        )
        result["counts"]["sessions"] = await conn.fetchval(
            'SELECT count(*) FROM session WHERE "userId" = ANY($1::text[])', user_ids
        )
        for table, column in [
            ("subscriptions", "user_id"),
            ("developer_api_keys", "user_id"),
            ("team_seats", "owner_user_id"),
            ("tenant_members", "user_id"),
            ("compilations", "user_id"),
            ("optimizations", "user_id"),
            ("usage_analytics", "user_id"),
            ("gdpr_requests", "user_id"),
        ]:
            result["counts"][table] = await conn.fetchval(
                f'SELECT count(*) FROM "{table}" WHERE "{column}" = ANY($1::uuid[])', user_ids
            )
        result["counts"]["tenants_owned"] = await conn.fetchval(
            "SELECT count(*) FROM tenants WHERE owner_id = ANY($1::uuid[])", user_ids
        )
        result["counts"]["tenants_audit_slug"] = await conn.fetchval(
            "SELECT count(*) FROM tenants WHERE slug LIKE $1", f"%{suffix}%"
        )
        fp = matrix["identities"].get("anonymous-device", {}).get("device_fingerprint")
        if fp:
            result["counts"]["device_trials"] = await conn.fetchval(
                "SELECT count(*) FROM device_trials WHERE device_fingerprint = $1", fp
            )
        result["migration_head"] = await conn.fetchval(
            "SELECT version_num FROM alembic_version LIMIT 1"
        )
        result["db"] = await conn.fetchval("SELECT current_database()")
    finally:
        await conn.close()
    result["clean"] = all(v == 0 for v in result["counts"].values())
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
