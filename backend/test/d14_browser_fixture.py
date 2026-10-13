"""Opt-in, loopback-only D14 browser-to-backend denial fixture.

Run only in an isolated test process:
    D14_BROWSER_FIXTURE=1 python -m uvicorn test.d14_browser_fixture:app \
        --host 127.0.0.1 --port 18073 --no-proxy-headers

The complete production API router and real EntitlementService policy decision
are used, but authentication, policy storage and every consequential handler
boundary are synthetic. This is NOT database-, provider- or deployment-backed
acceptance. It must never be mounted in the production application.
"""
from __future__ import annotations

import ipaddress
import os
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock, Mock

if os.environ.get("D14_BROWSER_FIXTURE") != "1":
    raise RuntimeError("D14 browser fixture requires explicit D14_BROWSER_FIXTURE=1 test opt-in")

# Configure dummy, unreachable infrastructure before importing application code.
# Never load a developer's provider, payment, email or authentication credentials.
for name in tuple(os.environ):
    if name.startswith("DODO_"):
        os.environ[name] = ""
os.environ.update({
    "SKIP_ENV_VALIDATION": "true", "ENVIRONMENT": "test", "DEPLOY_TARGET": "local",
    "DATABASE_URL": "postgresql+asyncpg://d14_dummy:d14_dummy@127.0.0.1:1/d14_browser_test",
    "REDIS_URL": "redis://127.0.0.1:1/15", "REDIS_CACHE_URL": "redis://127.0.0.1:1/14",
    "CELERY_BROKER_URL": "redis://127.0.0.1:1/15", "CELERY_RESULT_BACKEND": "redis://127.0.0.1:1/15",
    "JWT_SECRET_KEY": "d14_synthetic_jwt_secret_not_real_32chars",
    "BETTER_AUTH_SECRET": "d14_synthetic_auth_secret_not_real_32chars",
    "API_KEY_ENCRYPTION_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    "OPENAI_API_KEY": "", "RESEND_API_KEY": "", "DODO_MODE": "test", "RATE_LIMIT_ENABLED": "false",
})

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.api import ai_routes
from app.api.routes import router
from app.core.feature_registry import CAPABILITY_ROLES, PLAN_MATRIX_KEYS, gateable_keys
from app.database.connection import get_db
from app.middleware.auth_middleware import get_current_user_optional, get_current_user_required
from app.services.entitlement_service import entitlement_service

LEAVES = ("d14_latex", "d14_table_text", "d14_table_image", "d14_math_text", "d14_math_image")
FIXTURE_PATHS = frozenset({
    "/ai/generate-latex", "/ai/generate-table", "/ai/generate-table-image",
    "/ai/generate-math", "/ai/generate-math-image", "/__test/health",
    "/__test/policy", "/__test/effects", "/__test/evidence",
})
USER_ID = "11111111-1111-4111-8111-111111111111"
DeniedKey = Literal["d14_latex", "d14_table_text", "d14_table_image", "d14_math_text", "d14_math_image", "d14", "ai_writing"]


def enabled_blob():
    keys = gateable_keys()
    return {"kill": dict.fromkeys(keys, True),
            "matrix": {plan: dict.fromkeys(keys, True) for plan in PLAN_MATRIX_KEYS},
            "roles": {role: dict.fromkeys(keys, True) for role in CAPABILITY_ROLES}}


state = SimpleNamespace(role="user", blob=enabled_blob(), denied_key="d14", axis="global", snapshot_calls=0)
state.blob["kill"]["d14"] = False
app = FastAPI(title="Synthetic D14 loopback denial fixture", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def require_loopback(request: Request, call_next):
    try:
        loopback = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        return JSONResponse(status_code=403, content={"detail": "Test fixture accepts loopback requests only"})
    if request.url.path not in FIXTURE_PATHS:
        return JSONResponse(status_code=404, content={"detail": "Test fixture exposes D14 admissions only"})
    return await call_next(request)


async def synthetic_snapshot(user):
    if user != USER_ID:
        raise LookupError("Synthetic fixture identity mismatch")
    state.snapshot_calls += 1
    return state.role, "student", state.blob


# has_feature and _decide are untouched; only current identity/storage is fake.
entitlement_service._snapshot_for_user = synthetic_snapshot
app.dependency_overrides[get_current_user_optional] = lambda: USER_ID
app.dependency_overrides[get_current_user_required] = lambda: USER_ID

db = AsyncMock()
for name in ("execute", "commit", "flush", "refresh", "rollback"):
    getattr(db, name).side_effect = AssertionError(f"Synthetic denied route reached DB {name}")
app.dependency_overrides[get_db] = lambda: db

work = {}
for target, name, asynchronous in (
    (ai_routes.cache_manager, "get", True), (ai_routes.cache_manager, "set", True),
    (ai_routes, "read_upload_capped", True), (ai_routes, "_normalize_vision_image", False),
    (ai_routes, "_resolve_ai_api_key", True), (ai_routes, "_charge_ai_assist", True),
    (ai_routes, "_generate_math_body", True), (ai_routes.openai, "AsyncOpenAI", False),
    (entitlement_service, "refund_quota", True),
):
    double = (AsyncMock if asynchronous else Mock)(
        side_effect=AssertionError(f"Synthetic denied route reached {name}"),
    )
    setattr(target, name, double)
    work[name] = double


class PolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "support", "admin"] = "user"
    denied_key: DeniedKey | None = "d14"
    axis: Literal["global", "role", "family", "sku"] = "global"
    allow_table_text: bool = False


def effects():
    return {**{f"db.{name}": getattr(db, name).call_count for name in ("execute", "commit", "flush", "refresh", "rollback")},
            **{name: double.call_count for name, double in work.items()}}


@app.get("/__test/health")
async def fixture_health():
    return {"ok": True, "synthetic_auth": True, "synthetic_policy_storage": True,
            "real_policy_decisions": True, "real_registered_router": True,
            "live_providers": False, "database_acceptance": False}


@app.post("/__test/policy")
async def configure_policy(request: PolicyRequest):
    if request.denied_key is None and not request.allow_table_text:
        raise HTTPException(status_code=422, detail="A denial is required unless deterministic table-text is selected")
    if request.allow_table_text and request.denied_key is not None:
        raise HTTPException(status_code=422, detail="Deterministic admission requires denied_key=null")
    state.role = request.role
    state.blob = enabled_blob()
    state.denied_key = request.denied_key
    state.axis = request.axis
    state.snapshot_calls = 0
    if request.allow_table_text:
        for key in LEAVES:
            state.blob["kill"][key] = key == "d14_table_text"
    elif request.axis == "global":
        state.blob["kill"][request.denied_key] = False
    elif request.axis == "role":
        state.blob["roles"][request.role][request.denied_key] = False
    else:
        state.blob["matrix"]["pro" if request.axis == "family" else "student"][request.denied_key] = False
    for double in work.values():
        double.reset_mock()
    db.reset_mock()
    return {"role": state.role, "denied_key": state.denied_key, "axis": state.axis,
            "synthetic": True, "effects": effects()}


@app.get("/__test/effects")
async def fixture_effects():
    return {"effects": effects(), "snapshot_calls": state.snapshot_calls,
            "role": state.role, "denied_key": state.denied_key, "axis": state.axis}


@app.get("/__test/evidence")
async def fixture_evidence():
    counts = effects()
    return {"handler_effects": sum(counts.values()), "effects": counts,
            "snapshot_calls": state.snapshot_calls, "synthetic": True}


app.include_router(router)
