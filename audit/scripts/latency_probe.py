"""Warm latency baseline for representative production endpoints."""
import csv
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\Users\Sansk\Projects\Latexy")
MATRIX = json.loads((ROOT / "audit/plans/identity-matrix.json").read_text(encoding="utf-8"))
OUT = ROOT / "audit/latency/endpoints.csv"
BASE = "https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run"
SAMPLES = 30

ENDPOINTS = [
    ("/health", None, "anonymous"),
    ("/readyz", None, "anonymous"),
    ("/jobs/health", None, "anonymous"),
    ("/me", MATRIX["identities"]["pro-monthly"]["session_token"], "pro"),
    ("/config/entitlements", MATRIX["identities"]["pro-monthly"]["session_token"], "pro"),
    ("/subscription/current", MATRIX["identities"]["pro-monthly"]["session_token"], "pro"),
    ("/resumes", MATRIX["identities"]["pro-monthly"]["session_token"], "pro"),
    ("/resumes/builder/templates", MATRIX["identities"]["pro-monthly"]["session_token"], "pro"),
    ("/analytics/admin/overview?days=30", MATRIX["identities"]["admin-superadmin"]["session_token"], "admin"),
]


def pct(values, p):
    if not values:
        return None
    values = sorted(values)
    idx = min(len(values) - 1, max(0, round((p / 100) * (len(values) - 1))))
    return values[idx]


def main():
    rows = []
    for path, token, identity in ENDPOINTS:
        latencies, statuses, sizes = [], [], []
        for _ in range(SAMPLES):
            req = urllib.request.Request(
                BASE + path,
                headers={"Accept": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
            )
            start = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read()
                    latencies.append((time.perf_counter() - start) * 1000)
                    statuses.append(r.status)
                    sizes.append(len(body))
            except urllib.error.HTTPError as e:
                latencies.append((time.perf_counter() - start) * 1000)
                statuses.append(e.code)
                sizes.append(len(e.read()))
            except Exception:
                latencies.append((time.perf_counter() - start) * 1000)
                statuses.append(0)
                sizes.append(0)
            time.sleep(1.05)
        ok = sum(1 for s in statuses if 200 <= s < 300)
        rows.append({
            "path": path, "identity": identity, "samples": SAMPLES,
            "ok": ok, "error_rate_pct": round((SAMPLES - ok) / SAMPLES * 100, 2),
            "p50_ms": round(pct(latencies, 50), 1), "p95_ms": round(pct(latencies, 95), 1),
            "p99_ms": round(pct(latencies, 99), 1), "min_ms": round(min(latencies), 1),
            "max_ms": round(max(latencies), 1), "mean_ms": round(statistics.mean(latencies), 1),
            "mean_bytes": round(statistics.mean(sizes), 1), "status_codes": ",".join(map(str, sorted(set(statuses)))),
        })
        print(path, rows[-1]["p50_ms"], rows[-1]["p95_ms"], "ok", ok)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
