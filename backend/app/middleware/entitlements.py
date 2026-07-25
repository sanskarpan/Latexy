"""Entitlement enforcement dependency factories.

``require_feature(key)`` gates an AUTHENTICATED route (401 if anonymous, 403 if
the user's plan/kill-switch disables the feature).

``require_feature_optional(key)`` gates a route that also serves ANONYMOUS/trial
users: anonymous callers are evaluated against the ``free`` plan family, so an
admin who disables a feature for free (or globally) blocks anonymous access too,
while authenticated users are evaluated against their own plan. When the feature
is enabled it is a no-op and the underlying handler (incl. its trial logic) runs.

Both raise HTTP 403 with the standard error envelope when access is denied.
Entitlement resolution runs on a dedicated session inside the service, so these
never touch the request transaction.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from ..core.errors import error_body
from ..services.entitlement_service import entitlement_service
from .auth_middleware import get_current_user_optional, get_current_user_required


def _denied(key: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=error_body(
            "feature_disabled",
            f"The '{key}' feature is not available on your plan.",
            None,
        ),
    )


def require_feature(key: str):
    """Return an async dependency enforcing ``key`` for an authenticated user."""

    async def _dep(user: str = Depends(get_current_user_required)) -> str:
        if not await entitlement_service.has_feature(key, user=user):
            raise _denied(key)
        return user

    return _dep


def require_feature_optional(key: str):
    """Return an async dependency enforcing ``key`` for auth-optional routes.

    Anonymous callers (no session) are evaluated against the ``free`` family.
    Returns the user_id or None (so the handler keeps its optional-auth shape).
    """

    async def _dep(user=Depends(get_current_user_optional)):
        if not await entitlement_service.has_feature(key, user=user):
            raise _denied(key)
        return user

    return _dep
