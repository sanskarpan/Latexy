"""Provision the audit identity/plan matrix in production.

Direct database provisioning is the documented fallback in the audit brief.
Every identity uses the audit+ prefix and a single run suffix so analytics and
cleanup can filter it. Run with the production DATABASE_URL from .env.
"""
import asyncio
import hashlib
import json
import os
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(r"C:\Users\Sansk\Projects\Latexy")
load_dotenv(ROOT / ".env")

import asyncpg

OUT = ROOT / "audit/plans/identity-matrix.json"
CHANGES = ROOT / "audit/changes/production-changes.md"
SUFFIX = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
NOW = datetime.now(timezone.utc)


def dsn() -> str:
    return os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)


def ssl_arg():
    raw = os.environ["DATABASE_URL"]
    return None if "localhost" in raw or "127.0.0.1" in raw else ssl.create_default_context()


def email(cohort: str) -> str:
    return f"audit+{cohort}-{SUFFIX}@example.test"


def token(cohort: str) -> str:
    return f"audit_sess_{SUFFIX}_{cohort}"


async def create_user(conn, cohort, *, plan="free", status="active", role="user", verified=True,
                      trial_used=False, metadata=None):
    uid = str(uuid.uuid4())
    addr = email(cohort)
    await conn.execute(
        "INSERT INTO users (id,email,name,role,email_verified,subscription_plan,"
        "subscription_status,trial_used,user_metadata,auth_provider) "
        "VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,'email')",
        uid, addr, f"Audit {cohort}", role, verified, plan, status, trial_used,
        json.dumps(metadata or {}),
    )
    sid = f"audit_{cohort}_{SUFFIX}"
    tok = token(cohort)
    await conn.execute(
        'INSERT INTO session (id,"userId","expiresAt",token,"userAgent") VALUES ($1,$2::uuid,$3,$4,$5)',
        sid, uid, NOW + timedelta(days=7), tok, "Latexy production audit",
    )
    return {"cohort": cohort, "email": addr, "user_id": uid, "session_id": sid,
            "session_token": tok, "plan": plan, "status": status, "role": role}


async def add_subscription(conn, user, *, plan, status, provider="dodo", period_end_days=30, cancelled=False):
    sid = str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO subscriptions (id,user_id,plan_id,status,provider,current_period_start,"
        "current_period_end,cancelled_at,provider_subscription_id) "
        "VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6,$7,$8,$9)",
        sid, user["user_id"], plan, status, provider, NOW - timedelta(days=30),
        NOW + timedelta(days=period_end_days),
        NOW if cancelled else None,
        f"audit_sub_{SUFFIX}_{user['cohort']}",
    )
    user["subscription_id"] = sid


async def main():
    conn = await asyncpg.connect(dsn=dsn(), ssl=ssl_arg(), timeout=30)
    identities = {}
    try:
        # Core plan matrix
        specs = [
            ("free", dict(plan="free", status="active")),
            ("basic-monthly", dict(plan="basic", status="active")),
            ("basic-annual", dict(plan="basic_annual", status="active")),
            ("pro-monthly", dict(plan="pro", status="active")),
            ("pro-annual", dict(plan="pro_annual", status="active")),
            ("byok-monthly", dict(plan="byok", status="active")),
            ("student", dict(plan="student", status="active", metadata={"student_verified": True, "student_verification": "audit"})),
            ("trial-active", dict(plan="pro", status="trialing", trial_used=False)),
            ("trial-expired", dict(plan="free", status="expired", trial_used=True)),
            ("past-due", dict(plan="basic", status="past_due")),
            ("cancelled", dict(plan="basic", status="cancelled")),
            ("team-owner", dict(plan="team", status="active")),
            ("team-member", dict(plan="team", status="active")),
            ("admin-support", dict(plan="free", status="active", role="support")),
            ("admin-superadmin", dict(plan="free", status="active", role="admin")),
        ]
        for cohort, kwargs in specs:
            user = await create_user(conn, cohort, **kwargs)
            identities[cohort] = user
        for cohort in ("basic-monthly", "basic-annual", "pro-monthly", "pro-annual", "byok-monthly", "student", "team-owner", "team-member"):
            await add_subscription(conn, identities[cohort], plan=identities[cohort]["plan"], status="active")
        await add_subscription(conn, identities["trial-active"], plan="pro", status="trialing", period_end_days=7)
        await add_subscription(conn, identities["past-due"], plan="basic", status="past_due", period_end_days=-2)
        await add_subscription(conn, identities["cancelled"], plan="basic", status="cancelled", period_end_days=-10, cancelled=True)

        # Developer API key cohort
        dev = await create_user(conn, "developer-api", plan="pro", status="active")
        await add_subscription(conn, dev, plan="pro", status="active")
        full_key = f"lxy_audit_{SUFFIX}_{uuid.uuid4().hex[:24]}"
        key_hash = hashlib.sha256(full_key.encode("utf-8")).hexdigest()
        key_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO developer_api_keys (id,user_id,key_hash,key_prefix,name,scopes) "
            "VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6)",
            key_id, dev["user_id"], key_hash, full_key[:16], "Audit key",
            ["compile", "optimize", "ats", "export"],
        )
        dev.update({"api_key": full_key, "api_key_id": key_id})
        identities["developer-api"] = dev

        # Team tenant + owner/member rows
        owner = identities["team-owner"]
        member = identities["team-member"]
        tenant_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO tenants (id,slug,name,owner_id,plan_id,max_members,active) "
            "VALUES ($1::uuid,$2,$3,$4::uuid,'agency',5,true)",
            tenant_id, f"audit-team-{SUFFIX}", "Audit Team", owner["user_id"],
        )
        for user, role in ((owner, "owner"), (member, "member")):
            await conn.execute(
                "INSERT INTO tenant_members (tenant_id,user_id,role) VALUES ($1::uuid,$2::uuid,$3)",
                tenant_id, user["user_id"], role,
            )
            await conn.execute(
                "INSERT INTO team_seats (id,owner_user_id,member_email,member_user_id,status,joined_at) "
                "VALUES ($1::uuid,$2::uuid,$3,$4::uuid,'active',$5)",
                str(uuid.uuid4()), owner["user_id"], user["email"], user["user_id"], NOW,
            )
        identities["team-owner"]["tenant_id"] = tenant_id
        identities["team-member"]["tenant_id"] = tenant_id
        identities["team-owner"]["subscription_plan"] = "team"

        # Anonymous device-trial cohort
        device_key = f"audit-device-{SUFFIX}"
        await conn.execute(
            "INSERT INTO device_trials (id,device_fingerprint,usage_count,blocked,whitelisted) "
            "VALUES ($1::uuid,$2,0,false,false)",
            str(uuid.uuid4()), device_key,
        )
        identities["anonymous-device"] = {"cohort": "anonymous-device", "device_fingerprint": device_key}

        payload = {
            "suffix": SUFFIX,
            "created_at": NOW.isoformat(),
            "window_start": NOW.isoformat(),
            "window_end": None,
            "identities": identities,
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        CHANGES.parent.mkdir(parents=True, exist_ok=True)
        with CHANGES.open("a", encoding="utf-8") as f:
            f.write(f"\n## Identity provisioning {NOW.isoformat()} (audit {SUFFIX})\n\n")
            f.write("- Method: direct production PostgreSQL insert (documented fallback).\n")
            f.write("- Scope: users/sessions/subscriptions/tenant/team seats/developer key/device trial with `audit+` prefix.\n")
            f.write(f"- Identity matrix: `audit/plans/identity-matrix.json`.\n")
            f.write(f"- Restore/cleanup: run `audit/scripts/cleanup_identities.py` for suffix `{SUFFIX}`.\n")
            f.write("- Global configuration changed: none.\n")
        print(json.dumps({"provisioned": len(identities), "suffix": SUFFIX, "file": str(OUT)}))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
