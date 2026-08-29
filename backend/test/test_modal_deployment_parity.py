"""
Guards against the class of bug that caused P0 outages #954 and #956.

Production runs on Modal (``backend/modal_app.py``), not docker-compose and not
k8s. Every one of those outages was the same shape: code that is correct in local
dev and wrong on Modal, on a deployment path with no test coverage at all. Before
this file, ``grep -rn 'DEPLOY_TARGET|modal' backend/test`` returned nothing.

These tests are deliberately STATIC — they parse ``modal_app.py`` with ``ast``
rather than importing it, because ``modal`` is not in requirements.txt (it is a
deploy-time CLI tool) and importing the module would try to build images. That
keeps them runnable on every PR in normal CI, which is the whole point: a check
that only runs at deploy time would not have caught either outage.

Where a gap is known and not yet fixed, it is listed in an explicit waiver set
with a reason. The waivers are asserted to be exact: adding a new gap fails, and
fixing one without removing it from the waiver also fails, so the list cannot rot.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
MODAL_APP = BACKEND / "modal_app.py"
WORKERS = BACKEND / "app" / "workers"
DOCKERFILE = BACKEND / "Dockerfile"
DEPLOY_WORKFLOW = BACKEND.parent / ".github" / "workflows" / "deploy-modal.yml"


# ── helpers ──────────────────────────────────────────────────────────────────


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _modal_function_names() -> set[str]:
    """Names of every ``@app.function``-decorated function in modal_app.py."""
    names = set()
    for node in ast.walk(_parse(MODAL_APP)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(target, ast.Attribute) and target.attr == "function":
                names.add(node.name)
    return names


def _modal_apt_packages() -> dict[str, set[str]]:
    """image variable name -> set of apt packages it installs.

    Resolves any splatted module-level list (``*_APT_BASE``, ``*_APT_LATEX``, ...)
    by reading that list literal too, so grouping packages into a shared constant
    does not blind the check.
    """
    tree = _parse(MODAL_APP)

    # Every module-level list-of-strings, by name, so a splat can be resolved.
    constants: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.List):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name):
                constants[t.id] = {
                    e.value for e in node.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                }

    images: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.endswith("_image"):
            continue
        pkgs: set[str] = set()
        # Walk the builder chain looking for .apt_install(...)
        for call in ast.walk(node.value):
            if not isinstance(call, ast.Call):
                continue
            fn = call.func
            if not (isinstance(fn, ast.Attribute) and fn.attr == "apt_install"):
                continue
            for arg in call.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    pkgs.add(arg.value)
                elif isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Name):
                    pkgs |= constants.get(arg.value.id, set())
        images[target.id] = pkgs
    return images


def _dispatch_sites() -> list[tuple[str, str, bool]]:
    """(module, enclosing function, has_modal_branch) for each Celery dispatch.

    A "dispatch" is a ``.apply_async(`` or ``.delay(`` call. The Modal branch is
    the established ``if os.environ.get("DEPLOY_TARGET") == "modal":`` guard that
    calls ``modal_dispatch.spawn``.
    """
    sites = []
    for path in sorted(WORKERS.glob("*.py")):
        tree = _parse(path)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            dispatches = [
                c for c in ast.walk(fn)
                if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Attribute)
                and c.func.attr in {"apply_async", "delay"}
            ]
            if not dispatches:
                continue
            src = ast.get_source_segment(path.read_text(encoding="utf-8"), fn) or ""
            has_modal = 'DEPLOY_TARGET' in src and '"modal"' in src and "spawn(" in src
            sites.append((path.name, fn.name, has_modal))
    return sites


def test_modal_delivery_synchronizes_templates_and_assets_after_deploy():
    """New source templates must become usable without a manual production repair."""
    workflow = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    deploy = workflow.index('modal deploy --env main --strategy rolling --tag "$DEPLOY_SHA" modal_app.py')
    sync = workflow.index("modal run --env main modal_app.py::sync_templates")
    backfill = workflow.index("modal run --env main scripts/backfill_template_assets.py")
    health = workflow.index("Verify production backend health")
    catalog = workflow.index("Verify source template catalog and assets")

    assert deploy < sync < backfill < health < catalog
    assert "sync_templates" in _modal_function_names()

    tree = _parse(MODAL_APP)
    sync_fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "sync_templates"
    )
    source = ast.get_source_segment(MODAL_APP.read_text(encoding="utf-8"), sync_fn) or ""
    assert "app.scripts.seed_templates" in source


# ── 1. task dispatch parity ──────────────────────────────────────────────────

# Dispatchers that still have no Modal branch, and therefore never run in
# production. Each entry is a real, tracked gap — not an approval.
KNOWN_UNWIRED_DISPATCHERS = set()


def test_every_dispatcher_has_a_modal_branch():
    """A Celery dispatch with no Modal branch silently never runs in production.

    On Modal there is no Celery worker process at all — modal_app.py wraps each
    task in an ``@app.function`` and the submit helper must route to it. A helper
    that only calls ``apply_async`` enqueues to a broker with no consumer, so the
    caller gets a job id for work that will never happen.
    """
    unwired = {(mod, fn) for mod, fn, has_modal in _dispatch_sites() if not has_modal}

    new = unwired - KNOWN_UNWIRED_DISPATCHERS
    assert not new, (
        "New Celery dispatcher(s) with no Modal branch — these will silently never "
        f"run in production: {sorted(new)}. Add an "
        '`if os.environ.get(\"DEPLOY_TARGET\") == \"modal\": spawn(...)` branch and a '
        "matching @app.function in backend/modal_app.py."
    )

    fixed = KNOWN_UNWIRED_DISPATCHERS - unwired
    assert not fixed, (
        f"These dispatchers now have a Modal branch: {sorted(fixed)}. "
        "Remove them from KNOWN_UNWIRED_DISPATCHERS so the waiver list stays honest."
    )


def test_every_spawned_function_exists_in_modal_app():
    """``spawn("run_x_task", ...)`` must name a real @app.function.

    A typo here fails only in production, and only at dispatch time.
    """
    declared = _modal_function_names()
    spawned: set[str] = set()
    for path in sorted(BACKEND.glob("app/**/*.py")):
        for m in re.finditer(r'spawn\(\s*["\']([A-Za-z0-9_]+)["\']', path.read_text(encoding="utf-8")):
            spawned.add(m.group(1))

    assert spawned, "no spawn() call sites found — the detection regex is stale"
    missing = spawned - declared
    assert not missing, (
        f"spawn() targets with no matching @app.function in modal_app.py: {sorted(missing)}. "
        f"Declared: {sorted(declared)}"
    )


def test_modal_task_apply_never_initializes_configured_result_backend():
    """Modal's in-process Task.apply must use DisabledBackend, even with rediss configured.

    ``task_ignore_result`` alone is insufficient: Celery's eager tracer still
    accesses ``task.backend`` before invoking the task body. A production secret
    containing a rediss URL without Celery's query parameters exposed this by
    aborting every Modal wrapper during RedisBackend construction.
    """
    import subprocess
    import sys

    script = """
from app.core.celery_app import celery_app
from app.workers import email_worker

async def no_op(*args, **kwargs):
    return None

email_worker._async_send_job_failure = no_op
result = email_worker.send_job_failure_email.apply(
    kwargs={
        "user_id": "00000000-0000-0000-0000-000000000000",
        "job_type": "latex_compilation",
        "job_id": "modal-backend-regression",
    },
    throw=True,
)
assert result.successful()
assert celery_app.conf.result_backend == "disabled://"
assert type(celery_app.backend).__name__ == "DisabledBackend"
"""
    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND),
        "SKIP_ENV_VALIDATION": "true",
        "DEPLOY_TARGET": "modal",
        "CELERY_BROKER_URL": "redis://localhost:6379/0",
        # Deliberately invalid for Celery RedisBackend. The test only passes if
        # Modal never constructs that backend.
        "CELERY_RESULT_BACKEND": "rediss://example.invalid:6380/0",
    }
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


# ── 2. native dependency parity ──────────────────────────────────────────────


def _dockerfile_apt_packages() -> set[str]:
    text = DOCKERFILE.read_text(encoding="utf-8")
    pkgs = set()
    for block in re.findall(r"apt-get install[^\n]*((?:\n[^\n]*\\)*\n[^\n]*)", text):
        for line in block.splitlines():
            token = line.strip().rstrip("\\").strip()
            if token and not token.startswith("&&") and not token.startswith("-"):
                pkgs.add(token)
    return pkgs


# Packages backend/Dockerfile installs that the Modal images legitimately omit.
DOCKERFILE_ONLY_PACKAGES = {
    # Dockerfile-only build/runtime plumbing, not used by application code.
    "build-essential", "libpq-dev", "gcc", "g++", "curl", "ca-certificates",
    "gnupg", "git", "wget", "python3-dev", "pkg-config",
    # LaTeX lives in latex_image, which is asserted separately below.
    "texlive-latex-base", "texlive-latex-recommended", "texlive-latex-extra",
    "texlive-fonts-recommended", "texlive-fonts-extra", "texlive-science",
    "texlive-xetex", "texlive-luatex", "texlive-pictures", "texlive-lang-european",
    "latexmk", "lmodern", "fonts-liberation",
}


def test_ocr_native_deps_present_in_the_image_that_parses_uploads():
    """tesseract/poppler are shelled out to by the parsers, which run in the API container.

    ``backend/Dockerfile`` installs tesseract-ocr and poppler-utils; the Modal
    images do not. Uploading a screenshot of a resume, or a scanned image-only
    PDF, therefore fails in production only — the local box has both binaries on
    PATH, so it is green in dev and in the compose image.
    """
    images = _modal_apt_packages()
    api = images.get("api_image", set())
    required = {"tesseract-ocr", "poppler-utils"}
    missing = required - api
    assert not missing, (
        f"api_image is missing {sorted(missing)}, but backend/app/parsers shells out to them "
        "(image_parser.py -> pytesseract/pdf2image, pdf_parser.py -> OCR fallback) and uploads "
        "are parsed in the API container. Add them to _APT_BASE in backend/modal_app.py."
    )


def test_latex_image_has_every_engine_the_app_allows():
    """Every compiler in ALLOWED_LATEX_COMPILERS must exist in latex_image."""
    from app.core.config import settings

    images = _modal_apt_packages()
    latex = images.get("latex_image", set())
    engine_pkg = {
        "pdflatex": "texlive-latex-extra",
        "xelatex": "texlive-xetex",
        "lualatex": "texlive-luatex",
        "latexmk": "latexmk",
    }
    for engine in settings.ALLOWED_LATEX_COMPILERS:
        pkg = engine_pkg.get(engine)
        if pkg is None:
            pytest.fail(
                f"ALLOWED_LATEX_COMPILERS offers {engine!r} but this test does not know which "
                "apt package provides it — add it to engine_pkg and to latex_image."
            )
        assert pkg in latex, (
            f"{engine!r} is offered to users via ALLOWED_LATEX_COMPILERS but latex_image "
            f"does not install {pkg!r}."
        )


def test_no_new_dockerfile_runtime_package_is_missing_from_modal():
    """Catch the next tesseract-style divergence between Dockerfile and Modal."""
    images = _modal_apt_packages()
    everywhere = set().union(*images.values()) if images else set()
    missing = _dockerfile_apt_packages() - everywhere - DOCKERFILE_ONLY_PACKAGES
    assert not missing, (
        f"backend/Dockerfile installs {sorted(missing)} but no Modal image does. Either add them "
        "to backend/modal_app.py or, if they are genuinely build-only, list them in "
        "DOCKERFILE_ONLY_PACKAGES with a reason."
    )


# ── 3. the engine gate (guards outage #956) ──────────────────────────────────


@pytest.mark.parametrize(
    "topology,env,cgroup,expected",
    [
        # Modal: gVisor, texlive baked into the image, no docker CLI. This is the
        # exact combination that broke every production compile in #956.
        ("modal", {"DEPLOY_TARGET": "modal", "ENVIRONMENT": "production"}, "", True),
        ("k8s", {"ENVIRONMENT": "production", "KUBERNETES_SERVICE_HOST": "10.0.0.1"}, "", True),
        ("docker", {"ENVIRONMENT": "production"}, "0::/docker/abc123", True),
        ("bare-host-dev", {"ENVIRONMENT": "development"}, "0::/init.scope", True),
        # The one case the gate exists for: production, on a shared host, not
        # containerised, not opted in.
        ("bare-host-prod", {"ENVIRONMENT": "production"}, "0::/init.scope", False),
    ],
)
def test_local_engine_gate_across_real_topologies(monkeypatch, topology, env, cgroup, expected):
    """The in-process engine must be allowed everywhere it is the intended path.

    #956: ``running_in_container()`` looked for docker/kubepods cgroup markers,
    which gVisor does not carry, so the production gate refused every compile.
    """
    from app.services import latex_service

    for key in ("DEPLOY_TARGET", "ENVIRONMENT", "KUBERNETES_SERVICE_HOST", "ALLOW_LOCAL_LATEX_ENGINE"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(latex_service.settings, "DEPLOY_TARGET", env.get("DEPLOY_TARGET", "local"))
    monkeypatch.setattr(
        latex_service.settings, "ENVIRONMENT", env.get("ENVIRONMENT", "development"), raising=False
    )
    monkeypatch.setattr(Path, "read_text", lambda self, **kw: cgroup, raising=False)

    assert latex_service.local_engine_allowed() is expected, (
        f"topology {topology!r}: expected local_engine_allowed() == {expected}. "
        "A False here on a containerised topology means every compile fails on deploy."
    )


def test_recorder_allowlist_covers_fontconfig():
    """LuaLaTeX reads /etc/fonts via fontconfig; the allowlist must not reject it.

    The read-confinement allowlist is applied to the kpathsea recorder output. On a
    Debian image lualatex records ~50 files under /etc/fonts/, so omitting it fails
    an otherwise-successful compile with a security error blaming the user's
    document. pdflatex and xelatex do not touch it, which is why this is invisible
    until someone selects LuaLaTeX.
    """
    from app.services.latex_service import _ENGINE_TEXMF_ROOTS

    assert any(root.startswith("/etc/fonts") for root in _ENGINE_TEXMF_ROOTS), (
        "/etc/fonts is not in the recorder allowlist. fontconfig is consulted by "
        "lualatex on every Debian-based image, so LuaLaTeX compiles will be rejected."
    )


# ── 4. boot safety (guards outage #954) ──────────────────────────────────────


def test_importing_the_app_never_raises_when_optional_providers_are_unset():
    """Import-time asserts take the whole service down, not just one feature.

    #954: an email-transport assert ran at auth-module load and threw in
    production when RESEND_API_KEY was unset, crashing every auth route including
    sign-in and get-session. Optional providers must degrade, never raise at import.
    """
    import importlib
    import subprocess
    import sys

    env = {
        **os.environ,
        "ENVIRONMENT": "production",
        "DEPLOY_TARGET": "modal",
        # Everything optional, unset — the shape of a fresh deploy where someone
        # forgot a key in the Modal secret.
        "RESEND_API_KEY": "",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "RAZORPAY_KEY_ID": "",
        "RAZORPAY_KEY_SECRET": "",
        "SENTRY_DSN": "",
        "GITHUB_CLIENT_ID": "",
        "DROPBOX_APP_KEY": "",
        "SKIP_ENV_VALIDATION": "true",
    }
    importlib  # referenced for clarity; the import happens in the subprocess
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        "Importing app.main raised with optional providers unset. In production this "
        "is a total outage, not a degraded feature.\n"
        f"stderr tail:\n{result.stderr[-2500:]}"
    )


# ── 5. scheduled work (periodic tasks have no Modal runner) ──────────────────


# Beat entries with no Modal counterpart, and why that is acceptable.
SCHEDULE_WAIVERS = {
    # Pure observability sampling, every 20s. A Modal function per 20s tick would
    # cost more than the metric is worth; queue depth is meaningless there anyway,
    # since Modal does not use the Celery broker to dispatch.
    "sample-queue-depths": "Celery-broker-specific metric; no broker on Modal",
}


def test_beat_schedule_entries_are_accounted_for_on_modal():
    """Modal has no Celery beat, so every beat entry needs a Modal schedule.

    Without one, nothing periodic runs in production: temp-file cleanup, the
    expired-job reaper, the MinIO orphan pruner (which lives inside the
    expired-job task) and the weekly digest are all inert.

    Each beat entry is matched to a scheduled Modal function by the task it
    invokes, so renaming a Modal wrapper cannot silently orphan an entry.
    """
    from app.core.celery_app import celery_app

    scheduled = dict(celery_app.conf.beat_schedule or {})
    assert scheduled, "beat_schedule is empty — this guard is no longer meaningful"

    tree = _parse(MODAL_APP)

    # Task callables invoked inside a function that declares a schedule.
    scheduled_tasks: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Read the decorator AST rather than its source: get_source_segment on a
        # FunctionDef excludes the decorator lines.
        has_schedule = any(
            isinstance(dec, ast.Call)
            and any(kw.arg == "schedule" for kw in dec.keywords)
            for dec in node.decorator_list
        )
        if not has_schedule:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.ImportFrom):
                scheduled_tasks.update(a.name for a in sub.names)

    missing = {}
    for key, entry in scheduled.items():
        if key in SCHEDULE_WAIVERS:
            continue
        task_path = entry.get("task", "")
        task_fn = task_path.rsplit(".", 1)[-1]
        if task_fn not in scheduled_tasks:
            missing[key] = task_path

    assert not missing, (
        f"beat_schedule entries with no scheduled Modal function: {missing}. "
        "Nothing periodic runs on Modal without one — add an @app.function with "
        "schedule=modal.Period(...)/modal.Cron(...) that calls the same task, or "
        "waive it in SCHEDULE_WAIVERS with a reason."
    )

    stale = set(SCHEDULE_WAIVERS) - set(scheduled)
    assert not stale, (
        f"SCHEDULE_WAIVERS names beat entries that no longer exist: {sorted(stale)}."
    )


def test_scheduled_functions_initialize_worker_redis():
    """Every scheduled Modal function must call _init_worker_redis().

    The cleanup/health/digest tasks publish job events as their first action, so
    an uninitialized worker Redis makes get_worker_redis() raise and the task
    aborts before doing any work — and .apply(throw=False) swallows the error, so
    the scheduled function reports success while the reaper/pruner never runs.
    A scheduled container is always a fresh process, so it must init Redis itself
    (unlike the API container, which does it at lifespan). Requiring the call on
    every scheduled function is safe (the init is idempotent) and catches this
    silent-no-op regression that the schedule-existence guard above cannot see.
    """
    tree = _parse(MODAL_APP)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        has_schedule = any(
            isinstance(dec, ast.Call)
            and any(kw.arg == "schedule" for kw in dec.keywords)
            for dec in node.decorator_list
        )
        if not has_schedule:
            continue
        calls_init = any(
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id == "_init_worker_redis"
            for sub in ast.walk(node)
        )
        if not calls_init:
            offenders.append(node.name)

    assert not offenders, (
        f"scheduled Modal functions missing _init_worker_redis(): {offenders}. "
        "Their dispatched tasks publish events on a fresh container whose worker "
        "Redis is uninitialized → get_worker_redis() raises and the task no-ops "
        "silently. Add _init_worker_redis() as the first call."
    )


# ── 6. production settings are discoverable ──────────────────────────────────


def _localhost_or_empty_default(field) -> bool:
    """Whether this setting's default would silently misbehave in production."""
    default = field.default
    if default is None:
        return True
    if isinstance(default, str):
        if default == "":
            return True
        return bool(re.search(r"localhost|127\.0\.0\.1|::1", default))
    return False


def test_env_example_documents_settings_whose_default_breaks_in_production():
    """A setting defaulting to empty-or-localhost, undocumented, is a latent outage.

    This is the precise shape of both P0s and of the quota near-miss: ``RESEND_API_KEY``
    defaults to empty (so the boot assert fired), and ``REDIS_CACHE_URL`` defaults to
    ``redis://localhost:6379/1`` while the production validator only checks
    ``REDIS_URL``. A setting with a genuinely safe default (a timeout, a pool size, a
    feature flag) is deliberately not flagged — the point is signal, not a wall of names.
    """
    from app.core.config import Settings

    documented = set(
        re.findall(
            r"^\s*#?\s*([A-Z][A-Z0-9_]+)\s*=",
            (BACKEND / ".env.example").read_text(encoding="utf-8"),
            re.M,
        )
    )
    risky = {
        name for name, field in Settings.model_fields.items()
        if _localhost_or_empty_default(field)
    }

    # Locked-in list of currently-undocumented risky settings. Shrink it, never grow it.
    KNOWN_UNDOCUMENTED = {
        "ADMIN_EMAIL", "ADMIN_EMAILS", "ADMIN_SECRET_KEY", "FRONTEND_URL",
        "RAZORPAY_PLAN_BASIC_ANNUAL", "RAZORPAY_PLAN_BASIC_MONTHLY",
        "RAZORPAY_PLAN_BYOK_ANNUAL", "RAZORPAY_PLAN_BYOK_MONTHLY",
        "RAZORPAY_PLAN_PRO_ANNUAL", "RAZORPAY_PLAN_PRO_MONTHLY",
        "RAZORPAY_PLAN_STUDENT", "RAZORPAY_PLAN_TEAM", "RAZORPAY_COUPON_OFFERS",
        "UPSTASH_REDIS_REST_TOKEN", "UPSTASH_REDIS_REST_URL",
        "DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REDIRECT_URI",
        "MENDELEY_CLIENT_ID", "MENDELEY_CLIENT_SECRET", "MENDELEY_REDIRECT_URI",
        "ZOTERO_CLIENT_KEY", "ZOTERO_CLIENT_SECRET", "ZOTERO_REDIRECT_URI",
        "GITHUB_OAUTH_REDIRECT_URI", "GEOIP_PROVIDER_URL",
        "LANGUAGETOOL_URL", "LANGUAGETOOL_LOCAL_URL",
        "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_RESOURCE_ATTRIBUTES",
        "REDIS_CACHE_URL", "STUDENT_EMAIL_ALLOWED_SUFFIXES",
    }
    new_gaps = sorted(risky - documented - KNOWN_UNDOCUMENTED)
    assert not new_gaps, (
        f"Settings that default to empty-or-localhost but are absent from "
        f"backend/.env.example: {new_gaps}. Production has no other source of truth for "
        "what the Modal secret must contain, and these defaults fail silently there."
    )
