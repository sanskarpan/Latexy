"""Capture per-cohort production entitlement/quota baselines."""
import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\Users\Sansk\Projects\Latexy")
MATRIX = ROOT / "audit/plans/identity-matrix.json"
OUT = ROOT / "audit/plans/cohort-baselines.json"
BASE = "https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run"


def get(path, token=None, headers=None):
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json", **(headers or {})})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = body[:500]
            return {"status": r.status, "body": parsed}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = body[:500]
        return {"status": e.code, "body": parsed}
    except Exception as e:
        return {"status": None, "error": str(e)}


def main():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    out = {"suffix": matrix["suffix"], "window_start": matrix["window_start"], "cohorts": {}}
    for cohort, ident in matrix["identities"].items():
        if "user_id" not in ident:
            out["cohorts"][cohort] = {"identity": ident, "no_session": True}
            continue
        token = ident["session_token"]
        result = {
            "user_id": ident["user_id"],
            "plan": ident.get("plan"),
            "expected_status": ident.get("status"),
            "role": ident.get("role"),
            "me": get("/me", token),
            "entitlements": get("/config/entitlements", token),
            "subscription": get("/subscription/current", token),
            "trial": get("/public/trial-status", token),
        }
        if cohort == "developer-api":
            result["developer_keys"] = get("/developer/keys", token)
        if cohort in ("team-owner", "team-member"):
            result["tenants"] = get("/tenants/my", token)
        if ident.get("role") in ("admin", "support"):
            result["admin_users"] = get("/admin/users?limit=1", token)
        out["cohorts"][cohort] = result
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    summary = {k: {kk: (vv.get("status") if isinstance(vv, dict) else None) for kk, vv in v.items() if isinstance(vv, dict)} for k, v in out["cohorts"].items()}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
