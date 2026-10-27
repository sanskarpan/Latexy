"""
Latexy backend — Modal deployment definition.

Production deployment and migration are supported only through
.github/workflows/deploy-modal.yml. Do not use direct `modal deploy` or
`modal run ...::migrate` commands against production. Local Modal development
must set MODAL_ENVIRONMENT=dev and MODAL_DEPLOYMENT_TRAFFIC_HOLD=false before
using `modal serve modal_app.py::app`.

Environment variables are loaded from the Modal secrets "latexy-backend-secrets"
(app config) and "latexy-storage" (object storage).
DEPLOY_TARGET=modal is baked into the image so worker dispatch routes here.
"""

import base64
import hashlib
import os
import re
from functools import wraps
from pathlib import Path

import modal

from app.core.deployment_hold import deployment_traffic_held, modal_redis_secret_name
from app.core.engine_capacity import capacity_options

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_APP_NAME = "latexy-backend"
# Modal's module file is imported from /root/modal_app.py remotely, while the
# source tree is baked at /backend. During local build/deploy, use this file's
# checkout path so image copy operations read the actual backend directory.
_BACKEND_DIR = Path(__file__).parent if modal.is_local() else Path("/backend")


def _validated_optional_billing_secret_name(value: str | None) -> str | None:
    """Return a Modal secret label when configured, rejecting unsafe labels."""
    if value is None or value == "":
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("MODAL_BILLING_SECRET_NAME must be a valid Modal secret label")
    return value


# Snapshot the non-secret binding label into every image. Modal imports this
# module remotely to resolve function definitions, and that process does not
# inherit the local deploy command's environment.
_billing_secret_name = _validated_optional_billing_secret_name(
    os.environ.get("MODAL_BILLING_SECRET_NAME")
)
_billing_secret_binding_env = {
    "MODAL_BILLING_SECRET_NAME": _billing_secret_name or "",
}
_redis_secret_name = modal_redis_secret_name(os.environ.get("MODAL_REDIS_SECRET_NAME"))
_redis_secret_binding_env = {"MODAL_REDIS_SECRET_NAME": _redis_secret_name}

app = modal.App(_APP_NAME)
# Operator-only tasks run under a separate Modal App so ephemeral preflight and
# migration invocations cannot warm fastapi_app's min_containers=1 API service.
operations_app = modal.App(f"{_APP_NAME}-operations")

# Resolve the one canonical hold value while the deployment source is imported.
# The same value is baked into every image so child processes and remote imports
# observe the selected workflow mode, even when their local environment differs.
_DEPLOYMENT_TRAFFIC_HELD = deployment_traffic_held(os.environ, source_deployment=True)
_DEPLOYMENT_TRAFFIC_HOLD_VALUE = "true" if _DEPLOYMENT_TRAFFIC_HELD else "false"


def _require_worker_dispatch(fn):
    """Reject worker and scheduler inputs before they can perform side effects."""
    @wraps(fn)
    def guarded(*args, **kwargs):
        if _DEPLOYMENT_TRAFFIC_HELD:
            raise RuntimeError("Modal deployment traffic is held; worker execution is paused")
        from app.core.redis_authority import require_primary_authority_active_sync

        require_primary_authority_active_sync()
        return fn(*args, **kwargs)

    return guarded

# Directories to exclude from the code snapshot (security + size)
_IGNORE = [
    "**/.env*",
    "**/__pycache__/**",
    "**/*.pyc",
    "**/alembic/**",
    "**/test/**",
    "**/.git/**",
    "**/temp/**",
    "**/.venv/**",
    "**/.pytest_cache/**",
]

# ---------------------------------------------------------------------------
# Base apt packages (shared across all images)
# ---------------------------------------------------------------------------
# tesseract/poppler are not optional extras: app/parsers/image_parser.py shells out
# to the `tesseract` binary via pytesseract and to poppler's pdftoppm via pdf2image,
# and pdf_parser.py falls back to the same path for scanned, image-only PDFs. Uploads
# are parsed in the API container, so these belong in the base set rather than only in
# latex_image. backend/Dockerfile has installed them all along — omitting them here
# meant image uploads and scanned PDFs failed in production only.
_APT_BASE = [
    "gcc",
    "g++",
    "libpq-dev",
    "curl",
    "tesseract-ocr",
    "tesseract-ocr-eng",
    "poppler-utils",
]

# The full TeX toolchain. Every engine named in ALLOWED_LATEX_COMPILERS needs its
# package here, and poppler-utils (pdftotext, for page-count extraction) comes
# from _APT_BASE.
#
# texlive-fonts-extra trimmed to just its cm-super dependency (#1281 —
# "Compile latency: 37s median -> target <10s"): the full package is 1,665 of
# the 1,750MB this apt_install pulls in (per Debian package sizes). An audit of
# every currently-active production template's LaTeX source
# (backend/app/data/templates/**/*.tex) plus official_snippets.py found only
# array, enumitem, fontenc, geometry, hyperref, inputenc, microtype, parskip,
# titlesec, xcolor, amsmath, amssymb, graphicx, booktabs, tikz, pgfplots,
# tcolorbox, appendixnumberbeamer, ccicons, xspace in use — all standard
# packages shipped by texlive-latex-base/texlive-latex-recommended (a
# transitive dependency of texlive-latex-extra) or texlive-latex-extra itself.
#
# BUT: texlive-fonts-extra Recommends (and apt installs by default) the
# `cm-super` font package, which nothing else here depends on — and it is
# load-bearing. Every default-Computer-Modern template compiles via
# microtype's font-expansion feature, which needs cm-super's Type1 fonts
# (verified locally: dropping texlive-fonts-extra outright reproduces
# `! pdfTeX error (font expansion): auto expansion is only possible with
# scalable fonts` and a fatal, no-PDF compile on the production "Clean Simple"
# template — this is NOT a hypothetical). Installing `cm-super` directly
# instead keeps that dependency (52.6MB installed) while dropping the other
# ~1,362MB of texlive-fonts-extra that's genuinely unused (decorative font
# families like libertine/ebgaramond).
_APT_LATEX = [
    "texlive-latex-extra",
    "texlive-fonts-recommended",
    "cm-super",  # microtype font-expansion dependency; see comment above
    "texlive-science",
    "texlive-xetex",
    "texlive-luatex",
    # B54a/B54c: explicit script collections are required under
    # --no-install-recommends. texlive-lang-cjk is their common dependency,
    # but does not contain ctex or luatexja-fontspec itself.
    "texlive-lang-chinese",  # ctex.sty + Chinese JFM
    "texlive-lang-japanese",  # luatexja-fontspec + Japanese JFM
    "texlive-lang-korean",  # Korean TeX support; luatexko is in texlive-luatex
    "texlive-lang-arabic",
    "texlive-lang-european",
    "texlive-lang-greek",
    "fonts-noto-cjk",
    "fonts-noto-core",
    "fonts-texgyre",  # EuropeCV's fontspec TeX Gyre Heros must be visible to fontconfig
    "texlive-lang-english",  # hyphenation patterns; matches backend/Dockerfile
    # Small, freely licensed Devanagari font. LuaHBTeX + explicit HarfBuzz
    # shaping is required for correct Hindi/Marathi glyph order and extraction.
    "fonts-lohit-deva",
    "latexmk",
]

# The design panel offers Atkinson Hyperlegible as its readability-focused
# document font. Debian only ships it inside the 1.3GB+ texlive-fonts-extra
# bundle that this image deliberately avoids, so install the official 4.1MB
# CTAN TDS archive directly and pin its digest. The package supports pdfLaTeX,
# XeLaTeX, and LuaLaTeX. See https://ctan.org/pkg/atkinson.
_ATKINSON_TDS_SHA256 = "7c13720556a2ac2d0ea57015c7a6cf8c5bb9fcd72de7347a8d9ba58dbcb8492d"
_INSTALL_ATKINSON = (
    "curl -fsSL https://tug.ctan.org/install/fonts/atkinson.tds.zip "
    "-o /tmp/atkinson.tds.zip && "
    f"echo '{_ATKINSON_TDS_SHA256}  /tmp/atkinson.tds.zip' | sha256sum -c - && "
    "unzip -q /tmp/atkinson.tds.zip -d /usr/local/share/texmf && "
    "mktexlsr && updmap-sys --enable Map=atkinson.map && "
    "rm -f /tmp/atkinson.tds.zip"
)

# Keep Modal's Debian TeX image cache contract aligned with the local sandbox.
# The command is self-contained: it copies no application source and derives
# TEXMFVAR/TEXMFCACHE from the image's own kpathsea defaults, which differ from
# the local TeX Live image but remain stable between build and runtime.
_WARM_TEX_CACHE = r"""
set -eu
export TEXMFVAR="$(kpsewhich -var-value=TEXMFVAR)"
export TEXMFCACHE="$(kpsewhich -var-value=TEXMFCACHE)"
engine_fonts="$(kpsewhich -var-value=TEXMFDIST)/fonts"
for font_root in "$engine_fonts" /usr/share/fonts /usr/local/share/fonts; do
  if [ -d "$font_root" ]; then
    find "$font_root" -type d -exec touch -m -d '@1704067200' {} +
  fi
done
fc-cache --force --system-only
luaotfload-tool --update --force
probe="$(mktemp -d)"
trap 'rm -rf "$probe"' EXIT
printf '%s\n' \
  '\documentclass{article}' \
  '\usepackage{geometry}' \
  '\usepackage{fontspec}' \
  '\usepackage{luatexja-fontspec}' \
  '\setmainjfont{Noto Sans CJK JP}' \
  '\usepackage{polyglossia}' \
  '\setmainfont{Latin Modern Roman}' \
  '\setmainlanguage{english}' \
  '\setotherlanguage{arabic}' \
  '\setotherlanguage{hebrew}' \
  '\setotherlanguage{hindi}' \
  '\newfontfamily\arabicfont[Script=Arabic]{Noto Naskh Arabic}' \
  '\newfontfamily\hebrewfont[Script=Hebrew]{Noto Sans Hebrew}' \
  '\newfontfamily\hindifont[Renderer=HarfBuzz,Script=Devanagari,BoldFont={Noto Sans Devanagari Bold},ItalicFont={Noto Sans Devanagari},ItalicFeatures={FakeSlant=0.15},BoldItalicFont={Noto Sans Devanagari Bold},BoldItalicFeatures={FakeSlant=0.15}]{Noto Sans Devanagari}' \
  '\begin{document}' \
  '\textenglish{Latin email@example.com •}' \
  '日本語' \
  '\textarabic{العربية}' \
  '\texthebrew{עברית}' \
  '\texthindi{हिंदी \textenglish{email@example.com •} \textbf{बोल्ड} \textit{तिरछा} \textbf{\textit{दोनों}}}' \
  '\begin{itemize}' \
  '\item \texthindi{भुगतान मंच \textenglish{email@example.com •}}' \
  '\begin{itemize}\item \texthindi{दूसरा स्तर}\end{itemize}' \
  '\end{itemize}' \
  '\end{document}' > "$probe/font-probe.tex"
lualatex -no-shell-escape -recorder -interaction=batchmode -halt-on-error \
  -output-directory="$probe" "$probe/font-probe.tex" >"$probe/font-probe.stdout" 2>&1 &
engine_pid="$!"
(
  sleep 125
  kill "$engine_pid" 2>/dev/null || true
) &
watchdog_pid="$!"
set +e
wait "$engine_pid"
engine_rc="$?"
set -e
kill "$watchdog_pid" 2>/dev/null || true
wait "$watchdog_pid" 2>/dev/null || true
test "$engine_rc" -eq 0
test -s "$probe/font-probe.pdf"
! grep -Eq 'Missing character|Font shape .*undefined|Some font shapes were not available|Fatal error|^! ' "$probe/font-probe.log"
"""


def _encode_shell_script(script: str) -> str:
    """Transport a multiline script as one safe Dockerfile ``RUN`` command.

    Modal emits each ``run_commands`` argument after a literal ``RUN``. A raw
    multiline string therefore turns each subsequent line into a Dockerfile
    instruction. Base64 keeps the generated command on one line while
    preserving the script byte-for-byte, including shell metacharacters and
    control characters; only the encoded payload is interpolated.
    """
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return f"printf '%s' '{encoded}' | base64 -d | sh"


_WARM_TEX_CACHE_COMMAND = _encode_shell_script(_WARM_TEX_CACHE)
_fingerprint_source = (_BACKEND_DIR / "scripts" / "write_renderer_fingerprint.py").read_text(encoding="utf-8")
_fingerprint_encoded = base64.b64encode(_fingerprint_source.encode("utf-8")).decode("ascii")
_cache_seed_digest = hashlib.sha256(_WARM_TEX_CACHE.encode("utf-8")).hexdigest()
_WRITE_RENDERER_FINGERPRINT_COMMAND = (
    f"LATEXY_CACHE_SEED_SHA256={_cache_seed_digest} "
    f"python3 -c \"import base64; exec(base64.b64decode('{_fingerprint_encoded}'))\""
)

# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
# API image — FastAPI + all Python deps + the LaTeX toolchain.
#
# The toolchain is NOT optional here: POST /compile, POST /public/compile and
# POST /optimize-and-compile exec the engine in-process, inside this container.
# Hotfix #956 made local_engine_allowed() return True on Modal, so the gate now
# passes and the exec reaches the binary — which, without these packages, does
# not exist. That fails as success:false inside a 200, AFTER the quota charge, so
# the refund path never runs and the user is billed for nothing.
#
# It shares _APT_LATEX with latex_image rather than repeating the list, so the
# two cannot drift apart again. This does inflate the API image, but it has
# min_containers=1 and stays warm, so the cold-start cost is paid once.
texlive_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install(*_APT_BASE, *_APT_LATEX, "unzip")
    .run_commands(_INSTALL_ATKINSON, _WARM_TEX_CACHE_COMMAND)
    .add_local_file(str(_BACKEND_DIR / "scripts/build_trusted_render_formats.py"),
                    remote_path="/opt/latexy-format-build/scripts/build_trusted_render_formats.py", copy=True)
    .add_local_file(str(_BACKEND_DIR / "app/services/render_engine/managed_preamble.py"),
                    remote_path="/opt/latexy-format-build/app/services/render_engine/managed_preamble.py", copy=True)
    .run_commands("python3 /opt/latexy-format-build/scripts/build_trusted_render_formats.py", _WRITE_RENDERER_FINGERPRINT_COMMAND)
)

# A certified VM renderer is an immutable *bare* image pinned by the operator.
# The new image graph above is not substituted at request time: certification
# of a previous image never attests newly built fonts/formats/assets.
_renderer_capability_env = {
    key: os.environ[key]
    for key in ("MODAL_ENGINE_VM_CERTIFIED", "MODAL_ENGINE_VM_IMAGE_ID", "MODAL_ENGINE_VM_ASSETS_FINGERPRINT")
    if key in os.environ
}

# Serving-revision provenance. The deployment workflow verifies the exact commit
# and exports DEPLOY_SHA; baking it here lets /health attest which revision the
# container answering a request is running. Modal's deployment pointer alone
# cannot distinguish a fully drained fleet from an old one, and a frontend and
# backend serving different commits previously looked identically healthy.
# This value is non-secret and is validated again before it is published.
_serve_identity_env = (
    {"DEPLOY_SHA": os.environ["DEPLOY_SHA"]} if os.environ.get("DEPLOY_SHA") else {}
)

api_image = (
    texlive_image.pip_install_from_requirements("requirements.lock", extra_options="--require-hashes")
    .add_local_dir(str(_BACKEND_DIR), remote_path="/backend", copy=True, ignore=_IGNORE)
    .env({"PYTHONPATH": "/backend", "DEPLOY_TARGET": "modal", **_renderer_capability_env,
          **_serve_identity_env,
          **_billing_secret_binding_env,
          **_redis_secret_binding_env,
          "MODAL_DEPLOYMENT_TRAFFIC_HOLD": _DEPLOYMENT_TRAFFIC_HOLD_VALUE})
)

# LaTeX worker image — same Python deps + full texlive for compilation
latex_image = (
    texlive_image.pip_install_from_requirements("requirements.lock", extra_options="--require-hashes")
    .add_local_dir(str(_BACKEND_DIR), remote_path="/backend", copy=True, ignore=_IGNORE)
    .env({"PYTHONPATH": "/backend", "DEPLOY_TARGET": "modal", **_renderer_capability_env,
          **_serve_identity_env,
          **_billing_secret_binding_env,
          **_redis_secret_binding_env,
          "MODAL_DEPLOYMENT_TRAFFIC_HOLD": _DEPLOYMENT_TRAFFIC_HOLD_VALUE})
)

# Worker image — Python deps only (LLM, ATS, email, cleanup tasks)
worker_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install(*_APT_BASE)
    .pip_install_from_requirements("requirements.lock", extra_options="--require-hashes")
    .add_local_dir(str(_BACKEND_DIR), remote_path="/backend", copy=True, ignore=_IGNORE)
    .env({"PYTHONPATH": "/backend", "DEPLOY_TARGET": "modal", **_billing_secret_binding_env,
          **_redis_secret_binding_env,
          **_serve_identity_env,
          "MODAL_DEPLOYMENT_TRAFFIC_HOLD": _DEPLOYMENT_TRAFFIC_HOLD_VALUE})
)

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------
# Object storage lives in its own secret rather than being added to
# latexy-backend-secrets. `modal secret create --force` REPLACES a secret wholesale
# and its values cannot be read back, so amending the existing one risks silently
# dropping DATABASE_URL and every other key it holds. Modal merges the env from
# each secret in this list, so a second one is both safer and easier to rotate.
#
# Without it, MINIO_ENDPOINT fell back to http://localhost:9000 — which does not
# exist inside a Modal container — and every template thumbnail and preview PDF
# answered 502 Storage unavailable (#1143).
_base_secrets = [
    modal.Secret.from_name("latexy-backend-secrets"),
    modal.Secret.from_name("latexy-storage"),
]

# Dodo credentials are needed by the public API and its read-only billing
# preflight. Keep them out of unrelated render, worker, scheduler, and migration
# containers; renderer_preflight uses this same full API configuration by design.
_api_secrets = [*_base_secrets]
if _billing_secret_name:
    # Append after named base secrets so Dodo variables override legacy values
    # while preserving every unrelated key in the opaque backend secret. This
    # list is only attached to API and billing-configuration preflight functions.
    _api_secrets.append(modal.Secret.from_name(_billing_secret_name))

# Keep selected Redis last among named secrets so endpoints/passwords override
# legacy values in the opaque base secret and any accidental billing overlap.
_redis_secret = modal.Secret.from_name(_redis_secret_name)
_secrets = [*_base_secrets, _redis_secret]
_api_secrets.append(_redis_secret)

# Named Secrets can shadow image environment variables. Bind the deployment
# choice after every opaque secret and before registering any function so API,
# worker, scheduler, and operator functions receive the same hold mode.
_deployment_hold_secret = modal.Secret.from_dict(
    {
        "MODAL_DEPLOYMENT_TRAFFIC_HOLD": _DEPLOYMENT_TRAFFIC_HOLD_VALUE,
        "MODAL_REDIS_SECRET_NAME": _redis_secret_name,
    }
)
_secrets.append(_deployment_hold_secret)
_api_secrets.append(_deployment_hold_secret)

# This operations-only secret contains the HMAC verifier key shared with the
# protected GitHub Production workflow. It is intentionally excluded from API,
# worker, scheduler, and routine template-sync functions.
_operation_authorization_secret = modal.Secret.from_name("latexy-recovery-ops-20261027")
_operations_secrets = [*_base_secrets, _redis_secret, _operation_authorization_secret, _deployment_hold_secret]


# ---------------------------------------------------------------------------
# Helper — initialise sync Redis for event publishing inside a worker fn
# ---------------------------------------------------------------------------
def _init_worker_redis() -> None:
    from app.core.config import settings
    from app.core.worker_runtime import prepare_worker_logging, prepare_worker_runtime
    from app.workers.event_publisher import initialize_worker_redis

    prepare_worker_logging()
    # Run before .apply installs the task lifecycle/budget. Imports are memoized;
    # scoped clients and durable owner/epoch checks remain per invocation.
    prepare_worker_runtime(settings.RESUME_SEMANTIC_ENGINE_ENABLED is True)
    initialize_worker_redis(settings.REDIS_URL, password=settings.REDIS_PASSWORD or None)


# ---------------------------------------------------------------------------
# Worker functions
# ---------------------------------------------------------------------------


@app.function(
    image=latex_image,
    secrets=_secrets,
    timeout=300,
    # Keep one worker warm at all times. The texlive image cold-starts in ~40-45s,
    # which dominated compile latency (warm compile work is only ~3.5s). min_containers=1
    # eliminates the cold start for the common single-compile path. scaledown_window keeps
    # extra burst containers around briefly so bursts stay warm too.
    **capacity_options("LATEX"),
)
@_require_worker_dispatch
def run_latex_task(payload: dict) -> None:
    """Compile LaTeX to PDF (texlive installed in image; no Docker needed)."""
    # throw=False: prevents Celery's self.retry() Retry exception from propagating
    # to Modal (which would cause a double-execution via Modal's retry mechanism).
    # The Celery task publishes its own error events; Modal must not independently retry.
    from app.core.tracing import worker_trace
    task_payload = dict(payload)
    with worker_trace(task_payload.pop("_trace_context", None)):
        _init_worker_redis()
        from app.workers.latex_worker import compile_latex_task
        compile_latex_task.apply(kwargs=task_payload, throw=False)


@app.function(
    # latex_image (not worker_image): the orchestrator compiles LaTeX in-process
    # during its pipeline, so it needs the full texlive toolchain — otherwise the
    # compile stage fails (no pdflatex) and the combined job retries/stalls.
    image=latex_image,
    secrets=_secrets,
    timeout=600,
    # Keep one orchestrator warm: the texlive image cold-starts in ~2min, which
    # made the flagship "Optimize + Compile" flow take ~230s. Warm it so combined
    # jobs are ~40-50s (LLM-bound) instead. scaledown_window keeps burst
    # containers around for back-to-back runs.
    **capacity_options("ORCHESTRATOR"),
)
@_require_worker_dispatch
def run_orchestrator_task(payload: dict) -> None:
    """Combined LLM optimisation → LaTeX compilation → ATS scoring pipeline."""
    from app.core.tracing import worker_trace
    task_payload = dict(payload)
    with worker_trace(task_payload.pop("_trace_context", None)):
        _init_worker_redis()
        from app.workers.orchestrator import optimize_and_compile_task
        optimize_and_compile_task.apply(kwargs=task_payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=300,
    **capacity_options("LLM"),
)
@_require_worker_dispatch
def run_llm_task(payload: dict) -> None:
    """LLM resume optimisation (streaming tokens published via Redis)."""
    from app.core.tracing import worker_trace
    task_payload = dict(payload)
    with worker_trace(task_payload.pop("_trace_context", None)):
        _init_worker_redis()
        from app.workers.llm_worker import optimize_resume_task
        optimize_resume_task.apply(kwargs=task_payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=120,
    scaledown_window=60,
)
@_require_worker_dispatch
def run_ats_task(payload: dict) -> None:
    """ATS resume scoring."""
    _init_worker_redis()
    from app.workers.ats_worker import score_resume_ats_task

    score_resume_ats_task.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=60,
    scaledown_window=60,
)
@_require_worker_dispatch
def run_jd_analysis_task(payload: dict) -> None:
    """Job-description keyword analysis."""
    _init_worker_redis()
    from app.workers.ats_worker import analyze_job_description_ats_task

    analyze_job_description_ats_task.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=120,
    scaledown_window=300,
)
@_require_worker_dispatch
def run_deep_analyze_task(payload: dict) -> None:
    """Deep LLM-powered ATS analysis."""
    _init_worker_redis()
    from app.workers.ats_worker import deep_analyze_ats_task

    deep_analyze_ats_task.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=60,
    scaledown_window=600,
)
@_require_worker_dispatch
def run_embed_resume_task(payload: dict) -> None:
    """Compute and store resume embedding (low-priority background task)."""
    from app.workers.ats_worker import embed_resume_task

    embed_resume_task.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=120,
    scaledown_window=600,
)
@_require_worker_dispatch
def run_cleanup_task(payload: dict) -> None:
    """Temp-file and expired-job cleanup (fire-and-forget maintenance tasks)."""
    task_type = payload.pop("task_type", "temp_files")
    if task_type == "expired_jobs":
        from app.workers.cleanup_worker import cleanup_expired_jobs_task

        cleanup_expired_jobs_task.apply(kwargs=payload, throw=False)
    else:
        from app.workers.cleanup_worker import cleanup_temp_files_task

        cleanup_temp_files_task.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=300,
    scaledown_window=60,
)
@_require_worker_dispatch
def run_cover_letter_task(payload: dict) -> None:
    """LLM cover-letter generation."""
    _init_worker_redis()
    from app.workers.cover_letter_worker import generate_cover_letter_task

    resume_latex = payload.pop("resume_latex")
    job_description = payload.pop("job_description")
    generate_cover_letter_task.apply(args=[resume_latex, job_description], kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=300,
    scaledown_window=60,
)
@_require_worker_dispatch
def run_interview_prep_task(payload: dict) -> None:
    """LLM interview-prep generation."""
    _init_worker_redis()
    from app.workers.interview_prep_worker import generate_interview_prep_task

    resume_latex = payload.pop("resume_latex")
    prep_id = payload.pop("prep_id")
    generate_interview_prep_task.apply(args=[resume_latex, prep_id], kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=300,
    scaledown_window=60,
)
@_require_worker_dispatch
def run_github_import_task(payload: dict) -> None:
    """Import + summarize a user's top public GitHub projects."""
    _init_worker_redis()
    from app.workers.github_import_worker import import_github_projects_task

    import_github_projects_task.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=300,
    scaledown_window=60,
)
@_require_worker_dispatch
def run_document_conversion_task(payload: dict) -> None:
    """LLM document conversion (imported resume -> LaTeX)."""
    _init_worker_redis()
    from app.workers.converter_worker import convert_document_task

    convert_document_task.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=120,
    scaledown_window=300,
)
@_require_worker_dispatch
def run_auto_save_task(payload: dict) -> None:
    """Auto-save checkpoint recorded after a successful compile."""
    from app.workers.auto_save_worker import record_auto_save_checkpoint

    record_auto_save_checkpoint.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=120,
    scaledown_window=300,
)
@_require_worker_dispatch
def run_email_task(payload: dict) -> None:
    """Transactional job-completion email."""
    from app.workers.email_worker import send_job_completion_email

    send_job_completion_email.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=180,
    scaledown_window=60,
)
@_require_worker_dispatch
def run_comment_mention_task(payload: dict) -> None:
    """Transactional collaborator mention email."""
    from app.workers.email_worker import send_comment_mention_email

    send_comment_mention_email.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=180,
    scaledown_window=60,
)
@_require_worker_dispatch
def run_document_email_delivery_task(payload: dict) -> None:
    """Deliver one durable compiled-document email in Modal production."""
    from app.workers.email_worker import send_document_email_delivery

    send_document_email_delivery.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=180,
    scaledown_window=60,
)
@_require_worker_dispatch
def run_job_failure_email_task(payload: dict) -> None:
    """Transactional terminal job-failure email."""
    from app.workers.email_worker import send_job_failure_email

    send_job_failure_email.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=180,
    scaledown_window=60,
)
@_require_worker_dispatch
def run_share_viewed_email_task(payload: dict) -> None:
    """Transactional notification for a debounced public resume view."""
    from app.workers.email_worker import send_share_viewed_email

    send_share_viewed_email.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=180,
    scaledown_window=60,
)
@_require_worker_dispatch
def run_weekly_digest_task(payload: dict) -> None:
    """Send one user's weekly digest from the Modal scheduler fan-out."""
    from app.workers.email_worker import send_weekly_digest

    send_weekly_digest.apply(kwargs=payload, throw=False)


# ---------------------------------------------------------------------------
# Scheduled functions
# ---------------------------------------------------------------------------
# celery_app.py defines a beat_schedule, but Celery beat is only ever launched by
# scripts/dev.sh and the docker/k8s manifests — none of which run in production.
# Without these, the MinIO orphan pruner never runs (so the storage-growth fix it
# was written to deliver is inert), expired-job Redis state is never reaped, and
# /tmp grows unbounded in the warm min_containers=1 latex container, which now
# lives for hours rather than per-job. Periods mirror the beat entries.


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=600,
    schedule=None if _DEPLOYMENT_TRAFFIC_HELD else modal.Period(hours=1),
)
@_require_worker_dispatch
def scheduled_cleanup_expired_jobs() -> None:
    """Reap expired job state from Redis (beat: every 3600s).

    Also runs the MinIO orphan pruner added by #951 — it lives inside this task
    (cleanup_worker.py:419), not as a task of its own, so scheduling this is what
    makes the storage-growth fix actually take effect in production.
    """
    # cleanup_expired_jobs_task publishes progress events as its first action, so
    # the worker Redis MUST be initialized or get_worker_redis() raises and the
    # task aborts before the reaper/pruner runs — which .apply(throw=False) would
    # then silently swallow, leaving the storage fix inert.
    _init_worker_redis()
    from app.workers.cleanup_worker import cleanup_expired_jobs_task

    cleanup_expired_jobs_task.apply(throw=False)


@app.function(
    image=latex_image,
    secrets=_secrets,
    timeout=600,
    schedule=None if _DEPLOYMENT_TRAFFIC_HELD else modal.Period(minutes=30),
)
@_require_worker_dispatch
def scheduled_cleanup_temp_files() -> None:
    """Clear stale workspaces from /tmp (beat: every 1800s).

    Runs on latex_image because the workspaces it removes are created by the
    compile container.

    NOTE: on Modal each container has an isolated ephemeral filesystem, so this
    scheduled container only sees its OWN /tmp, not the warm run_latex_task
    container's. It is a safety net (reaps /tmp if a compile container is reused
    long enough to accumulate). The primary /tmp hygiene is the per-job
    shutil.rmtree in the compile workers' finally blocks.
    """
    # Publishes events on some paths → worker Redis must be initialized first.
    _init_worker_redis()
    from app.workers.cleanup_worker import cleanup_temp_files_task

    cleanup_temp_files_task.apply(throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=300,
)
# This intentionally uses a new Modal name. The v49 registration used the old
# name as a scheduled function; replacing it in place can leave server-side
# schedule metadata associated with that name during rollout. The retention
# behavior is deployment-dependent, so never restore the old function name.
@_require_worker_dispatch
def run_scheduled_health_check() -> None:
    """Worker health check runner (beat: every 300s).

    The cadence is owned by ``scheduled_five_minute_maintenance`` so this
    runner remains independently callable and receives its own timeout.
    """
    _init_worker_redis()
    from app.workers.cleanup_worker import health_check_task

    health_check_task.apply(throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=300,
    schedule=None if _DEPLOYMENT_TRAFFIC_HELD else modal.Cron("0 9 * * 1"),
)
@_require_worker_dispatch
def scheduled_weekly_digest() -> None:
    """Monday 09:00 weekly digest fan-out (inert while EMAIL_ENABLED is false)."""
    _init_worker_redis()
    from app.workers.email_worker import send_weekly_digest_to_all

    send_weekly_digest_to_all.apply(throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=300,
)
@_require_worker_dispatch
def scheduled_tracker_notifications() -> None:
    """Deliver due application reminders and saved-search review nudges.

    The cadence is owned by ``scheduled_five_minute_maintenance`` so this
    runner remains independently callable and receives its own timeout.
    """
    _init_worker_redis()
    from app.workers.tracker_notification_worker import send_tracker_notifications

    send_tracker_notifications.apply(throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=300,
)
@_require_worker_dispatch
def scheduled_comment_mention_recovery() -> None:
    """Recover mention rows whose post-commit enqueue missed the queue.

    The cadence is owned by ``scheduled_minute_recovery`` so this runner
    remains independently callable and receives its own timeout.
    """
    _init_worker_redis()
    from app.workers.email_worker import send_pending_comment_mention_emails

    send_pending_comment_mention_emails.apply(throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=300,
)
@_require_worker_dispatch
def scheduled_document_email_recovery() -> None:
    """Recover compiled-document email rows missed by a broker/process crash.

    The cadence is owned by ``scheduled_minute_recovery`` so this runner
    remains independently callable and receives its own timeout.
    """
    _init_worker_redis()
    from app.workers.email_worker import send_pending_document_email_deliveries

    send_pending_document_email_deliveries.apply(throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=120,
    schedule=None if _DEPLOYMENT_TRAFFIC_HELD else modal.Period(minutes=5),
)
@_require_worker_dispatch
def scheduled_five_minute_maintenance() -> None:
    """Fan out the two five-minute maintenance runners independently."""
    _init_worker_redis()
    spawn_failures = []

    try:
        run_scheduled_health_check.spawn()
    except Exception as exc:
        print(f"scheduled health-check spawn failed: {type(exc).__name__}")
        spawn_failures.append("run_scheduled_health_check")

    try:
        scheduled_tracker_notifications.spawn()
    except Exception as exc:
        print(f"scheduled tracker-notification spawn failed: {type(exc).__name__}")
        spawn_failures.append("scheduled_tracker_notifications")

    if spawn_failures:
        raise RuntimeError(
            "scheduled five-minute maintenance fan-out failed: "
            + ",".join(spawn_failures)
        )


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=120,
    schedule=None if _DEPLOYMENT_TRAFFIC_HELD else modal.Period(minutes=1),
)
@_require_worker_dispatch
def scheduled_minute_recovery() -> None:
    """Fan out the two one-minute recovery runners independently."""
    _init_worker_redis()
    spawn_failures = []

    try:
        scheduled_comment_mention_recovery.spawn()
    except Exception as exc:
        print(f"scheduled comment-mention recovery spawn failed: {type(exc).__name__}")
        spawn_failures.append("scheduled_comment_mention_recovery")

    try:
        scheduled_document_email_recovery.spawn()
    except Exception as exc:
        print(f"scheduled document-email recovery spawn failed: {type(exc).__name__}")
        spawn_failures.append("scheduled_document_email_recovery")

    if spawn_failures:
        raise RuntimeError(
            "scheduled one-minute recovery fan-out failed: "
            + ",".join(spawn_failures)
        )


# ---------------------------------------------------------------------------
# Deployment preflight and migrations
# ---------------------------------------------------------------------------
@operations_app.function(image=api_image, secrets=_api_secrets, timeout=60)
def renderer_preflight() -> dict:
    """Validate actual API configuration only; never certify or start a VM."""
    import contextlib
    import json
    import logging
    import os
    import sys

    previous_logging_disable = logging.root.manager.disable
    check_failed = False
    try:
        # This isolated function has no concurrent inputs. Suppress startup
        # diagnostics while importing settings: existing handlers may retain
        # the original stderr, so redirecting the streams alone is insufficient.
        logging.disable(sys.maxsize)
        with open(os.devnull, "w") as discarded_output, contextlib.redirect_stdout(discarded_output), contextlib.redirect_stderr(discarded_output):
            from app.services.render_engine.deployment_preflight import renderer_configuration_report

            report = renderer_configuration_report()
    except Exception:
        # Configuration validation failures can contain secret input values.
        # Keep the public diagnostic fixed, including import-time failures.
        check_failed = True
        report = {"configuration_ready": False, "certification_verified": False,
                  "reasons": ["configuration_check_failed"]}
    finally:
        logging.disable(previous_logging_disable)
    print(json.dumps(report, sort_keys=True))
    if check_failed:
        raise RuntimeError("Renderer configuration preflight failed") from None
    if not report["configuration_ready"]:
        raise RuntimeError("Renderer configuration preflight blocked deployment")
    return report


# Locally, migrations run on backend startup. Production migrations are invoked
# only by deploy-modal.yml after an external drain/recovery procedure and a
# read-only current App identity/state check. The workflow does not stop the App
# or verify queued/in-flight work. Keep migration separate from API startup so
# no container can migrate as an incidental side effect.
migrate_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install(*_APT_BASE)
    .pip_install_from_requirements("requirements.lock", extra_options="--require-hashes")
    .add_local_dir(
        str(_BACKEND_DIR),
        remote_path="/backend",
        copy=True,
        ignore=[p for p in _IGNORE if "alembic" not in p],
    )
    .env({"PYTHONPATH": "/backend", "DEPLOY_TARGET": "modal", **_billing_secret_binding_env,
          **_redis_secret_binding_env,
          **_serve_identity_env,
          "MODAL_DEPLOYMENT_TRAFFIC_HOLD": _DEPLOYMENT_TRAFFIC_HOLD_VALUE})
)


@operations_app.function(image=migrate_image, secrets=_operations_secrets, timeout=900)
def migrate(source_revision: str, authorization_token: str) -> None:
    """Apply Alembic migrations to the production database."""
    import os
    import subprocess

    from scripts.modal_operation_authorization import verify_proof

    try:
        if source_revision != os.environ.get("DEPLOY_SHA"):
            raise ValueError("operation authorization is invalid")
        verify_proof(authorization_token, action="migrate", environ=os.environ)
    except Exception:
        raise RuntimeError("Modal migration authorization was not verified") from None

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd="/backend",
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"alembic upgrade failed with code {result.returncode}")


@operations_app.function(image=migrate_image, secrets=_operations_secrets, timeout=90)
def freeze_redis_recovery(source_revision: str, freeze_id: str, authorization_token: str) -> None:
    """Workflow-only durable containment; never promote or replay backup work."""
    import asyncio
    import json
    import os

    import modal

    from scripts.modal_operation_authorization import verify_proof

    if modal.is_local():
        raise RuntimeError("Redis recovery containment requires the canonical workflow runtime")
    try:
        if source_revision != os.environ.get("DEPLOY_SHA"):
            raise ValueError("operation authorization is invalid")
        verify_proof(authorization_token, action="freeze", expected_freeze_id=freeze_id, environ=os.environ)
    except Exception:
        raise RuntimeError("Redis recovery authorization was not verified") from None

    async def run():
        from app.database.connection import close_db, get_async_db_session
        from scripts.redis_recovery_quarantine import freeze_primary_for_recovery

        try:
            return await freeze_primary_for_recovery(
                get_async_db_session, environ=os.environ,
                source_revision=source_revision, freeze_id=freeze_id,
                expected_generation=0,
            )
        finally:
            await close_db()

    try:
        report = asyncio.run(run())
    except Exception:
        print(json.dumps({"status": "blocked", "reason": "recovery_containment_not_verified"}))
        raise RuntimeError("Redis recovery containment was not verified") from None
    print(json.dumps(report, sort_keys=True))


@operations_app.function(image=migrate_image, secrets=_api_secrets, timeout=120)
def billing_preflight(
    source_revision: str, expected_environment: str = "main", purpose: str = "report",
    allow_configured_live: bool = False,
) -> None:
    """Print a redacted, read-only billing report using the deployment secret bindings.

    This runs candidate source in an ephemeral diagnostic container. It does not
    claim that candidate source is already deployed, migrate the database, or
    contact a payment provider. The caller supplies its clean checkout revision.
    """
    import hashlib
    import json
    import os
    import re
    import subprocess

    from scripts.dodo_billing_preflight import EXPECTED_HEAD, public_report, rollout_assessment

    def safe_identifier(value: str) -> str:
        return value if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value) else "unavailable"

    context = {
        "application": _APP_NAME,
        "selected_environment": safe_identifier(os.environ.get("MODAL_ENVIRONMENT", "")),
        "expected_environment": safe_identifier(expected_environment),
        "image_id": safe_identifier(os.environ.get("MODAL_IMAGE_ID", "")),
        "image_role": "candidate_migration_preflight",
        "source_revision_reported": source_revision if re.fullmatch(r"[0-9a-f]{40}", source_revision) else "invalid",
        "expected_repository_head": EXPECTED_HEAD,
        "purpose": "rollout" if purpose == "rollout" else "report" if purpose == "report" else "invalid",
    }
    if (
        context["source_revision_reported"] == "invalid"
        or context["purpose"] == "invalid"
        or context["expected_environment"] == "unavailable"
        or context["selected_environment"] != context["expected_environment"]
    ):
        print(json.dumps({"execution_context": context, "status": "blocked", "error": "execution_context_mismatch"}))
        raise RuntimeError("Billing preflight refused mismatched execution context")

    try:
        fingerprint = hashlib.sha256()
        files = [Path("/backend/app/core/config.py"), Path("/backend/scripts/dodo_billing_preflight.py")]
        files.extend(sorted(Path("/backend/alembic/versions").glob("*.py")))
        for path in files:
            fingerprint.update(str(path.relative_to("/backend")).encode())
            fingerprint.update(b"\0")
            fingerprint.update(path.read_bytes())
            fingerprint.update(b"\0")
        context["source_files_sha256"] = fingerprint.hexdigest()
        result = subprocess.run(
            ["python", "/backend/scripts/dodo_billing_preflight.py"],
            cwd="/backend", capture_output=True, text=True, timeout=90,
        )
        # The script has a deliberately redacted JSON contract. Never print raw
        # stderr, a traceback, or an exception that could contain a database URL.
        report = public_report(json.loads(result.stdout))
        if not isinstance(report, dict) or result.returncode not in {0, 1, 2}:
            raise ValueError("Unexpected diagnostic result")
    except Exception:
        print(json.dumps({"execution_context": context, "status": "error", "error": "preflight_execution_failed"}))
        raise RuntimeError("Billing preflight failed; no diagnostic details were logged") from None
    if expected_environment == "main" and report.get("production_like") is not True:
        # Billing mode guards depend on the application's ENVIRONMENT setting.
        # A diagnostic against main must not bless a development classification.
        # A valid incomplete diagnostic may not include environment fields.
        # Keep its failure state so rollout cannot mistake absent DB metadata
        # for a malformed report; complete non-production reports still block.
        if report.get("status") != "diagnostic_error":
            report["status"] = "blocked"
        report["blockers"] = list(dict.fromkeys([
            *report.get("blockers", []), "main_environment_not_production_like",
        ]))
    rollout_safe = False
    if purpose == "rollout":
        try:
            assessment = rollout_assessment(report, allow_configured_live=allow_configured_live)
        except Exception:
            print(json.dumps({"execution_context": context, "status": "error", "error": "preflight_execution_failed"}))
            raise RuntimeError("Billing preflight failed; no diagnostic details were logged") from None
        if result.returncode == 2:
            assessment["safe_to_rollout"] = False
            assessment["reasons"] = list(dict.fromkeys([
                *assessment["reasons"], "rollout_diagnostics_incomplete",
            ]))
        report["rollout_safety"] = assessment
        rollout_safe = assessment["safe_to_rollout"] is True
    report["execution_context"] = context
    if purpose == "rollout":
        # Public workflow logs need only the decision, not operational account
        # counts, catalog configuration, or credential-presence metadata.
        print(json.dumps({"execution_context": context, "rollout_safety": assessment}, sort_keys=True))
    else:
        print(json.dumps(report, sort_keys=True))
    if purpose == "rollout" and rollout_safe:
        return
    if purpose == "rollout" or result.returncode or report.get("status") != "ready":
        raise RuntimeError("Billing preflight requires review; see the redacted JSON report")


@operations_app.function(image=migrate_image, secrets=_secrets, timeout=900)
def sync_templates() -> None:
    """Reconcile the production template catalog with the source-owned seed files."""
    import subprocess

    result = subprocess.run(
        ["python", "-m", "app.scripts.seed_templates"],
        cwd="/backend",
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"template synchronization failed with code {result.returncode}")


# ---------------------------------------------------------------------------
# FastAPI ASGI endpoint
# ---------------------------------------------------------------------------


@app.function(
    image=api_image,
    secrets=_api_secrets,
    min_containers=1,
    timeout=3600,
    scaledown_window=300,
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def fastapi_app():
    # Modal serves this ASGI app through its managed ingress rather than
    # Uvicorn, so Uvicorn's ``--ws-max-size`` option is not applicable here.
    # The jobs/collaboration handlers retain their 64 KiB/256 KiB app-level
    # protocol bounds before parsing or relaying frames.
    import sys

    sys.path.insert(0, "/backend")
    from app.main import app as _app

    return _app
