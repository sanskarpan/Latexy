"""Provision synthetic users and fixtures for the front-end page audit.

Creates three Better Auth users (free, pro, admin), marks them verified,
grants a pro subscription and admin role, and creates a published resume,
share link and tracker item. The full identities (session tokens + cookies)
are written outside the repository for the audit run.
"""
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
API = "https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run"
SUFFIX = time.strftime("%Y%m%d%H%M%S", time.gmtime())
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


def signup(label):
    email = f"audit.fe.{label}.{SUFFIX}@example.test"
    s = requests.Session()
    r = s.post(
        f"{BASE}/api/auth/sign-up/email",
        json={"email": email, "password": "AuditPass!2026", "name": f"Audit FE {label}"},
        headers={"Origin": BASE, "Content-Type": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    cookie = s.cookies.get("__Secure-better-auth.session_token")
    return {
        "label": label,
        "email": email,
        "user_id": data["user"]["id"],
        "session_token": data["token"],
        "cookie": cookie,
    }


async def main():
    users = {label: signup(label) for label in ("free", "pro", "admin", "team")}
    conn = await asyncpg.connect(dsn=dsn(), ssl=ssl.create_default_context(), timeout=30)
    try:
        await conn.execute(
            "UPDATE users SET email_verified=true WHERE id = ANY($1::uuid[])",
            [u["user_id"] for u in users.values()],
        )
        # Pro subscription
        sub_id = await conn.fetchval(
            """INSERT INTO subscriptions (user_id, plan_id, status, provider, current_period_start, current_period_end)
               VALUES ($1::uuid,'pro','active','dodo',now(),now()+interval '30 days') RETURNING id""",
            users["pro"]["user_id"],
        )
        await conn.execute(
            "UPDATE users SET subscription_plan='pro', subscription_status='active', subscription_id=$2 WHERE id=$1::uuid",
            users["pro"]["user_id"], str(sub_id),
        )
        # Team subscription + tenant
        team_sub_id = await conn.fetchval(
            """INSERT INTO subscriptions (user_id, plan_id, status, provider, current_period_start, current_period_end)
               VALUES ($1::uuid,'team','active','dodo',now(),now()+interval '30 days') RETURNING id""",
            users["team"]["user_id"],
        )
        tenant_id = await conn.fetchval(
            """INSERT INTO tenants (slug,name,owner_id,plan_id,max_members,active)
               VALUES ($1,'Audit FE Team',$2::uuid,'team',5,true) RETURNING id""",
            f"audit-fe-{SUFFIX}", users["team"]["user_id"],
        )
        await conn.execute(
            "INSERT INTO tenant_members (tenant_id,user_id,role) VALUES ($1::uuid,$2::uuid,'admin')",
            tenant_id, users["team"]["user_id"],
        )
        await conn.execute(
            "UPDATE users SET subscription_plan='team', subscription_status='active', subscription_id=$2, default_tenant_id=$3::uuid WHERE id=$1::uuid",
            users["team"]["user_id"], str(team_sub_id), tenant_id,
        )
        # Admin role
        await conn.execute("UPDATE users SET role='admin' WHERE id=$1::uuid", users["admin"]["user_id"])
        # Portfolio fields for the pro user
        username = f"auditfe{SUFFIX}"
        await conn.execute(
            "UPDATE users SET public_username=$2, portfolio_enabled=true, portfolio_tagline='Audit portfolio' WHERE id=$1::uuid",
            users["pro"]["user_id"], username,
        )
    finally:
        await conn.close()

    pro = users["pro"]
    headers = {"Authorization": f"Bearer {pro['session_token']}", "Content-Type": "application/json"}
    rr = requests.post(
        f"{API}/resumes/",
        json={"title": "Audit FE Resume", "latex_content": LATEX},
        headers=headers,
        timeout=60,
    )
    rr.raise_for_status()
    resume = rr.json()
    resume_id = resume.get("id") or resume.get("resume", {}).get("id")
    share = requests.post(
        f"{API}/resumes/{resume_id}/share",
        json={"anonymous": False, "review_comments": True},
        headers=headers,
        timeout=60,
    )
    share.raise_for_status()
    share_data = share.json()
    share_token = share_data.get("share_token") or share_data.get("token")
    tracker = requests.post(
        f"{API}/tracker/applications",
        json={
            "company": "Audit Co",
            "role": "Senior Engineer",
            "status": "applied",
            "applied_date": "2026-11-27",
        },
        headers=headers,
        timeout=60,
    )
    payload = {
        "suffix": SUFFIX,
        "users": users,
        "pro_resume_id": resume_id,
        "share_token": share_token,
        "portfolio_username": username,
        "tenant_id": str(tenant_id),
        "tracker_status": tracker.status_code,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("suffix", "pro_resume_id", "share_token", "portfolio_username", "tenant_id", "tracker_status")}, indent=2))
    print("identities", OUT)


if __name__ == "__main__":
    asyncio.run(main())
