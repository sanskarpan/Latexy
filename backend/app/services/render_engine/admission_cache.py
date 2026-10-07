"""Bounded, non-compiling API shortcut after normal durable job admission."""
from __future__ import annotations

import asyncio
from typing import Any

from ...core.config import settings
from .artifacts import RENDERER_EPOCH, canonical_json, parse_manifest, sha256
from .backend import resolve_backend
from .modal_sandbox import ModalEngineUnavailable


def prepare_direct_request(kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    # Auto-fit needs real probes to determine its prepared source and cannot be
    # evaluated by this cache-only admission shortcut.
    if kwargs.get("auto_fit"):
        return None
    from ...workers.latex_worker import (
        _ALLOWED_EXTRA_FLAGS,
        _MAIN_FILE_RE,
        _WATERMARK_MAX_LEN,
        _WATERMARK_RE,
        _inject_draft_graphics,
        _inject_packages,
        _inject_watermark,
        compile_cache_key,
        latex_service,
    )
    source = kwargs.get("latex_content")
    if not isinstance(source, str) or not latex_service.validate_latex_content(source):
        return None
    scope = (f"user:{kwargs['user_id']}" if kwargs.get("user_id") else
             f"device:{kwargs['device_fingerprint']}" if kwargs.get("device_fingerprint") else None)
    if not scope:
        return None
    compiler = kwargs.get("compiler") or settings.DEFAULT_LATEX_COMPILER
    if compiler not in settings.ALLOWED_LATEX_COMPILERS:
        compiler = settings.DEFAULT_LATEX_COMPILER
    try:
        backend = resolve_backend(compiler)
    except ModalEngineUnavailable:
        return None
    if not backend.cacheable:
        return None
    cs = kwargs.get("compile_settings") or {}
    prepared = source
    packages = cs.get("extra_packages") or []
    if packages and isinstance(packages, list):
        prepared = _inject_packages(prepared, packages)
    if cs.get("draft_mode") is True:
        prepared = _inject_draft_graphics(prepared)
    watermark = kwargs.get("watermark")
    if watermark:
        if not isinstance(watermark, str) or not _WATERMARK_RE.match(watermark) or len(watermark) > _WATERMARK_MAX_LEN:
            return None
        prepared = _inject_watermark(prepared, watermark)
    if not latex_service.validate_latex_content(prepared):
        return None
    main_file = str(cs.get("main_file") or "resume.tex")
    if not _MAIN_FILE_RE.fullmatch(main_file):
        main_file = "resume.tex"
    flags = [flag for flag in (cs.get("latexmk_flags") or []) if flag in _ALLOWED_EXTRA_FLAGS]
    canonical_settings = {**cs, "main_file": main_file, "latexmk_flags": flags,
                          "halt_on_error": cs.get("halt_on_error") is not False}
    key = compile_cache_key(prepared, compiler, canonical_settings, scope)
    if key is None:
        return None
    return key, {"owner_scope": scope, "source": source, "render_source": prepared,
                 "compiler": compiler, "settings": canonical_settings,
                 "engine_fingerprint": backend.engine_fingerprint}


async def has_exact_render_cache(redis_client: Any, kwargs: dict[str, Any]) -> bool:
    # Preparation/JSON hashing can be proportional to source length; keep it
    # off the API event loop along with all worker and storage operations.
    prepared = await asyncio.to_thread(prepare_direct_request, kwargs)
    if prepared is None:
        return False
    key, request = prepared
    raw = await redis_client.get(key)
    if not raw:
        return False
    try:
        manifest = parse_manifest(raw)
        return (manifest.owner_scope_sha256 == sha256(request["owner_scope"])
                and manifest.render_source_sha256 == sha256(request["render_source"])
                and manifest.settings_sha256 == sha256(canonical_json(request["settings"]))
                and manifest.compiler == request["compiler"]
                and manifest.engine_fingerprint == request["engine_fingerprint"]
                and manifest.renderer_epoch == RENDERER_EPOCH)
    except (ValueError, TypeError):
        return False


def execute_exact_render_cache(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Call in an API bounded executor after admission; never spawn TeX here."""
    from ...workers.event_publisher import initialize_worker_redis
    from ...workers.latex_worker import compile_latex_task

    initialize_worker_redis(settings.REDIS_URL, password=settings.REDIS_PASSWORD)
    return compile_latex_task.apply(kwargs={**kwargs, "cache_only": True}, throw=True).get()
