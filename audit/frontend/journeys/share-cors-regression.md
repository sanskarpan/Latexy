# Share PDF CORS/Range regression check

Reusable check for #2344. It creates a tiny object in the R2 bucket, presigns it, and asserts the browser-facing headers on the actual bucket, then deletes the object.

## Run

```powershell
backend/.venv/Scripts/python.exe audit/scripts/check_share_cors.py
```

Requires the same `R2_API_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `MINIO_BUCKET` env values used by the backend.

## Result - 2026-11-27

```text
PASS: Range 206, ACAO=https://latexy.xyz
PASS: expose=Content-Length,Content-Range,Accept-Ranges,ETag,Content-Type
PASS: disallowed origin https://evil.example has no ACAO
cleaned: audit-cors-check/regression-1795803092.txt
```

This protects the fixed behavior: allowed first-party origins receive `Access-Control-Allow-Origin` and `Content-Range` is exposed, Range requests return `206`, and a disallowed origin receives no ACAO.

The script is intentionally standalone. CI wiring (run on deploy/schedule with R2 secrets, fail the workflow on non-zero exit) is tracked separately so it does not block the user-visible fix.
