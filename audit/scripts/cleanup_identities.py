"""Clean up the audit identity matrix created by provision_identities.py."""
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


def ssl_arg():
    raw = os.environ["DATABASE_URL"]
    return None if "localhost" in raw or "127.0.0.1" in raw else ssl.create_default_context()


async def main():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    suffix = matrix["suffix"]
    dry_run = os.environ.get("DRY_RUN") == "1"
    conn = await asyncpg.connect(dsn=dsn(), ssl=ssl_arg(), timeout=30)
    counts = {}
    try:
        user_ids = [v["user_id"] for v in matrix["identities"].values() if "user_id" in v]
        matrix_tenant_ids = [v["tenant_id"] for v in matrix["identities"].values() if "tenant_id" in v]
        # Include tenants created by later auditors under a shared identity (for example
        # the security tenant) so cleanup does not depend on the matrix being complete.
        extra_tenants = await conn.fetch(
            "SELECT id FROM tenants WHERE owner_id = ANY($1::uuid[])", user_ids
        )
        tenant_ids = sorted({str(r["id"]) for r in extra_tenants} | set(matrix_tenant_ids))

        tx = conn.transaction()
        await tx.start()
        try:
            if tenant_ids:
                counts["tenant_members"] = await conn.execute(
                    "DELETE FROM tenant_members WHERE tenant_id = ANY($1::uuid[])", tenant_ids
                )
                counts["team_seats"] = await conn.execute(
                    "DELETE FROM team_seats WHERE owner_user_id = ANY($1::uuid[])", user_ids
                )
                counts["tenant_domain_events"] = await conn.execute(
                    "DELETE FROM tenant_domain_events WHERE tenant_id = ANY($1::uuid[])", tenant_ids
                )
                counts["tenants"] = await conn.execute(
                    "DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenant_ids
                )
            counts["developer_api_keys"] = await conn.execute(
                "DELETE FROM developer_api_keys WHERE user_id = ANY($1::uuid[])", user_ids
            )
            counts["sessions"] = await conn.execute(
                'DELETE FROM session WHERE "userId" = ANY($1::text[])', user_ids
            )
            counts["subscriptions"] = await conn.execute(
                "DELETE FROM subscriptions WHERE user_id = ANY($1::uuid[])", user_ids
            )
            # These FKs are SET NULL, so delete explicitly or the rows survive as orphans.
            counts["compilations"] = await conn.execute(
                "DELETE FROM compilations WHERE user_id = ANY($1::uuid[])", user_ids
            )
            counts["optimizations"] = await conn.execute(
                "DELETE FROM optimizations WHERE user_id = ANY($1::uuid[])", user_ids
            )
            counts["usage_analytics"] = await conn.execute(
                "DELETE FROM usage_analytics WHERE user_id = ANY($1::uuid[])", user_ids
            )
            # gdpr_requests are legally retained by a database trigger; the user FK
            # is SET NULL, so they survive as anonymized audit evidence by design.
            counts["device_trials"] = await conn.execute(
                "DELETE FROM device_trials WHERE device_fingerprint = $1",
                matrix["identities"]["anonymous-device"]["device_fingerprint"],
            )
            counts["users"] = await conn.execute(
                "DELETE FROM users WHERE id = ANY($1::uuid[])", user_ids
            )
            if dry_run:
                await tx.rollback()
            else:
                await tx.commit()
        except Exception:
            await tx.rollback()
            raise
        print(json.dumps({"cleaned": not dry_run, "dry_run": dry_run, "suffix": suffix, "counts": counts}))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
