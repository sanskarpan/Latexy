"""Redact live tokens from the committed identity matrix before merge.

The full matrix is saved outside the repository for the short remainder of the
audit. The committed matrix keeps user/tenant/key IDs so cleanup and evidence
remain reproducible, but no usable bearer credential.
"""
import json
from pathlib import Path

ROOT = Path(r"C:\Users\Sansk\Projects\Latexy")
MATRIX = ROOT / "audit/plans/identity-matrix.json"
SECRET_COPY = Path(r"C:\Users\Sansk\AppData\Local\Temp\opencode\audit-identity-secrets.json")


def main():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    SECRET_COPY.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    redacted = 0
    for identity in matrix.get("identities", {}).values():
        if identity.get("session_token"):
            identity["session_token"] = "REDACTED - valid only during the 2026-11-27 audit window; session deleted"
            redacted += 1
        if identity.get("api_key"):
            identity["api_key"] = "REDACTED - fixture key; revoked and row deleted"
            redacted += 1
    matrix["secrets_note"] = (
        "Bearer tokens and the fixture developer key were redacted before merge. "
        "They were valid only during the 2026-11-27 audit window and were deleted by cleanup_identities.py. "
        "User, tenant, subscription and key IDs remain for reproducibility."
    )
    MATRIX.write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"redacted_fields": redacted, "secret_copy": str(SECRET_COPY)}))


if __name__ == "__main__":
    main()
