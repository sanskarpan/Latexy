"""Read-only GET sweep across the source OpenAPI, using audit identities."""
import csv
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\Users\Sansk\Projects\Latexy")
SPEC = json.loads((ROOT / "audit/inventory/openapi-source.json").read_text(encoding="utf-8"))
MATRIX = json.loads((ROOT / "audit/plans/identity-matrix.json").read_text(encoding="utf-8"))
OUT = ROOT / "audit/inventory/http-disposition.csv"
BASE = "https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run"

TOKENS = {
    "anonymous": None,
    "free": MATRIX["identities"]["free"]["session_token"],
    "pro": MATRIX["identities"]["pro-monthly"]["session_token"],
    "admin": MATRIX["identities"]["admin-superadmin"]["session_token"],
    "team": MATRIX["identities"]["team-owner"]["session_token"],
}


def identity_for(path: str) -> str:
    if path.startswith("/admin"):
        return "admin"
    if path.startswith("/tenants"):
        return "team"
    if path.startswith(("/account", "/byok", "/developer", "/me", "/subscription", "/trial")):
        return "free"
    if path.startswith(("/public", "/share", "/portfolio", "/auth", "/health", "/readyz", "/jobs/health")):
        return "anonymous"
    return "pro"


def main():
    rows = []
    for path, methods in sorted(SPEC.get("paths", {}).items()):
        if "get" not in methods:
            continue
        op = methods["get"]
        row = {
            "method": "GET", "path": path, "operation_id": op.get("operationId", ""),
            "auth_identity": identity_for(path),
            "disposition": "", "http_status": "", "latency_ms": "", "content_type": "",
            "bytes": "", "request_id": "", "reason": "",
        }
        if "{" in path:
            row["disposition"] = "blocked"
            row["reason"] = "path parameter requires a domain fixture"
            rows.append(row)
            continue
        ident = row["auth_identity"]
        req = urllib.request.Request(
            BASE + path,
            headers={"Accept": "application/json", **({"Authorization": f"Bearer {TOKENS[ident]}"} if TOKENS[ident] else {})},
        )
        start = time.time()
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                row.update({
                    "disposition": "tested", "http_status": r.status,
                    "latency_ms": round((time.time() - start) * 1000, 1),
                    "content_type": r.headers.get("content-type", ""),
                    "bytes": len(body), "request_id": r.headers.get("x-request-id", ""),
                })
        except urllib.error.HTTPError as e:
            body = e.read()
            row.update({
                "disposition": "tested", "http_status": e.code,
                "latency_ms": round((time.time() - start) * 1000, 1),
                "content_type": e.headers.get("content-type", ""),
                "bytes": len(body), "request_id": e.headers.get("x-request-id", ""),
                "reason": "auth/entitlement/fixture response" if e.code < 500 else "server error",
            })
        except Exception as e:
            row.update({"disposition": "error", "reason": str(e)[:160]})
        rows.append(row)
        time.sleep(1.05)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    summary = {}
    for r in rows:
        summary[r["disposition"]] = summary.get(r["disposition"], 0) + 1
        if r["http_status"]:
            key = f"http_{r['http_status']}"
            summary[key] = summary.get(key, 0) + 1
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
