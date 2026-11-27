"""Finish front-end audit fixtures using the users created by provision.py.

The first run hit the product-wide auth rate limit after three signups. This
script reuses those existing Better Auth sessions, grants the plans/roles, and
creates the resume/share/tracker fixtures. No new signup is attempted.
"""
import asyncio
import json
import os
import ssl
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(r"C:\Users\Sansk\Projects\Latexy")
load_dotenv(ROOT / ".env")
import asyncpg

API = "https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run"
OUT = Path(r"C:\Users\Sansk\AppData\Local\Temp\opencode\fe_identities.json")
LATEX = r"""\documentclass[11pt]{article}
\usepackage[margin=0.75in]{geometry}
\begin{document}
\begin{center}{\Large \textbf{Audit Candidate}}\\audit@example.test\end{center}
\section*{Summary}
Product engineer with experience in distributed systems and frontend performance.
\section*{Experience}
\textbf{Senior Engineer}, Example Corp \hfill 2022--2026\\
Built and operated high-traffic web services.
\section*{Education}
B.Tech, Example University
\end{document}
"""


def dsn():
    return os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)


async def main():
    conn = await asyncpg.connect(dsn=dsn(), ssl=ssl.create_default_context(), timeout=30)
    try:
        rows = await conn.fetch(
            """SELECT u.id,u.email,u.subscription_plan,u.role,s.token
               FROM users u JOIN session s ON s."userId"=u.id::text
               WHERE u.email LIKE 'audit.fe.%'
               ORDER BY u.created_at DESC"""
        )
        users = {}
        for r in rows:
            email = r["email"]
            if ".free." in email:
                label = "free"
            elif ".pro." in email:
                label = "pro"
            elif ".admin." in email:
                label = "admin"
            elif ".probe2." in email:
                label = "team"
            else:
                continue
            users[label] = {
                "user_id": str(r["id"]),
                "email": email,
                "session_token": r["token"],
                "plan": "free",
                "role": "user",
            }
        missing = {"free", "pro", "admin", "team"} - set(users)
        if missing:
            raise SystemExit(f"missing users: {missing}")

        await conn.execute(
            "UPDATE users SET email_verified=true WHERE id = ANY($1::uuid[])",
            [u["user_id"] for u in users.values()],
        )
        pro_sub = await conn.fetchval(
            """INSERT INTO subscriptions (id, user_id, plan_id, status, provider, current_period_start, current_period_end)
               VALUES (gen_random_uuid(),$1::uuid,'pro','active','dodo',now(),now()+interval '30 days') RETURNING id""",
            users["pro"]["user_id"],
        )
        await conn.execute(
            "UPDATE users SET subscription_plan='pro', subscription_status='active', subscription_id=$2 WHERE id=$1::uuid",
            users["pro"]["user_id"], str(pro_sub),
        )
        users["pro"].update(plan="pro", subscription_id=str(pro_sub))

        team_sub = await conn.fetchval(
            """INSERT INTO subscriptions (id, user_id, plan_id, status, provider, current_period_start, current_period_end)
               VALUES (gen_random_uuid(),$1::uuid,'team','active','dodo',now(),now()+interval '30 days') RETURNING id""",
            users["team"]["user_id"],
        )
        tenant_id = await conn.fetchval(
            """INSERT INTO tenants (slug,name,owner_id,plan_id,max_members,active)
               VALUES ($1,'Audit FE Team',$2::uuid,'team',5,true) RETURNING id""",
            "audit-fe-team", users["team"]["user_id"],
        )
        await conn.execute(
            "INSERT INTO tenant_members (tenant_id,user_id,role) VALUES ($1::uuid,$2::uuid,'admin')",
            tenant_id, users["team"]["user_id"],
        )
        await conn.execute(
            "UPDATE users SET subscription_plan='team', subscription_status='active', subscription_id=$2, default_tenant_id=$3::uuid WHERE id=$1::uuid",
            users["team"]["user_id"], str(team_sub), tenant_id,
        )
        users["team"].update(plan="team", tenant_id=str(tenant_id))

        await conn.execute("UPDATE users SET role='admin' WHERE id=$1::uuid", users["admin"]["user_id"])
        users["admin"]["role"] = "admin"

        username = "auditfe20261127"
        await conn.execute(
            "UPDATE users SET public_username=$2, portfolio_enabled=true, portfolio_tagline='Audit portfolio' WHERE id=$1::uuid",
            users["pro"]["user_id"], username,
        )
    finally:
        await conn.close()

    def auth(label):
        return {"Authorization": f"Bearer {users[label]['session_token']}", "Content-Type": "application/json"}

    def create_resume(label, title):
        r = requests.post(
            f"{API}/resumes/",
            json={"title": title, "latex_content": LATEX},
            headers=auth(label),
            timeout=60,
        )
        r.raise_for_status()
        d = r.json()
        return d.get("id") or d.get("resume", {}).get("id")

    pro_resume = create_resume("pro", "Audit FE Resume")
    free_resume = create_resume("free", "Audit Free Resume")

    share = requests.post(
        f"{API}/resumes/{pro_resume}/share",
        json={"anonymous": False, "review_comments": True},
        headers=auth("pro"),
        timeout=60,
    )
    share.raise_for_status()
    sd = share.json()
    share_token = sd.get("share_token") or sd.get("token")

    tracker = requests.post(
        f"{API}/tracker/applications",
        json={"company": "Audit Co", "role": "Senior Engineer", "status": "applied", "applied_date": "2026-11-27"},
        headers=auth("pro"),
        timeout=60,
    )

    payload = {
        "suffix": "20261127150805",
        "users": users,
        "pro_resume_id": pro_resume,
        "free_resume_id": free_resume,
        "share_token": share_token,
        "portfolio_username": username,
        "tenant_id": str(tenant_id),
        "tracker_status": tracker.status_code,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("pro_resume_id", "free_resume_id", "share_token", "portfolio_username", "tenant_id", "tracker_status")}, indent=2))
    print("identities", OUT)


if __name__ == "__main__":
    asyncio.run(main())
