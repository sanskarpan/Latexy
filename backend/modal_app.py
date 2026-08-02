"""
Latexy backend — Modal deployment.

Run from the backend/ directory:
  modal deploy modal_app.py          # deploy to production
  modal serve  modal_app.py          # live-reload dev mode

Environment variables are loaded from Modal secret "latexy-backend-secrets".
DEPLOY_TARGET=modal is baked into the image so worker dispatch routes here.
"""

from pathlib import Path

import modal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_APP_NAME = "latexy-backend"
_BACKEND_DIR = Path(__file__).parent   # backend/

app = modal.App(_APP_NAME)

# Directories to exclude from the code snapshot (security + size)
_IGNORE = [
    "**/.env*",
    "**/__pycache__/**",
    "**/*.pyc",
    "**/alembic/**",
    "**/test/**",
    "**/.git/**",
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
    "gcc", "g++", "libpq-dev", "curl",
    "tesseract-ocr", "tesseract-ocr-eng", "poppler-utils",
]

# The full TeX toolchain. Every engine named in ALLOWED_LATEX_COMPILERS needs its
# package here, and poppler-utils (pdftotext, for page-count extraction) comes
# from _APT_BASE.
_APT_LATEX = [
    "texlive-latex-extra",
    "texlive-fonts-recommended",
    "texlive-fonts-extra",
    "texlive-science",
    "texlive-xetex",
    "texlive-luatex",
    "texlive-lang-english",   # hyphenation patterns; matches backend/Dockerfile
    "latexmk",
]

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
api_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(*_APT_BASE, *_APT_LATEX)
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir(str(_BACKEND_DIR), remote_path="/backend", copy=True, ignore=_IGNORE)
    .env({"PYTHONPATH": "/backend", "DEPLOY_TARGET": "modal"})
)

# LaTeX worker image — same Python deps + full texlive for compilation
latex_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(*_APT_BASE, *_APT_LATEX)
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir(str(_BACKEND_DIR), remote_path="/backend", copy=True, ignore=_IGNORE)
    .env({"PYTHONPATH": "/backend", "DEPLOY_TARGET": "modal"})
)

# Worker image — Python deps only (LLM, ATS, email, cleanup tasks)
worker_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(*_APT_BASE)
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir(str(_BACKEND_DIR), remote_path="/backend", copy=True, ignore=_IGNORE)
    .env({"PYTHONPATH": "/backend", "DEPLOY_TARGET": "modal"})
)

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------
_secrets = [modal.Secret.from_name("latexy-backend-secrets")]


# ---------------------------------------------------------------------------
# Helper — initialise sync Redis for event publishing inside a worker fn
# ---------------------------------------------------------------------------
def _init_worker_redis() -> None:
    from app.core.config import settings
    from app.workers.event_publisher import initialize_worker_redis
    initialize_worker_redis(settings.REDIS_URL)


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
    min_containers=1,
    scaledown_window=120,
)
def run_latex_task(payload: dict) -> None:
    """Compile LaTeX to PDF (texlive installed in image; no Docker needed)."""
    _init_worker_redis()
    from app.workers.latex_worker import compile_latex_task
    # throw=False: prevents Celery's self.retry() Retry exception from propagating
    # to Modal (which would cause a double-execution via Modal's retry mechanism).
    # The Celery task publishes its own error events; Modal must not independently retry.
    compile_latex_task.apply(kwargs=payload, throw=False)


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
    min_containers=1,
    scaledown_window=180,
)
def run_orchestrator_task(payload: dict) -> None:
    """Combined LLM optimisation → LaTeX compilation → ATS scoring pipeline."""
    _init_worker_redis()
    from app.workers.orchestrator import optimize_and_compile_task
    optimize_and_compile_task.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=300,
    scaledown_window=60,
)
def run_llm_task(payload: dict) -> None:
    """LLM resume optimisation (streaming tokens published via Redis)."""
    _init_worker_redis()
    from app.workers.llm_worker import optimize_resume_task
    optimize_resume_task.apply(kwargs=payload, throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=120,
    scaledown_window=60,
)
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
def run_cover_letter_task(payload: dict) -> None:
    """LLM cover-letter generation."""
    _init_worker_redis()
    from app.workers.cover_letter_worker import generate_cover_letter_task
    resume_latex = payload.pop("resume_latex")
    job_description = payload.pop("job_description")
    generate_cover_letter_task.apply(
        args=[resume_latex, job_description], kwargs=payload, throw=False
    )


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=300,
    scaledown_window=60,
)
def run_interview_prep_task(payload: dict) -> None:
    """LLM interview-prep generation."""
    _init_worker_redis()
    from app.workers.interview_prep_worker import generate_interview_prep_task
    resume_latex = payload.pop("resume_latex")
    prep_id = payload.pop("prep_id")
    generate_interview_prep_task.apply(
        args=[resume_latex, prep_id], kwargs=payload, throw=False
    )


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=300,
    scaledown_window=60,
)
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
def run_email_task(payload: dict) -> None:
    """Transactional job-completion email."""
    from app.workers.email_worker import send_job_completion_email
    send_job_completion_email.apply(kwargs=payload, throw=False)


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
    schedule=modal.Period(hours=1),
)
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
    schedule=modal.Period(minutes=30),
)
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
    schedule=modal.Period(minutes=5),
)
def scheduled_health_check() -> None:
    """Worker health check (beat: every 300s)."""
    _init_worker_redis()
    from app.workers.cleanup_worker import health_check_task
    health_check_task.apply(throw=False)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=300,
    schedule=modal.Cron("0 9 * * 1"),
)
def scheduled_weekly_digest() -> None:
    """Monday 09:00 weekly digest fan-out (inert while EMAIL_ENABLED is false)."""
    _init_worker_redis()
    from app.workers.email_worker import send_weekly_digest_to_all
    send_weekly_digest_to_all.apply(throw=False)


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------
# Locally, migrations run on backend startup. In production nothing applied them:
# alembic/ was excluded from every image and no deploy step ran it. Run this
# BEFORE `modal deploy` whenever a migration has landed:
#
#     modal run modal_app.py::migrate
#
# Deliberately a separate manual step rather than a lifespan hook, so a schema
# change is never applied by whichever API container happens to boot first.
migrate_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(*_APT_BASE)
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir(
        str(_BACKEND_DIR),
        remote_path="/backend",
        copy=True,
        ignore=[p for p in _IGNORE if "alembic" not in p],
    )
    .env({"PYTHONPATH": "/backend", "DEPLOY_TARGET": "modal"})
)


@app.function(image=migrate_image, secrets=_secrets, timeout=900)
def migrate() -> None:
    """Apply Alembic migrations to the production database."""
    import subprocess

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


# ---------------------------------------------------------------------------
# FastAPI ASGI endpoint
# ---------------------------------------------------------------------------

@app.function(
    image=api_image,
    secrets=_secrets,
    min_containers=1,
    timeout=3600,
    scaledown_window=300,
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def fastapi_app():
    import sys
    sys.path.insert(0, "/backend")
    from app.main import app as _app
    return _app
