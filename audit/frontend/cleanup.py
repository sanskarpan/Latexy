"""Delete the front-end audit users and every fixture they created."""
import asyncio
import json
import os
import ssl
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(r"C:\Users\Sansk\Projects\Latexy")
load_dotenv(ROOT / ".env")
import asyncpg

IDS = Path(r"C:\Users\Sansk\AppData\Local\Temp\opencode\fe_identities.json")


def dsn():
    return os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)


async def main():
    ids = json.loads(IDS.read_text(encoding="utf-8"))
    conn = await asyncpg.connect(dsn=dsn(), ssl=ssl.create_default_context(), timeout=30)
    counts = {}
    try:
        users = await conn.fetch("SELECT id FROM users WHERE email LIKE 'audit.fe.%'")
        user_ids = [str(r["id"]) for r in users]
        counts["users_found"] = len(user_ids)
        tenants = await conn.fetch("SELECT id FROM tenants WHERE owner_id = ANY($1::uuid[])", user_ids)
        tenant_ids = [str(r["id"]) for r in tenants]
        workspaces = await conn.fetch("SELECT id FROM workspaces WHERE owner_id = ANY($1::uuid[])", user_ids)
        workspace_ids = [str(r["id"]) for r in workspaces]
        tx = conn.transaction()
        await tx.start()
        try:
            if tenant_ids:
                counts["tenant_members"] = await conn.execute("DELETE FROM tenant_members WHERE tenant_id = ANY($1::uuid[])", tenant_ids)
                counts["tenants"] = await conn.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenant_ids)
            if workspace_ids:
                counts["workspace_members"] = await conn.execute("DELETE FROM workspace_members WHERE workspace_id = ANY($1::uuid[])", workspace_ids)
                counts["workspace_resumes"] = await conn.execute("DELETE FROM workspace_resumes WHERE workspace_id = ANY($1::uuid[])", workspace_ids)
                counts["workspaces"] = await conn.execute("DELETE FROM workspaces WHERE id = ANY($1::uuid[])", workspace_ids)
            counts["team_seats"] = await conn.execute("DELETE FROM team_seats WHERE owner_user_id = ANY($1::uuid[])", user_ids)
            counts["developer_api_keys"] = await conn.execute("DELETE FROM developer_api_keys WHERE user_id = ANY($1::uuid[])", user_ids)
            counts["sessions"] = await conn.execute('DELETE FROM session WHERE "userId" = ANY($1::text[])', user_ids)
            counts["subscriptions"] = await conn.execute("DELETE FROM subscriptions WHERE user_id = ANY($1::uuid[])", user_ids)
            counts["compilations"] = await conn.execute("DELETE FROM compilations WHERE user_id = ANY($1::uuid[])", user_ids)
            counts["optimizations"] = await conn.execute("DELETE FROM optimizations WHERE user_id = ANY($1::uuid[])", user_ids)
            counts["usage_analytics"] = await conn.execute("DELETE FROM usage_analytics WHERE user_id = ANY($1::uuid[])", user_ids)
            counts["users"] = await conn.execute("DELETE FROM users WHERE id = ANY($1::uuid[])", user_ids)
            await tx.commit()
        except Exception:
            await tx.rollback()
            raise
    finally:
        await conn.close()
    remaining = await asyncpg.connect(dsn=dsn(), ssl=ssl.create_default_context(), timeout=30)
    try:
        result = {
            "counts": counts,
            "remaining_users": await remaining.fetchval("SELECT count(*) FROM users WHERE email LIKE 'audit.fe.%'"),
            "remaining_tenants": await remaining.fetchval("SELECT count(*) FROM tenants WHERE slug LIKE 'audit-fe-%'"),
            "remaining_workspaces": await remaining.fetchval("SELECT count(*) FROM workspaces WHERE name LIKE 'Audit FE%'"),
            "migration_head": await remaining.fetchval("SELECT version_num FROM alembic_version LIMIT 1"),
        }
    finally:
        await remaining.close()
    print(json.dumps(result, indent=2, default=str))
    Path(ROOT / "audit/frontend/cleanup-after.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
