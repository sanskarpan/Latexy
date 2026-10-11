"""Read-only Modal renderer configuration checks, never image certification."""
from __future__ import annotations

import os
import re

from ...core.config import settings
from .backend import resolve_backend


def renderer_configuration_report() -> dict:
    """Check the candidate API's bound configuration without creating a renderer.

    The existing resolver only selects a backend and reads its local identity.
    This check never creates a VM, probes a provider, opens a database connection,
    or verifies the pinned image's contents. Reports contain no configuration
    values: a well-formed tuple is only an operator assertion of certification.
    """
    known_compilers = {"pdflatex", "xelatex", "lualatex"}
    allowed = settings.ALLOWED_LATEX_COMPILERS
    default = settings.DEFAULT_LATEX_COMPILER
    new_default = settings.DEFAULT_NEW_RESUME_COMPILER
    allowed_valid = (isinstance(allowed, (list, tuple)) and bool(allowed)
                     and all(isinstance(compiler, str) and compiler in known_compilers for compiler in allowed))
    defaults_valid = (allowed_valid and isinstance(default, str) and isinstance(new_default, str)
                      and default in allowed and new_default in allowed)
    requires_lua = (default == "lualatex" or new_default == "lualatex"
                    or isinstance(allowed, (list, tuple)) and "lualatex" in allowed)
    vm_configuration_valid = (os.environ.get("MODAL_ENGINE_VM_CERTIFIED") == "true"
        and re.fullmatch(r"im-[A-Za-z0-9]{1,128}", os.environ.get("MODAL_ENGINE_VM_IMAGE_ID", "")) is not None
        and re.fullmatch(r"[0-9a-f]{64}", os.environ.get("MODAL_ENGINE_VM_ASSETS_FINGERPRINT", "")) is not None)
    checks = {
        "modal_runtime": os.environ.get("DEPLOY_TARGET") == "modal",
        "accepted_compilers_supported": bool(allowed_valid),
        "defaults_accepted": bool(defaults_valid),
        "required_vm_configuration_valid": bool(not requires_lua or vm_configuration_valid),
        "accepted_compilers_resolve": False,
    }
    reasons = []
    if not checks["modal_runtime"]:
        reasons.append("modal_runtime_required")
    if not checks["accepted_compilers_supported"] or not checks["defaults_accepted"]:
        reasons.append("compiler_configuration_invalid")
    if not checks["required_vm_configuration_valid"]:
        reasons.append("lua_vm_configuration_missing_or_invalid")
    if not reasons:
        try:
            for compiler in sorted(set(allowed)):
                resolve_backend(compiler)
        except Exception:
            # Exception strings may include deployment configuration. Never
            # print them or return runtime/backend identities in this report.
            reasons.append("renderer_configuration_unavailable")
        else:
            checks["accepted_compilers_resolve"] = True
    return {
        "configuration_ready": all(checks.values()),
        "certification_verified": False,
        "checks": checks,
        "reasons": reasons,
    }
