"""
Modal task dispatcher — used when DEPLOY_TARGET=modal.

Call spawn(function_name, payload) to fire-and-forget a Modal function.
All imports are lazy so this module is safe to import in local-dev mode.
"""
import asyncio
import logging
import weakref
from collections.abc import Callable
from typing import Any

from .engine_observability import engine_span
from .tracing import inject_trace_context

logger = logging.getLogger(__name__)

_APP_NAME = "latexy-backend"
_SUBMISSION_CONCURRENCY = 8
_submission_limits: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


async def submit_async(submission: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run an existing broker submission without blocking the API event loop.

    The semaphore bounds SDK calls admitted to the executor. Shielding the
    runner is deliberate: cancelling the HTTP request cannot stop a spawn
    already running in a thread, and must not free its permit prematurely.
    Callers retain their durable dispatch intent before awaiting this helper.
    Both Modal and Celery keep their existing synchronous payload builders.
    """
    loop = asyncio.get_running_loop()
    limit = _submission_limits.setdefault(loop, asyncio.Semaphore(_SUBMISSION_CONCURRENCY))
    with engine_span("dispatch_wait"):
        await limit.acquire()

    async def run() -> Any:
        try:
            with engine_span("dispatch_call"):
                return await asyncio.to_thread(submission, *args, **kwargs)
        finally:
            limit.release()

    runner = asyncio.create_task(run())

    def observe(task: asyncio.Task) -> None:
        # Retrieve errors even if a disconnected caller no longer awaits us.
        # Its durable dispatch intent remains available to recovery workers.
        if not task.cancelled():
            task.exception()

    runner.add_done_callback(observe)
    return await asyncio.shield(runner)


def spawn(function_name: str, payload: dict) -> None:
    """Fire-and-forget a Modal function by name."""
    import modal  # noqa: PLC0415 — intentionally lazy
    fn = modal.Function.from_name(_APP_NAME, function_name)
    if function_name in {"run_latex_task", "run_orchestrator_task", "run_llm_task"}:
        carrier = inject_trace_context({})
        safe_carrier = {key: value for key, value in carrier.items() if key in {"traceparent", "tracestate"}}
        if safe_carrier:
            payload = {**payload, "_trace_context": safe_carrier}
    fn.spawn(payload)
    logger.debug("Modal spawn: %s", function_name)
