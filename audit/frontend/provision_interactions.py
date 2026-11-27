"""Provision users for the remaining front-end interaction journeys."""
import asyncio
import json
import os
import ssl
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(r"C:\Users\Sansk\Projects\Latexy")
load_dotenv(ROOT / ".env")
import asyncpg

BASE = "https://latexy.xyz"
SUFFIX = time.strftime("%Y%m%d%H%M%S", time.gmtime())
OUT = Path(r"C:\Users\Sansk\AppData\Local\Temp\opencode\interaction_identities.json")


def dsn():
    return os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)


async def main():
    users = {}
    for label in ("free", "pro", "admin", "team"):
        email = f"interact.{label}.{SUFFIX}@example.test"
        s = requests.Session()
        r = s.post(
            f"{BASE}/api/auth/sign-up/email",
            json={"email": email, "password": "AuditPass!2026", "name": f"Interaction {label}"},
            headers={"Origin": BASE, "Content-Type": "application/json"},
            timeout=30,
        )
        print(label, r.status_code)
        if r.status_code != 200:
            raise SystemExit(f"signup failed for {label}: {r.status_code} {r.text[:200]}")
        d = r.json()
        users[label] = {
            "email": email,
            "user_id": d["user"]["id"],
            "session_token": d["token"],
            "cookie": s.cookies.get("__Secure-better-auth.session_token"),
        }
        time.sleep(2)

    conn = await asyncpg.connect(dsn=dsn(), ssl=ssl.create_default_context(), timeout=30)
    try:
        await conn.execute(
            "UPDATE users SET email_verified=true WHERE id = ANY($1::uuid[])",
            [u["user_id"] for u in users.values()],
        )
        pro_sub = await conn.fetchval(
            """INSERT INTO subscriptions (id,user_id,plan_id,status,provider,current_period_start,current_period_end)
               VALUES (gen_random_uuid(),$1::uuid,'pro','active','dodo',now(),now()+interval '30 days') RETURNING id""",
            users["pro"]["user_id"],
        )
        await conn.execute(
            "UPDATE users SET subscription_plan='pro', subscription_status='active', subscription_id=$2 WHERE id=$1::uuid",
            users["pro"]["user_id"], str(pro_sub),
        )
        await conn.execute("UPDATE users SET role='admin' WHERE id=$1::uuid", users["admin"]["user_id"])
        team_sub = await conn.fetchval(
            """INSERT INTO subscriptions (id,user_id,plan_id,status,provider,current_period_start,current_period_end)
               VALUES (gen_random_uuid(),$1::uuid,'team','active','dodo',now(),now()+interval '30 days') RETURNING id""",
            users["team"]["user_id"],
        )
        tenant = await conn.fetchval(
            """INSERT INTO tenants (slug,name,owner_id,plan_id,max_members,active)
               VALUES ($1,'Interaction Team',$2::uuid,'team',5,true) RETURNING id""",
            f"interaction-{SUFFIX}", users["team"]["user_id"],
        )
        await conn.execute(
            "INSERT INTO tenant_members (tenant_id,user_id,role) VALUES ($1::uuid,$2::uuid,'admin')",
            tenant, users["team"]["user_id"],
        )
        await conn.execute(
            "UPDATE users SET subscription_plan='team', subscription_status='active', subscription_id=$2, default_tenant_id=$3::uuid WHERE id=$1::uuid",
            users["team"]["user_id"], str(team_sub), tenant,
        )
        workspace = await conn.fetchval(
            """INSERT INTO workspaces (name,owner_id,plan_id,max_members,tenant_id)
               VALUES ('Interaction Workspace',$1::uuid,'team',5,$2::uuid) RETURNING id""",
            users["team"]["user_id"], tenant,
        )
        await conn.execute(
            "INSERT INTO workspace_members (workspace_id,user_id,role,joined_at) VALUES ($1::uuid,$2::uuid,'owner',now())",
            workspace, users["team"]["user_id"],
        )
        users["team"]["tenant_id"] = str(tenant)
        users["team"]["workspace_id"] = str(workspace)
    finally:
        await conn.close()

    OUT.write_text(json.dumps({"suffix": SUFFIX, "users": users}, indent=2), encoding="utf-8")
    print(json.dumps({k: {"email": v["email"], "user_id": v["user_id"]} for k, v in users.items()}, indent=2))
    print("saved", OUT)


if __name__ == "__main__":
    asyncio.run(main())
