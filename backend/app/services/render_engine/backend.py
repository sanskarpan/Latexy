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

from .functional_acceptance_policy import is_trusted_functional_acceptance_environment
from .modal_sandbox import ModalEngineUnavailable, create_modal_engine
from .version import renderer_fingerprint

VM_POLICY = "lua-credential-free-vm-v1"
FUNCTIONAL_TEST_VM_POLICY = "lua-credential-free-vm-functional-test-only-v1"
NATIVE_LUA_POLICY = "lua-landlock-seccomp-v2"


@dataclass(frozen=True)
class RendererBackend:
    kind: str
    engine_fingerprint: str
    policy_identity: str | None
    image_id: str | None = None
    assets_fingerprint: str | None = None
    cacheable: bool = True
    certification_flag_asserted: bool = False
    boundary_preflight: bool = True


def resolve_backend(compiler: str) -> RendererBackend:
    """Admission and workers share immutable operator configuration, never client metadata."""
    functional_setting = os.getenv("MODAL_ENGINE_VM_FUNCTIONAL_ONLY_ACCEPTANCE", "")
    if functional_setting not in {"", "true"}:
        raise ModalEngineUnavailable("Invalid functional-only renderer configuration")
    if compiler == "lualatex" and os.getenv("DEPLOY_TARGET") == "modal":
        image_id = os.getenv("MODAL_ENGINE_VM_IMAGE_ID", "")
        assets = os.getenv("MODAL_ENGINE_VM_ASSETS_FINGERPRINT", "")
        certified = os.getenv("MODAL_ENGINE_VM_CERTIFIED") == "true"
        functional_only = functional_setting == "true"
        if (not re.fullmatch(r"im-[A-Za-z0-9]{1,128}", image_id)
                or not re.fullmatch(r"[0-9a-f]{64}", assets)):
            raise ModalEngineUnavailable("Modal credential-free renderer capability is unavailable")
        if functional_only:
            environment = os.getenv("MODAL_ENVIRONMENT", "")
            if (certified or os.getenv("ENVIRONMENT") != "test" or not environment
                    or not is_trusted_functional_acceptance_environment(environment)):
                raise ModalEngineUnavailable("Functional-only renderer mode is restricted to nonproduction tests")
            policy = FUNCTIONAL_TEST_VM_POLICY
            material = json.dumps({"image_id": image_id, "assets": assets, "policy": policy}, sort_keys=True)
            identity = "modal-vm-functional-test-assets:" + hashlib.sha256(material.encode()).hexdigest()
            return RendererBackend(
                "modal_vm", identity, policy, image_id, assets, cacheable=False,
                certification_flag_asserted=False, boundary_preflight=False,
            )
        if not certified:
            raise ModalEngineUnavailable("Certified credential-free renderer capability is unavailable")
        material = json.dumps({"image_id": image_id, "assets": assets, "policy": VM_POLICY}, sort_keys=True)
        identity = "modal-vm-assets:" + hashlib.sha256(material.encode()).hexdigest()
        return RendererBackend(
            "modal_vm", identity, VM_POLICY, image_id, assets,
            certification_flag_asserted=True, boundary_preflight=True,
        )
    if (compiler == "lualatex"
            and functional_setting == "true"):
        raise ModalEngineUnavailable("Functional-only renderer mode requires a Modal test runtime")
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
                               boundary_preflight=chosen.boundary_preflight, session=engine_session)


def close_engine_session(process: Any) -> None:
    session = getattr(process, "renderer_session", None)
    if session is not None:
        session.close()
