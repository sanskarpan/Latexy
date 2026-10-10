"""Role-toggle audit fields must come from the allowlisted registry, not request text."""
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api import admin_routes
from app.core.feature_registry import CAPABILITY_ROLES, get_feature


@pytest.mark.parametrize("role", CAPABILITY_ROLES)
async def test_role_toggle_logs_canonical_registry_fields(monkeypatch, role):
    update = AsyncMock()
    state = AsyncMock(return_value={"verified": True})
    logger = Mock()
    monkeypatch.setattr(admin_routes.entitlement_service, "set_role_cell", update)
    monkeypatch.setattr(admin_routes.entitlement_service, "get_state", state)
    monkeypatch.setattr(admin_routes, "logger", logger)
    # Force equal values constructed at runtime rather than source constants.
    body = admin_routes.RoleMatrixUpdateRequest(
        role="".join(list(role)), feature_key="".join(["b", "0", "3"]),
        enabled=False, expected_enabled=True,
    )
    db = Mock()
    result = await admin_routes.update_role_matrix_cell(body, db, "synthetic-admin-id")
    assert result == {"verified": True}
    update.assert_awaited_once_with(role, "b03", False, db, expected_enabled=True)
    extra = logger.info.call_args.kwargs["extra"]
    assert extra["role"] is next(known for known in CAPABILITY_ROLES if known == role)
    assert extra["feature_key"] is get_feature("b03").key
    assert extra["enabled"] is False
    logger.info.assert_called_once_with("admin_entitlement_role_updated", extra=extra)


@pytest.mark.parametrize(("role", "feature", "status"), [
    ("user\nforged-event", "b03", 400),
    ("admin\rforged-event", "b03", 400),
    ("reader", "b03", 400),
    ("user", "b03\nforged-event", 404),
    ("user", "b03\rforged-event", 404),
    ("user", "compile", 404),
    ("user", "unknown", 404),
])
async def test_invalid_role_toggle_cannot_write_or_emit_success_audit(monkeypatch, role, feature, status):
    update = AsyncMock()
    state = AsyncMock()
    logger = Mock()
    monkeypatch.setattr(admin_routes.entitlement_service, "set_role_cell", update)
    monkeypatch.setattr(admin_routes.entitlement_service, "get_state", state)
    monkeypatch.setattr(admin_routes, "logger", logger)
    body = admin_routes.RoleMatrixUpdateRequest(role=role, feature_key=feature, enabled=True)
    with pytest.raises(HTTPException) as exc:
        await admin_routes.update_role_matrix_cell(body, Mock(), "synthetic-admin-id")
    assert exc.value.status_code == status
    update.assert_not_awaited()
    state.assert_not_awaited()
    logger.info.assert_not_called()
