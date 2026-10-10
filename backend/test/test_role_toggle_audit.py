"""Role-toggle audit fields must come from the allowlisted registry, not request text."""
import json
import logging
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api import admin_routes
from app.core.feature_registry import CAPABILITY_ROLES, get_feature
from app.core.logging import JsonFormatter


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
    assert update.call_args.args[0] is next(known for known in CAPABILITY_ROLES if known == role)
    assert update.call_args.args[1] is get_feature("b03").key
    logger.info.assert_called_once_with(
        "admin_entitlement_role_updated admin_user_id=%s role=%s feature_key=%s enabled=%s",
        "synthetic-admin-id", role, "b03", False,
    )
    record = logging.LogRecord("audit", logging.INFO, __file__, 1, logger.info.call_args.args[0], logger.info.call_args.args[1:], None)
    message = json.loads(JsonFormatter().format(record))["message"]
    assert f"role={role} feature_key=b03 enabled=False" in message
    assert "admin_user_id=synthetic-admin-id" in message


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


@pytest.mark.parametrize("separator", ["\r", "\n", "\r\n", "\x85", "\u2028", "\u2029"])
def test_audit_sink_escapes_line_breaks_for_plain_and_json_handlers(monkeypatch, separator):
    logger = Mock()
    monkeypatch.setattr(admin_routes, "logger", logger)
    injected = f"known{separator}forged-event"
    admin_routes._log_role_toggle(injected, injected, injected, True)
    logger.info.assert_called_once()
    message, *arguments = logger.info.call_args.args
    record = logging.LogRecord("audit", logging.INFO, __file__, 1, message, tuple(arguments), None)
    plain = record.getMessage()
    assert len(plain.splitlines()) == 1
    assert "forged-event" in plain  # visible as escaped data, never a new record
    assert all(character not in plain for character in "\r\n\x85\u2028\u2029")
    formatted = JsonFormatter().format(record)
    assert len(formatted.splitlines()) == 1
    assert json.loads(formatted)["message"] == plain
