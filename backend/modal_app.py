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
_APT_BASE = ["gcc", "g++", "libpq-dev", "curl"]

# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
# API image — FastAPI + all Python deps, no system LaTeX toolchain
api_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(*_APT_BASE)
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir(str(_BACKEND_DIR), remote_path="/backend", copy=True, ignore=_IGNORE)
    .env({"PYTHONPATH": "/backend", "DEPLOY_TARGET": "modal"})
)

# LaTeX worker image — same Python deps + full texlive for compilation
latex_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        *_APT_BASE,
        "texlive-latex-extra",
        "texlive-fonts-recommended",
        "texlive-fonts-extra",
        "texlive-science",
        "texlive-xetex",
        "texlive-luatex",
        "latexmk",
        "poppler-utils",   # pdftotext for page-count extraction
    )
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
    retries=modal.Retries(max_retries=1, backoff_coefficient=2.0),
    scaledown_window=60,
)
def run_latex_task(payload: dict) -> None:
    """Compile LaTeX to PDF (texlive installed in image; no Docker needed)."""
    _init_worker_redis()
    from app.workers.latex_worker import compile_latex_task
    compile_latex_task.apply(kwargs=payload)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=600,
    retries=modal.Retries(max_retries=1, backoff_coefficient=2.0),
    scaledown_window=60,
)
def run_orchestrator_task(payload: dict) -> None:
    """Combined LLM optimisation → LaTeX compilation → ATS scoring pipeline."""
    _init_worker_redis()
    from app.workers.orchestrator import optimize_and_compile_task
    optimize_and_compile_task.apply(kwargs=payload)


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
    optimize_resume_task.apply(kwargs=payload)


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
    score_resume_ats_task.apply(kwargs=payload)


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
    analyze_job_description_ats_task.apply(kwargs=payload)


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
    deep_analyze_ats_task.apply(kwargs=payload)


@app.function(
    image=worker_image,
    secrets=_secrets,
    timeout=60,
    scaledown_window=600,
)
def run_embed_resume_task(payload: dict) -> None:
    """Compute and store resume embedding (low-priority background task)."""
    from app.workers.ats_worker import embed_resume_task
    embed_resume_task.apply(kwargs=payload)


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
        cleanup_expired_jobs_task.apply(kwargs=payload)
    else:
        from app.workers.cleanup_worker import cleanup_temp_files_task
        cleanup_temp_files_task.apply(kwargs=payload)


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
