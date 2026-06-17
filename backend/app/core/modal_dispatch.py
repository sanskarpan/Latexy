"""
Modal task dispatcher — used when DEPLOY_TARGET=modal.

Call spawn(function_name, payload) to fire-and-forget a Modal function.
All imports are lazy so this module is safe to import in local-dev mode.
"""
import logging

logger = logging.getLogger(__name__)

_APP_NAME = "latexy-backend"


def spawn(function_name: str, payload: dict) -> None:
    """Fire-and-forget a Modal function by name."""
    import modal  # noqa: PLC0415 — intentionally lazy
    fn = modal.Function.from_name(_APP_NAME, function_name)
    fn.spawn(payload)
    logger.debug("Modal spawn: %s", function_name)
