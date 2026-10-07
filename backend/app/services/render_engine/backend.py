"""Server-owned execution identity, resolved without creating an engine/VM."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from .modal_sandbox import ModalEngineUnavailable, create_modal_engine
from .version import renderer_fingerprint

VM_POLICY = "lua-credential-free-vm-v1"
NATIVE_LUA_POLICY = "lua-landlock-seccomp-v2"


@dataclass(frozen=True)
class RendererBackend:
    kind: str
    engine_fingerprint: str
    policy_identity: str | None
    image_id: str | None = None
    assets_fingerprint: str | None = None
    cacheable: bool = True


def resolve_backend(compiler: str) -> RendererBackend:
    """Admission and workers share immutable operator configuration, never client metadata."""
    if compiler == "lualatex" and os.getenv("DEPLOY_TARGET") == "modal":
        image_id = os.getenv("MODAL_ENGINE_VM_IMAGE_ID", "")
        assets = os.getenv("MODAL_ENGINE_VM_ASSETS_FINGERPRINT", "")
        if (os.getenv("MODAL_ENGINE_VM_CERTIFIED") != "true"
                or not re.fullmatch(r"im-[A-Za-z0-9]{1,128}", image_id)
                or not re.fullmatch(r"[0-9a-f]{64}", assets)):
            raise ModalEngineUnavailable("Certified credential-free renderer capability is unavailable")
        material = json.dumps({"image_id": image_id, "assets": assets, "policy": VM_POLICY}, sort_keys=True)
        identity = "modal-vm-assets:" + hashlib.sha256(material.encode()).hexdigest()
        return RendererBackend("modal_vm", identity, VM_POLICY, image_id, assets)
    selected = os.getenv("LATEXY_RENDER_BACKEND", "auto")
    if selected == "auto":
        selected = "docker" if shutil.which("docker") else "native"
    if selected not in {"native", "docker"}:
        raise ModalEngineUnavailable("Unknown server renderer backend")
    policy = NATIVE_LUA_POLICY if compiler == "lualatex" else None
    # A selected Docker engine must not silently fall back to the native engine.
    # Its operator-pinned image digest is distinct from the worker's assets.
    if selected == "docker":
        from ...core.config import settings

        image = settings.LATEX_DOCKER_IMAGE
        pinned = bool(re.search(r"@sha256:[0-9a-f]{64}$", image))
        fingerprint = "docker-image:" + image
        return RendererBackend(selected, fingerprint, policy, cacheable=pinned)
    else:
        fingerprint = renderer_fingerprint()
    return RendererBackend(selected, fingerprint, policy)


def effective_renderer_fingerprint(compiler: str) -> str:
    return resolve_backend(compiler).engine_fingerprint


def start_engine_process(command: list[str], *, cwd: str, env: dict[str, str], workspace: str,
                         compiler: str, timeout: float, backend: RendererBackend | None = None,
                         actual_engine: str | None = None, engine_session: Any = None,
                         popen_factory: Any = subprocess.Popen, **popen_options: Any):
    chosen = backend or resolve_backend(compiler)
    engine = actual_engine or compiler
    if chosen.kind != "modal_vm":
        return popen_factory(command, cwd=cwd, env=env, **popen_options)
    try:
        index = command.index(engine)
    except ValueError as exc:
        raise ModalEngineUnavailable("Engine arguments are not a recognized server command") from exc
    return create_modal_engine(workspace=workspace, compiler=engine, arguments=command[index + 1:],
                               timeout=timeout, enabled=True, image_id=chosen.image_id,
                               expected_assets=chosen.assets_fingerprint, policy="credential_free_vm",
                               session=engine_session)


def close_engine_session(process: Any) -> None:
    session = getattr(process, "renderer_session", None)
    if session is not None:
        session.close()
