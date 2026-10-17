"""
Latexy backend â€” Modal deployment definition.

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

from app.core.deployment_hold import deployment_traffic_held
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
# latex_image. backend/Dockerfile has installed them all along â€” omitting them here
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
# texlive-fonts-extra trimmed to just its cm-super dependency (#1281 â€”
# "Compile latency: 37s median -> target <10s"): the full package is 1,665 of
# the 1,750MB this apt_install pulls in (per Debian package sizes). An audit of
# every currently-active production template's LaTeX source
# (backend/app/data/templates/**/*.tex) plus official_snippets.py found only
# array, enumitem, fontenc, geometry, hyperref, inputenc, microtype, parskip,
# titlesec, xcolor, amsmath, amssymb, graphicx, booktabs, tikz, pgfplots,
# tcolorbox, appendixnumberbeamer, ccicons, xspace in use â€” all standard
# packages shipped by texlive-latex-base/texlive-latex-recommended (a
# transitive dependency of texlive-latex-extra) or texlive-latex-extra itself.
#
# BUT: texlive-fonts-extra Recommends (and apt installs by default) the
# `cm-super` font package, which nothing else here depends on â€” and it is
# load-bearing. Every default-Computer-Modern template compiles via
# microtype's font-expansion feature, which needs cm-super's Type1 fonts
# (verified locally: dropping texlive-fonts-extra outright reproduces
# `! pdfTeX error (font expansion): auto expansion is only possible with
# scalable fonts` and a fatal, no-PDF compile on the production "Clean Simple"
# template â€” this is NOT a hypothetical). Installing `cm-super` directly
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
  '\textenglish{Latin email@example.com â€¢}' \
  'æ—¥æœ¬èªž' \
  '\textarabic{Ø§Ù„Ø¹Ø±Ø¨ÙŠØ©}' \
  '\texthebrew{×¢×‘×¨×™×ª}' \
  '\texthindi{à¤¹à¤¿à¤‚à¤¦à¥€ \textenglish{email@example.com â€¢} \textbf{à¤¬à¥‹à¤²à¥à¤¡} \textit{à¤¤à¤¿à¤°à¤›à¤¾} \textbf{\textit{à¤¦à¥‹à¤¨à¥‹à¤‚}}}' \
  '\begin{itemize}' \
  '\item \texthindi{à¤­à¥à¤—à¤¤à¤¾à¤¨ à¤®à¤‚à¤š \textenglish{email@example.com â€¢}}' \
  '\begin{itemize}\item \texthindi{à¤¦à¥‚à¤¸à¤°à¤¾ à¤¸à¥à¤¤à¤°}\end{itemize}' \
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
# API image â€” FastAPI + all Python deps + the LaTeX toolchain.
#
# The toolchain is NOT optional here: POST /compile, POST /public/compile and
# POST /optimize-and-compile exec the engine in-process, inside this container.
# Hotfix #956 made local_engine_allowed() return True on Modal, so the gate now
# passes and the exec reaches the binary â€” which, without these packages, does
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

api_image = (
    texlive_image.pip_install_from_requirements("requirements.lock", extra_options="--require-hashes")
    .add_local_dir(str(_BACKEND_DIR), remote_path="/backend", copy=True, ignore=_IGNORE)
    .env({"PYTHONPATH": "/backend", "DEPLOY_TARGET": "modal", **_renderer_capability_env,
ç½=¶‰žËkºwµçu”…Ì„Í¡•‘Õ±•™Õ¹Ñ¥½¸ìÉ•Á±…¥¹œ¥Ð¥¸Á±…”…¸±•…Ù”Í•ÉÙ•ÈµÍ¥‘”4(ŒÍ¡•‘Õ±”µ•Ñ…‘…Ñ„…ÍÍ½¥…Ñ•Ý¥Ñ Ñ¡…Ð¹…µ”‘ÕÉ¥¹œÉ½±±½ÕÐ¸Q¡”É•Ñ•¹Ñ¥½¸4(Œ‰•¡…Ù¥½È¥Ì‘•Á±½åµ•¹Ðµ‘•Á•¹‘•¹Ð°Í¼¹•Ù•ÈÉ•ÍÑ½É”Ñ¡”½±™Õ¹Ñ¥½¸¹…µ”¸4)}É•ÅÕ¥É•}Ý½É­•É}‘¥ÍÁ…Ñ 4)‘•˜ÉÕ¹}Í¡•‘Õ±•‘}¡•…±Ñ¡}¡•¬ ¤€´ø9½¹”è4(€€€€ˆˆ‰]½É­•È¡•…±Ñ ¡•¬ÉÕ¹¹•È€¡‰•…Ðè•Ù•Éä€ÌÀÁÌ¤¸4(4(€€€Q¡”…‘•¹”¥Ì½Ý¹•‰äÍ¡•‘Õ±•‘}™¥Ù•}µ¥¹ÕÑ•}µ…¥¹Ñ•¹…¹•€Í¼Ñ¡¥Ì4(€€€ÉÕ¹¹•ÈÉ•µ…¥¹Ì¥¹‘•Á•¹‘•¹Ñ±ä…±±…‰±”…¹É••¥Ù•Ì¥ÑÌ½Ý¸Ñ¥µ•½ÕÐ¸4(€€€€ˆˆˆ4(€€€}¥¹¥Ñ}Ý½É­•É}É•‘¥Ì ¤4(€€€™É½´…ÁÀ¹Ý½É­•ÉÌ¹±•…¹ÕÁ}Ý½É­•È¥µÁ½ÉÐ¡•…±Ñ¡}¡•­}Ñ…Í¬4(4(€€€¡•…±Ñ¡}¡•­}Ñ…Í¬¹…ÁÁ±ä¡Ñ¡É½Üõ…±Í”¤4(4(4)…ÁÀ¹™Õ¹Ñ¥½¸ 4(€€€¥µ…”õÝ½É­•É}¥µ…”°4(€€€Í•É•ÑÌõ}Í•É•ÑÌ°4(€€€Ñ¥µ•½ÕÐôÌÀÀ°4(€€€Í¡•‘Õ±”õ9½¹”¥˜}A1=e59Q}QI%}!1•±Í”µ½‘…°¹É½¸ ˆÀ€ä€¨€¨€Äˆ¤°4(¤4)}É•ÅÕ¥É•}Ý½É­•É}‘¥ÍÁ…Ñ 4)‘•˜Í¡•‘Õ±•‘}Ý••­±å}‘¥•ÍÐ ¤€´ø9½¹”è4(€€€€ˆˆ‰5½¹‘…ä€ÀäèÀÀÝ••­±ä‘¥•ÍÐ™…¸µ½ÕÐ€¡¥¹•ÉÐÝ¡¥±”5%1}9	1¥Ì™…±Í”¤¸ˆˆˆ4(€€€}¥¹¥Ñ}Ý½É­•É}É•‘¥Ì ¤4(€€€™É½´…ÁÀ¹Ý½É­•ÉÌ¹•µ…¥±}Ý½É­•È¥µÁ½ÉÐÍ•¹‘}Ý••­±å}‘¥•ÍÑ}Ñ½}…±°4(4(€€€Í•¹‘}Ý••­±å}‘¥•ÍÑ}Ñ½}…±°¹…ÁÁ±ä¡Ñ¡É½Üõ…±Í”¤4(4(4)…ÁÀ¹™Õ¹Ñ¥½¸ 4(€€€¥µ…”õÝ½É­•É}¥µ…”°4(€€€Í•É•ÑÌõ}Í•É•ÑÌ°4(€€€Ñ¥µ•½ÕÐôÌÀÀ°4(¤4)}É•ÅÕ¥É•}Ý½É­•É}‘¥ÍÁ…Ñ 4)‘•˜Í¡•‘Õ±•‘}ÑÉ…­•É}¹½Ñ¥™¥…Ñ¥½¹Ì ¤€´ø9½¹”è4(€€€€ˆˆ‰•±¥Ù•È‘Õ”…ÁÁ±¥…Ñ¥½¸É•µ¥¹‘•ÉÌ…¹Í…Ù•µÍ•…É É•Ù¥•Ü¹Õ‘•Ì¸4(4(€€€Q¡”…‘•¹”¥Ì½Ý¹•‰äÍ¡•‘Õ±•‘}™¥Ù•}µ¥¹ÕÑ•}µ…¥¹Ñ•¹…¹•€Í¼Ñ¡¥Ì4(€€€ÉÕ¹¹•ÈÉ•µ…¥¹Ì¥¹‘•Á•¹‘•¹Ñ±ä…±±…‰±”…¹É••¥Ù•Ì¥ÑÌ½Ý¸Ñ¥µ•½ÕÐ¸4(€€€€ˆˆˆ4(€€€}¥¹¥Ñ}Ý½É­•É}É•‘¥Ì ¤4(€€€™É½´…ÁÀ¹Ý½É­•ÉÌ¹ÑÉ…­•É}¹½Ñ¥™¥…Ñ¥½¹}Ý½É­•È¥µÁ½ÉÐÍ•¹‘}ÑÉ…­•É}¹½Ñ¥™¥…Ñ¥½¹Ì4(4(€€€Í•¹‘}ÑÉ…­•É}¹½Ñ¥™¥…Ñ¥½¹Ì¹…ÁÁ±ä¡Ñ¡É½Üõ…±Í”¤4(4(4)…ÁÀ¹™Õ¹Ñ¥½¸ 4(€€€¥µ…”õÝ½É­•É}¥µ…”°4(€€€Í•É•ÑÌõ}Í•É•ÑÌ°4(€€€Ñ¥µ•½ÕÐôÌÀÀ°4(¤4)}É•ÅÕ¥É•}Ý½É­•É}‘¥ÍÁ…Ñ 4)‘•˜Í¡•‘Õ±•‘}½µµ•¹Ñ}µ•¹Ñ¥½¹}É•½Ù•Éä ¤€´ø9½¹”è4(€€€€ˆˆ‰I•½Ù•Èµ•¹Ñ¥½¸É½ÝÌÝ¡½Í”Á½ÍÐµ½µµ¥Ð•¹ÅÕ•Õ”µ¥ÍÍ•Ñ¡”ÅÕ•Õ”¸4(4(€€€Q¡”…‘•¹”¥Ì½Ý¹•‰äÍ¡•‘Õ±•‘}µ¥¹ÕÑ•}É•½Ù•Éå€Í¼Ñ¡¥ÌÉÕ¹¹•È4(€€€É•µ…¥¹Ì¥¹‘•Á•¹‘•¹Ñ±ä…±±…‰±”…¹É••¥Ù•Ì¥ÑÌ½Ý¸Ñ¥µ•½ÕÐ¸4(€€€€ˆˆˆ4(€€€}¥¹¥Ñ}Ý½É­•É}É•‘¥Ì ¤4(€€€™É½´…ÁÀ¹Ý½É­•ÉÌ¹•µ…¥±}Ý½É­•È¥µÁ½ÉÐÍ•¹‘}Á•¹‘¥¹}½µµ•¹Ñ}µ•¹Ñ¥½¹}•µ…¥±Ì4(4(€€€Í•¹‘}Á•¹‘¥¹}½µµ•¹Ñ}µ•¹Ñ¥½¹}•µ…¥±Ì¹…ÁÁ±ä¡Ñ¡É½Üõ…±Í”¤4(4(4)…ÁÀ¹™Õ¹Ñ¥½¸ 4(€€€¥µ…”õÝ½É­•É}¥µ…”°4(€€€Í•É•ÑÌõ}Í•É•ÑÌ°4(€€€Ñ¥µ•½ÕÐôÌÀÀ°4(¤4)}É•ÅÕ¥É•}Ý½É­•É}‘¥ÍÁ…Ñ 4)‘•˜Í¡•‘Õ±•‘}‘½Õµ•¹Ñ}•µ…¥±}É•½Ù•Éä ¤€´ø9½¹”è4(€€€€ˆˆ‰I•½Ù•È½µÁ¥±•µ‘½Õµ•¹Ð•µ…¥°É½ÝÌµ¥ÍÍ•‰ä„‰É½­•È½ÁÉ½•ÍÌÉ…Í ¸4(4(€€€Q¡”…‘•¹”¥Ì½Ý¹•‰äÍ¡•‘Õ±•‘}µ¥¹ÕÑ•}É•½Ù•Éå€Í¼Ñ¡¥ÌÉÕ¹¹•È4(€€€É•µ…¥¹Ì¥¹‘•Á•¹‘•¹Ñ±ä…±±…‰±”…¹É••¥Ù•Ì¥ÑÌ½Ý¸Ñ¥µ•½ÕÐ¸4(€€€€ˆˆˆ4(€€€}¥¹¥Ñ}Ý½É­•É}É•‘¥Ì ¤4(€€€™É½´…ÁÀ¹Ý½É­•ÉÌ¹•µ…¥±}Ý½É­•È¥µÁ½ÉÐÍ•¹‘}Á•¹‘¥¹}‘½Õµ•¹Ñ}•µ…¥±}‘•±¥Ù•É¥•Ì4(4(€€€Í•¹‘}Á•¹‘¥¹}‘½Õµ•¹Ñ}•µ…¥±}‘•±¥Ù•É¥•Ì¹…ÁÁ±ä¡Ñ¡É½Üõ…±Í”¤4(4(4)…ÁÀ¹™Õ¹Ñ¥½¸ 4(€€€¥µ…”õÝ½É­•É}¥µ…”°4(€€€Í•É•ÑÌõ}Í•É•ÑÌ°4(€€€Ñ¥µ•½ÕÐôÄÈÀ°4(€€€Í¡•‘Õ±”õ9½¹”¥˜}A1=e59Q}QI%}!1•±Í”µ½‘…°¹A•É¥½¡µ¥¹ÕÑ•ÌôÔ¤°4(¤4)}É•ÅÕ¥É•}Ý½É­•É}‘¥ÍÁ…Ñ 4)‘•˜Í¡•‘Õ±•‘}™¥Ù•}µ¥¹ÕÑ•}µ…¥¹Ñ•¹…¹” ¤€´ø9½¹”è4(€€€€ˆˆ‰…¸½ÕÐÑ¡”ÑÝ¼™¥Ù”µµ¥¹ÕÑ”µ…¥¹Ñ•¹…¹”ÉÕ¹¹•ÉÌ¥¹‘•Á•¹‘•¹Ñ±ä¸ˆˆˆ4(€€€}¥¹¥Ñ}Ý½É­•É}É•‘¥Ì ¤4(€€€ÍÁ…Ý¹}™…¥±ÕÉ•Ì€ômt4(4(€€€ÑÉäè4(€€€€€€€ÉÕ¹}Í¡•‘Õ±•‘}¡•…±Ñ¡}¡•¬¹ÍÁ…Ý¸ ¤4(€€€•á•ÁÐá•ÁÑ¥½¸…Ì•áŒè4(€€€€€€€ÁÉ¥¹Ð¡˜‰Í¡•‘Õ±•¡•…±Ñ µ¡•¬ÍÁ…Ý¸™…¥±•èíÑåÁ”¡•áŒ¤¹}}¹…µ•}}ôˆ¤4(€€€€€€€ÍÁ…Ý¹}™…¥±ÕÉ•Ì¹…ÁÁ•¹ ‰ÉÕ¹}Í¡•‘Õ±•‘}¡•…±Ñ¡}¡•¬ˆ¤4(4(€€€ÑÉäè4(€€€€€€€Í¡•‘Õ±•‘}ÑÉ…­•É}¹½Ñ¥™¥…Ñ¥½¹Ì¹ÍÁ…Ý¸ ¤4(€€€•á•ÁÐá•ÁÑ¥½¸…Ì•áŒè4(€€€€€€€ÁÉ¥¹Ð¡˜‰Í¡•‘Õ±•ÑÉ…­•Èµ¹½Ñ¥™¥…Ñ¥½¸ÍÁ…Ý¸™…¥±•èíÑåÁ”¡•áŒ¤¹}}¹…µ•}}ôˆ¤4(€€€€€€€ÍÁ…Ý¹}™…¥±ÕÉ•Ì¹…ÁÁ•¹ ‰Í¡•‘Õ±•‘}ÑÉ…­•É}¹½Ñ¥™¥…Ñ¥½¹Ìˆ¤4(4(€€€¥˜ÍÁ…Ý¹}™…¥±ÕÉ•Ìè4(€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È 4(€€€€€€€€€€€€‰Í¡•‘Õ±•™¥Ù”µµ¥¹ÕÑ”µ…¥¹Ñ•¹…¹”™…¸µ½ÕÐ™…¥±•è€ˆ4(€€€€€€€€€€€€¬€ˆ°ˆ¹©½¥¸¡ÍÁ…Ý¹}™…¥±ÕÉ•Ì¤4(€€€€€€€€¤4(4(4)…ÁÀ¹™Õ¹Ñ¥½¸ 4(€€€¥µ…”õÝ½É­•É}¥µ…”°4(€€€Í•É•ÑÌõ}Í•É•ÑÌ°4(€€€Ñ¥µ•½ÕÐôÄÈÀ°4(€€€Í¡•‘Õ±”õ9½¹”¥˜}A1=e59Q}QI%}!1•±Í”µ½‘…°¹A•É¥½¡µ¥¹ÕÑ•ÌôÄ¤°4(¤4)}É•ÅÕ¥É•}Ý½É­•É}‘¥ÍÁ…Ñ 4)‘•˜Í¡•‘Õ±•‘}µ¥¹ÕÑ•}É•½Ù•Éä ¤€´ø9½¹”è4(€€€€ˆˆ‰…¸½ÕÐÑ¡”ÑÝ¼½¹”µµ¥¹ÕÑ”É•½Ù•ÉäÉÕ¹¹•ÉÌ¥¹‘•Á•¹‘•¹Ñ±ä¸ˆˆˆ4(€€€}¥¹¥Ñ}Ý½É­•É}É•‘¥Ì ¤4(€€€ÍÁ…Ý¹}™…¥±ÕÉ•Ì€ômt4(4(€€€ÑÉäè4(€€€€€€€Í¡•‘Õ±•‘}½µµ•¹Ñ}µ•¹Ñ¥½¹}É•½Ù•Éä¹ÍÁ…Ý¸ ¤4(€€€•á•ÁÐá•ÁÑ¥½¸…Ì•áŒè4(€€€€€€€ÁÉ¥¹Ð¡˜‰Í¡•‘Õ±•½µµ•¹Ðµµ•¹Ñ¥½¸É•½Ù•ÉäÍÁ…Ý¸™…¥±•èíÑåÁ”¡•áŒ¤¹}}¹…µ•}}ôˆ¤4(€€€€€€€ÍÁ…Ý¹}™…¥±ÕÉ•Ì¹…ÁÁ•¹ ‰Í¡•‘Õ±•‘}½µµ•¹Ñ}µ•¹Ñ¥½¹}É•½Ù•Éäˆ¤4(4(€€€ÑÉäè4(€€€€€€€Í¡•‘Õ±•‘}‘½Õµ•¹Ñ}•µ…¥±}É•½Ù•Éä¹ÍÁ…Ý¸ ¤4(€€€•á•ÁÐá•ÁÑ¥½¸…Ì•áŒè4(€€€€€€€ÁÉ¥¹Ð¡˜‰Í¡•‘Õ±•‘½Õµ•¹Ðµ•µ…¥°É•½Ù•ÉäÍÁ…Ý¸™…¥±•èíÑåÁ”¡•áŒ¤¹}}¹…µ•}}ôˆ¤4(€€€€€€€ÍÁ…Ý¹}™…¥±ÕÉ•Ì¹…ÁÁ•¹ ‰Í¡•‘Õ±•‘}‘½Õµ•¹Ñ}•µ…¥±}É•½Ù•Éäˆ¤4(4(€€€¥˜ÍÁ…Ý¹}™…¥±ÕÉ•Ìè4(€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È 4(€€€€€€€€€€€€‰Í¡•‘Õ±•½¹”µµ¥¹ÕÑ”É•½Ù•Éä™…¸µ½ÕÐ™…¥±•è€ˆ4(€€€€€€€€€€€€¬€ˆ°ˆ¹©½¥¸¡ÍÁ…Ý¹}™…¥±ÕÉ•Ì¤4(€€€€€€€€¤4(4(4(Œ€´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´4(Œ•Á±½åµ•¹ÐÁÉ•™±¥¡Ð…¹µ¥É…Ñ¥½¹Ì4(Œ€´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´4)½Á•É…Ñ¥½¹Í}…ÁÀ¹™Õ¹Ñ¥½¸¡¥µ…”õ…Á¥}¥µ…”°Í•É•ÑÌõ}…Á¥}Í•É•ÑÌ°Ñ¥µ•½ÕÐôØÀ¤4)‘•˜É•¹‘•É•É}ÁÉ•™±¥¡Ð ¤€´ø‘¥Ðè4(€€€€ˆˆ‰Y…±¥‘…Ñ”…ÑÕ…°A$½¹™¥ÕÉ…Ñ¥½¸½¹±äì¹•Ù•È•ÉÑ¥™ä½ÈÍÑ…ÉÐ„Y4¸ˆˆˆ4(€€€¥µÁ½ÉÐ½¹Ñ•áÑ±¥ˆ4(€€€¥µÁ½ÉÐ©Í½¸4(€€€¥µÁ½ÉÐ±½¥¹œ4(€€€¥µÁ½ÉÐ½Ì4(€€€¥µÁ½ÉÐÍåÌ4(4(€€€ÁÉ•Ù¥½ÕÍ}±½¥¹}‘¥Í…‰±”€ô±½¥¹œ¹É½½Ð¹µ…¹…•È¹‘¥Í…‰±”4(€€€¡•­}™…¥±•€ô…±Í”4(€€€ÑÉäè4(€€€€€€€€ŒQ¡¥Ì¥Í½±…Ñ•™Õ¹Ñ¥½¸¡…Ì¹¼½¹ÕÉÉ•¹Ð¥¹ÁÕÑÌ¸MÕÁÁÉ•ÍÌÍÑ…ÉÑÕÀ4(€€€€€€€€Œ‘¥…¹½ÍÑ¥ÌÝ¡¥±”¥µÁ½ÉÑ¥¹œÍ•ÑÑ¥¹Ìè•á¥ÍÑ¥¹œ¡…¹‘±•ÉÌµ…äÉ•Ñ…¥¸4(€€€€€€€€ŒÑ¡”½É¥¥¹…°ÍÑ‘•ÉÈ°Í¼É•‘¥É•Ñ¥¹œÑ¡”ÍÑÉ•…µÌ…±½¹”¥Ì¥¹ÍÕ™™¥¥•¹Ð¸4(€€€€€€€±½¥¹œ¹‘¥Í…‰±”¡ÍåÌ¹µ…áÍ¥é”¤4(€€€€€€€Ý¥Ñ ½Á•¸¡½Ì¹‘•Ù¹Õ±°°€‰Üˆ¤…Ì‘¥Í…É‘•‘}½ÕÑÁÕÐ°½¹Ñ•áÑ±¥ˆ¹É•‘¥É•Ñ}ÍÑ‘½ÕÐ¡‘¥Í…É‘•‘}½ÕÑÁÕÐ¤°½¹Ñ•áÑ±¥ˆ¹É•‘¥É•Ñ}ÍÑ‘•ÉÈ¡‘¥Í…É‘•‘}½ÕÑÁÕÐ¤è4(€€€€€€€€€€€™É½´…ÁÀ¹Í•ÉÙ¥•Ì¹É•¹‘•É}•¹¥¹”¹‘•Á±½åµ•¹Ñ}ÁÉ•™±¥¡Ð¥µÁ½ÉÐÉ•¹‘•É•É}½¹™¥ÕÉ…Ñ¥½¹}É•Á½ÉÐ4(4(€€€€€€€€€€€É•Á½ÉÐ€ôÉ•¹‘•É•É}½¹™¥ÕÉ…Ñ¥½¹}É•Á½ÉÐ ¤4(€€€•á•ÁÐá•ÁÑ¥½¸è4(€€€€€€€€Œ½¹™¥ÕÉ…Ñ¥½¸Ù…±¥‘…Ñ¥½¸™…¥±ÕÉ•Ì…¸½¹Ñ…¥¸Í•É•Ð¥¹ÁÕÐÙ…±Õ•Ì¸4(€€€€€€€€Œ-••ÀÑ¡”ÁÕ‰±¥Œ‘¥…¹½ÍÑ¥Œ™¥á•°¥¹±Õ‘¥¹œ¥µÁ½ÉÐµÑ¥µ”™…¥±ÕÉ•Ì¸4(€€€€€€€¡•­}™…¥±•€ôQÉÕ”4(€€€€€€€É•Á½ÉÐ€ôì‰½¹™¥ÕÉ…Ñ¥½¹}É•…‘äˆè…±Í”°€‰•ÉÑ¥™¥…Ñ¥½¹}Ù•É¥™¥•ˆè…±Í”°4(€€€€€€€€€€€€€€€€€€‰É•…Í½¹Ìˆèl‰½¹™¥ÕÉ…Ñ¥½¹}¡•­}™…¥±•‰uô4(€€€™¥¹…±±äè4(€€€€€€€±½¥¹œ¹‘¥Í…‰±”¡ÁÉ•Ù¥½ÕÍ}±½¥¹}‘¥Í…‰±”¤4(€€€ÁÉ¥¹Ð¡©Í½¸¹‘ÕµÁÌ¡É•Á½ÉÐ°Í½ÉÑ}­•åÌõQÉÕ”¤¤4(€€€¥˜¡•­}™…¥±•è4(€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È ‰I•¹‘•É•È½¹™¥ÕÉ…Ñ¥½¸ÁÉ•™±¥¡Ð™…¥±•ˆ¤™É½´9½¹”4(€€€¥˜¹½ÐÉ•Á½ÉÑl‰½¹™¥ÕÉ…Ñ¥½¹}É•…‘ä‰tè4(€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È ‰I•¹‘•É•È½¹™¥ÕÉ…Ñ¥½¸ÁÉ•™±¥¡Ð‰±½­•‘•Á±½åµ•¹Ðˆ¤4(€€€É•ÑÕÉ¸É•Á½ÉÐ4(4(4(Œ1½…±±ä°µ¥É…Ñ¥½¹ÌÉÕ¸½¸‰…­•¹ÍÑ…ÉÑÕÀ¸AÉ½‘ÕÑ¥½¸µ¥É…Ñ¥½¹Ì…É”¥¹Ù½­•4(Œ½¹±ä‰ä‘•Á±½äµµ½‘…°¹åµ°…™Ñ•È…¸•áÑ•É¹…°‘É…¥¸½É•½Ù•ÉäÁÉ½•‘ÕÉ”…¹„4(ŒÉ•…µ½¹±äÕÉÉ•¹ÐÁÀ¥‘•¹Ñ¥Ñä½ÍÑ…Ñ”¡•¬¸Q¡”Ý½É­™±½Ü‘½•Ì¹½ÐÍÑ½ÀÑ¡”ÁÀ4(Œ½ÈÙ•É¥™äÅÕ•Õ•½¥¸µ™±¥¡ÐÝ½É¬¸-••Àµ¥É…Ñ¥½¸Í•Á…É…Ñ”™É½´A$ÍÑ…ÉÑÕÀÍ¼4(Œ¹¼½¹Ñ…¥¹•È…¸µ¥É…Ñ”…Ì…¸¥¹¥‘•¹Ñ…°Í¥‘”•™™•Ð¸4)µ¥É…Ñ•}¥µ…”€ô€ 4(€€€µ½‘…°¹%µ…”¹‘•‰¥…¹}Í±¥´¡ÁåÑ¡½¹}Ù•ÉÍ¥½¸ôˆÌ¸ÄÈˆ¤4(€€€€¹…ÁÑ}¥¹ÍÑ…±° ©}AQ}	M¤4(€€€€¹Á¥Á}¥¹ÍÑ…±±}™É½µ}É•ÅÕ¥É•µ•¹ÑÌ ‰É•ÅÕ¥É•µ•¹ÑÌ¹±½¬ˆ°•áÑÉ…}½ÁÑ¥½¹Ìôˆ´µÉ•ÅÕ¥É”µ¡…Í¡•Ìˆ¤4(€€€€¹…‘‘}±½…±}‘¥È 4(€€€€€€€ÍÑÈ¡}	-9}%H¤°4(€€€€€€€É•µ½Ñ•}Á…Ñ ôˆ½‰…­•¹ˆ°4(€€€€€€€½ÁäõQÉÕ”°4(€€€€€€€¥¹½É”õmÀ™½ÈÀ¥¸}%9=I¥˜€‰…±•µ‰¥Œˆ¹½Ð¥¸Át°4(€€€€¤4(€€€€¹•¹Ø¡ì‰AeQ!=9AQ ˆè€ˆ½‰…­•¹ˆ°€‰A1=e}QIPˆè€‰µ½‘…°ˆ°€¨©}‰¥±±¥¹}Í•É•Ñ}‰¥¹‘¥¹}•¹Ø°4(€€€€€€€€€€‰5=1}A1=e59Q}QI%}!=1ˆè}A1=e59Q}QI%}!=1}Y1Uô¤4(¤4(4(4)½Á•É…Ñ¥½¹Í}…ÁÀ¹™Õ¹Ñ¥½¸¡¥µ…”õµ¥É…Ñ•}¥µ…”°Í•É•ÑÌõ}Í•É•ÑÌ°Ñ¥µ•½ÕÐôäÀÀ¤4)‘•˜µ¥É…Ñ” ¤€´ø9½¹”è4(€€€€ˆˆ‰ÁÁ±ä±•µ‰¥Œµ¥É…Ñ¥½¹ÌÑ¼Ñ¡”ÁÉ½‘ÕÑ¥½¸‘…Ñ…‰…Í”¸ˆˆˆ4(€€€¥µÁ½ÉÐÍÕ‰ÁÉ½•ÍÌ4(4(€€€É•ÍÕ±Ð€ôÍÕ‰ÁÉ½•ÍÌ¹ÉÕ¸ 4(€€€€€€€l‰…±•µ‰¥Œˆ°€‰ÕÁÉ…‘”ˆ°€‰¡•…‰t°4(€€€€€€€Ýôˆ½‰…­•¹ˆ°4(€€€€€€€…ÁÑÕÉ•}½ÕÑÁÕÐõQÉÕ”°4(€€€€€€€Ñ•áÐõQÉÕ”°4(€€€€¤4(€€€ÁÉ¥¹Ð¡É•ÍÕ±Ð¹ÍÑ‘½ÕÐ¤4(€€€¥˜É•ÍÕ±Ð¹É•ÑÕÉ¹½‘”€„ô€Àè4(€€€€€€€ÁÉ¥¹Ð¡É•ÍÕ±Ð¹ÍÑ‘•ÉÈ¤4(€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È¡˜‰…±•µ‰¥ŒÕÁÉ…‘”™…¥±•Ý¥Ñ ½‘”íÉ•ÍÕ±Ð¹É•ÑÕÉ¹½‘•ôˆ¤4(4(4)½Á•É…Ñ¥½¹Í}…ÁÀ¹™Õ¹Ñ¥½¸¡¥µ…”õµ¥É…Ñ•}¥µ…”°Í•É•ÑÌõ}…Á¥}Í•É•ÑÌ°Ñ¥µ•½ÕÐôÄÈÀ¤4)‘•˜‰¥±±¥¹}ÁÉ•™±¥¡Ð 4(€€€Í½ÕÉ•}É•Ù¥Í¥½¸èÍÑÈ°•áÁ•Ñ•‘}•¹Ù¥É½¹µ•¹ÐèÍÑÈ€ô€‰µ…¥¸ˆ°ÁÕÉÁ½Í”èÍÑÈ€ô€‰É•Á½ÉÐˆ°4(€€€…±±½Ý}½¹™¥ÕÉ•‘}±¥Ù”è‰½½°€ô…±Í”°4(¤€´ø9½¹”è4(€€€€ˆˆ‰AÉ¥¹Ð„É•‘…Ñ•°É•…µ½¹±ä‰¥±±¥¹œÉ•Á½ÉÐÕÍ¥¹œÑ¡”‘•Á±½åµ•¹ÐÍ•É•Ð‰¥¹‘¥¹Ì¸4(4(€€€Q¡¥ÌÉÕ¹Ì…¹‘¥‘…Ñ”Í½ÕÉ”¥¸…¸•Á¡•µ•É…°‘¥…¹½ÍÑ¥Œ½¹Ñ…¥¹•È¸%Ð‘½•Ì¹½Ð4(€€€±…¥´Ñ¡…Ð…¹‘¥‘…Ñ”Í½ÕÉ”¥Ì…±É•…‘ä‘•Á±½å•°µ¥É…Ñ”Ñ¡”‘…Ñ…‰…Í”°½È4(€€€½¹Ñ…Ð„Á…åµ•¹ÐÁÉ½Ù¥‘•È¸Q¡”…±±•ÈÍÕÁÁ±¥•Ì¥ÑÌ±•…¸¡•­½ÕÐÉ•Ù¥Í¥½¸¸4(€€€€ˆˆˆ4(€€€¥µÁ½ÉÐ¡…Í¡±¥ˆ4(€€€¥µÁ½ÉÐ©Í½¸4(€€€¥µÁ½ÉÐ½Ì4(€€€¥µÁ½ÉÐÉ”4(€€€¥µÁ½ÉÐÍÕ‰ÁÉ½•ÍÌ4(4(€€€™É½´ÍÉ¥ÁÑÌ¹‘½‘½}‰¥±±¥¹}ÁÉ•™±¥¡Ð¥µÁ½ÉÐaAQ}!°ÁÕ‰±¥}É•Á½ÉÐ°É½±±½ÕÑ}…ÍÍ•ÍÍµ•¹Ð4(4(€€€‘•˜Í…™•}¥‘•¹Ñ¥™¥•È¡Ù…±Õ”èÍÑÈ¤€´øÍÑÈè4(€€€€€€€É•ÑÕÉ¸Ù…±Õ”¥˜É”¹™Õ±±µ…Ñ ¡È‰mµi„µèÀ´å|¸µuìÄ°ÄÀÁôˆ°Ù…±Õ”¤•±Í”€‰Õ¹…Ù…¥±…‰±”ˆ4(4(€€€½¹Ñ•áÐ€ôì4(€€€€€€€€‰…ÁÁ±¥…Ñ¥½¸ˆè}AA}95°4(€€€€€€€€‰Í•±•Ñ•‘}•¹Ù¥É½¹µ•¹ÐˆèÍ…™•}¥‘•¹Ñ¥™¥•È¡½Ì¹•¹Ù¥É½¸¹•Ð ‰5=1}9Y%I=959Pˆ°€ˆˆ¤¤°4(€€€€€€€€‰•áÁ•Ñ•‘}•¹Ù¥É½¹µ•¹ÐˆèÍ…™•}¥‘•¹Ñ¥™¥•È¡•áÁ•Ñ•‘}•¹Ù¥É½¹µ•¹Ð¤°4(€€€€€€€€‰¥µ…•}¥ˆèÍ…™•}¥‘•¹Ñ¥™¥•È¡½Ì¹•¹Ù¥É½¸¹•Ð ‰5=1}%5}%ˆ°€ˆˆ¤¤°4(€€€€€€€€‰¥µ…•}É½±”ˆè€‰…¹‘¥‘…Ñ•}µ¥É…Ñ¥½¹}ÁÉ•™±¥¡Ðˆ°4(€€€€€€€€‰Í½ÕÉ•}É•Ù¥Í¥½¹}É•Á½ÉÑ•ˆèÍ½ÕÉ•}É•Ù¥Í¥½¸¥˜É”¹™Õ±±µ…Ñ ¡È‰lÀ´å„µ™uìÐÁôˆ°Í½ÕÉ•}É•Ù¥Í¥½¸¤•±Í”€‰¥¹Ù…±¥ˆ°4(€€€€€€€€‰•áÁ•Ñ•‘}É•Á½Í¥Ñ½Éå}¡•…ˆèaAQ}!°4(€€€€€€€€‰ÁÕÉÁ½Í”ˆè€‰É½±±½ÕÐˆ¥˜ÁÕÉÁ½Í”€ôô€‰É½±±½ÕÐˆ•±Í”€‰É•Á½ÉÐˆ¥˜ÁÕÉÁ½Í”€ôô€‰É•Á½ÉÐˆ•±Í”€‰¥¹Ù…±¥ˆ°4(€€€ô4(€€€¥˜€ 4(€€€€€€€½¹Ñ•áÑl‰Í½ÕÉ•}É•Ù¥Í¥½¹}É•Á½ÉÑ•‰t€ôô€‰¥¹Ù…±¥ˆ4(€€€€€€€½È½¹Ñ•áÑl‰ÁÕÉÁ½Í”‰t€ôô€‰¥¹Ù…±¥ˆ4(€€€€€€€½È½¹Ñ•áÑl‰•áÁ•Ñ•‘}•¹Ù¥É½¹µ•¹Ð‰t€ôô€‰Õ¹…Ù…¥±…‰±”ˆ4(€€€€€€€½È½¹Ñ•áÑl‰Í•±•Ñ•‘}•¹Ù¥É½¹µ•¹Ð‰t€„ô½¹Ñ•áÑl‰•áÁ•Ñ•‘}•¹Ù¥É½¹µ•¹Ð‰t4(€€€€¤è4(€€€€€€€ÁÉ¥¹Ð¡©Í½¸¹‘ÕµÁÌ¡ì‰•á•ÕÑ¥½¹}½¹Ñ•áÐˆè½¹Ñ•áÐ°€‰ÍÑ…ÑÕÌˆè€‰‰±½­•ˆ°€‰•ÉÉ½Èˆè€‰•á•ÕÑ¥½¹}½¹Ñ•áÑ}µ¥Íµ…Ñ ‰ô¤¤4(€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È ‰	¥±±¥¹œÁÉ•™±¥¡ÐÉ•™ÕÍ•µ¥Íµ…Ñ¡••á•ÕÑ¥½¸½¹Ñ•áÐˆ¤4(4(€€€ÑÉäè4(€€€€€€€™¥¹•ÉÁÉ¥¹Ð€ô¡…Í¡±¥ˆ¹Í¡„ÈÔØ ¤4(€€€€€€€™¥±•Ì€ômA…Ñ  ˆ½‰…­•¹½…ÁÀ½½É”½½¹™¥œ¹Áäˆ¤°A…Ñ  ˆ½‰…­•¹½ÍÉ¥ÁÑÌ½‘½‘½}‰¥±±¥¹}ÁÉ•™±¥¡Ð¹Áäˆ¥t4(€€€€€€€™¥±•Ì¹•áÑ•¹¡Í½ÉÑ•¡A…Ñ  ˆ½‰…­•¹½…±•µ‰¥Œ½Ù•ÉÍ¥½¹Ìˆ¤¹±½ˆ ˆ¨¹Áäˆ¤¤¤4(€€€€€€€™½ÈÁ…Ñ ¥¸™¥±•Ìè4(€€€€€€€€€€€™¥¹•ÉÁÉ¥¹Ð¹ÕÁ‘…Ñ”¡ÍÑÈ¡Á…Ñ ¹É•±…Ñ¥Ù•}Ñ¼ ˆ½‰…­•¹ˆ¤¤¹•¹½‘” ¤¤4(€€€€€€€€€€€™¥¹•ÉÁÉ¥¹Ð¹ÕÁ‘…Ñ”¡ˆ‰pÀˆ¤4(€€€€€€€€€€€™¥¹•ÉÁÉ¥¹Ð¹ÕÁ‘…Ñ”¡Á…Ñ ¹É•…‘}‰åÑ•Ì ¤¤4(€€€€€€€€€€€™¥¹•ÉÁÉ¥¹Ð¹ÕÁ‘…Ñ”¡ˆ‰pÀˆ¤4(€€€€€€€½¹Ñ•áÑl‰Í½ÕÉ•}™¥±•Í}Í¡„ÈÔØ‰t€ô™¥¹•ÉÁÉ¥¹Ð¹¡•á‘¥•ÍÐ ¤4(€€€€€€€É•ÍÕ±Ð€ôÍÕ‰ÁÉ½•ÍÌ¹ÉÕ¸ 4(€€€€€€€€€€€l‰ÁåÑ¡½¸ˆ°€ˆ½‰…­•¹½ÍÉ¥ÁÑÌ½‘½‘½}‰¥±±¥¹}ÁÉ•™±¥¡Ð¹Áä‰t°4(€€€€€€€€€€€Ýôˆ½‰…­•¹ˆ°…ÁÑÕÉ•}½ÕÑÁÕÐõQÉÕ”°Ñ•áÐõQÉÕ”°Ñ¥µ•½ÕÐôäÀ°4(€€€€€€€€¤4(€€€€€€€€ŒQ¡”ÍÉ¥ÁÐ¡…Ì„‘•±¥‰•É…Ñ•±äÉ•‘…Ñ•)M=8½¹ÑÉ…Ð¸9•Ù•ÈÁÉ¥¹ÐÉ…Ü4(€€€€€€€€ŒÍÑ‘•ÉÈ°„ÑÉ…•‰…¬°½È…¸•á•ÁÑ¥½¸Ñ¡…Ð½Õ±½¹Ñ…¥¸„‘…Ñ…‰…Í”UI0¸4(€€€€€€€É•Á½ÉÐ€ôÁÕ‰±¥}É•Á½ÉÐ¡©Í½¸¹±½…‘Ì¡É•ÍÕ±Ð¹ÍÑ‘½ÕÐ¤¤4(€€€€€€€¥˜¹½Ð¥Í¥¹ÍÑ…¹”¡É•Á½ÉÐ°‘¥Ð¤½ÈÉ•ÍÕ±Ð¹É•ÑÕÉ¹½‘”¹½Ð¥¸ìÀ°€Ä°€Éôè4(€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰U¹•áÁ•Ñ•‘¥…¹½ÍÑ¥ŒÉ•ÍÕ±Ðˆ¤4(€€€•á•ÁÐá•ÁÑ¥½¸è4(€€€€€€€ÁÉ¥¹Ð¡©Í½¸¹‘ÕµÁÌ¡ì‰•á•ÕÑ¥½¹}½¹Ñ•áÐˆè½¹Ñ•áÐ°€‰ÍÑ…ÑÕÌˆè€‰•ÉÉ½Èˆ°€‰•ÉÉ½Èˆè€‰ÁÉ•™±¥¡Ñ}•á•ÕÑ¥½¹}™…¥±•‰ô¤¤4(€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È ‰	¥±±¥¹œÁÉ•™±¥¡Ð™…¥±•ì¹¼‘¥…¹½ÍÑ¥Œ‘•Ñ…¥±ÌÝ•É”±½•ˆ¤™É½´9½¹”4(€€€¥˜•áÁ•Ñ•‘}•¹Ù¥É½¹µ•¹Ð€ôô€‰µ…¥¸ˆ…¹É•Á½ÉÐ¹•Ð ‰ÁÉ½‘ÕÑ¥½¹}±¥­”ˆ¤¥Ì¹½ÐQÉÕ”è4(€€€€€€€€Œ	¥±±¥¹œµ½‘”Õ…É‘Ì‘•Á•¹½¸Ñ¡”…ÁÁ±¥…Ñ¥½¸Ì9Y%I=959PÍ•ÑÑ¥¹œ¸4(€€€€€€€€Œ‘¥…¹½ÍÑ¥Œ……¥¹ÍÐµ…¥¸µÕÍÐ¹½Ð‰±•ÍÌ„‘•Ù•±½Áµ•¹Ð±…ÍÍ¥™¥…Ñ¥½¸¸4(€€€€€€€€ŒÙ…±¥¥¹½µÁ±•Ñ”‘¥…¹½ÍÑ¥Œµ…ä¹½Ð¥¹±Õ‘”•¹Ù¥É½¹µ•¹Ð™¥•±‘Ì¸4(€€€€€€€€Œ-••À¥ÑÌ™…¥±ÕÉ”ÍÑ…Ñ”Í¼É½±±½ÕÐ…¹¹½Ðµ¥ÍÑ…­”…‰Í•¹Ðµ•Ñ…‘…Ñ„4(€€€€€€€€Œ™½È„µ…±™½Éµ•É•Á½ÉÐì½µÁ±•Ñ”¹½¸µÁÉ½‘ÕÑ¥½¸É•Á½ÉÑÌÍÑ¥±°‰±½¬¸4(€€€€€€€¥˜É•Á½ÉÐ¹•Ð ‰ÍÑ…ÑÕÌˆ¤€„ô€‰‘¥…¹½ÍÑ¥}•ÉÉ½Èˆè4(€€€€€€€€€€€É•Á½ÉÑl‰ÍÑ…ÑÕÌ‰t€ô€‰‰±½­•ˆ4(€€€€€€€É•Á½ÉÑl‰‰±½­•ÉÌ‰t€ô±¥ÍÐ¡‘¥Ð¹™É½µ­•åÌ¡l4(€€€€€€€€€€€€©É•Á½ÉÐ¹•Ð ‰‰±½­•ÉÌˆ°mt¤°€‰µ…¥¹}•¹Ù¥É½¹µ•¹Ñ}¹½Ñ}ÁÉ½‘ÕÑ¥½¹}±¥­”ˆ°4(€€€€€€€t¤¤4(€€€É½±±½ÕÑ}Í…™”€ô…±Í”4(€€€¥˜ÁÕÉÁ½Í”€ôô€‰É½±±½ÕÐˆè4(€€€€€€€ÑÉäè4(€€€€€€€€€€€…ÍÍ•ÍÍµ•¹Ð€ôÉ½±±½ÕÑ}…ÍÍ•ÍÍµ•¹Ð¡É•Á½ÉÐ°…±±½Ý}½¹™¥ÕÉ•‘}±¥Ù”õ…±±½Ý}½¹™¥ÕÉ•‘}±¥Ù”¤4(€€€€€€€•á•ÁÐá•ÁÑ¥½¸è4(€€€€€€€€€€€ÁÉ¥¹Ð¡©Í½¸¹‘ÕµÁÌ¡ì‰•á•ÕÑ¥½¹}½¹Ñ•áÐˆè½¹Ñ•áÐ°€‰ÍÑ…ÑÕÌˆè€‰•ÉÉ½Èˆ°€‰•ÉÉ½Èˆè€‰ÁÉ•™±¥¡Ñ}•á•ÕÑ¥½¹}™…¥±•‰ô¤¤4(€€€€€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È ‰	¥±±¥¹œÁÉ•™±¥¡Ð™…¥±•ì¹¼‘¥…¹½ÍÑ¥Œ‘•Ñ…¥±ÌÝ•É”±½•ˆ¤™É½´9½¹”4(€€€€€€€¥˜É•ÍÕ±Ð¹É•ÑÕÉ¹½‘”€ôô€Èè4(€€€€€€€€€€€…ÍÍ•ÍÍµ•¹Ñl‰Í…™•}Ñ½}É½±±½ÕÐ‰t€ô…±Í”4(€€€€€€€€€€€…ÍÍ•ÍÍµ•¹Ñl‰É•…Í½¹Ì‰t€ô±¥ÍÐ¡‘¥Ð¹™É½µ­•åÌ¡l4(€€€€€€€€€€€€€€€€©…ÍÍ•ÍÍµ•¹Ñl‰É•…Í½¹Ì‰t°€‰É½±±½ÕÑ}‘¥…¹½ÍÑ¥Í}¥¹½µÁ±•Ñ”ˆ°4(€€€€€€€€€€€t¤¤4(€€€€€€€É•Á½ÉÑl‰É½±±½ÕÑ}Í…™•Ñä‰t€ô…ÍÍ•ÍÍµ•¹Ð4(€€€€€€€É½±±½ÕÑ}Í…™”€ô…ÍÍ•ÍÍµ•¹Ñl‰Í…™•}Ñ½}É½±±½ÕÐ‰t¥ÌQÉÕ”4(€€€É•Á½ÉÑl‰•á•ÕÑ¥½¹}½¹Ñ•áÐ‰t€ô½¹Ñ•áÐ4(€€€¥˜ÁÕÉÁ½Í”€ôô€‰É½±±½ÕÐˆè4(€€€€€€€€ŒAÕ‰±¥ŒÝ½É­™±½Ü±½Ì¹••½¹±äÑ¡”‘•¥Í¥½¸°¹½Ð½Á•É…Ñ¥½¹…°…½Õ¹Ð4(€€€€€€€€Œ½Õ¹ÑÌ°…Ñ…±½œ½¹™¥ÕÉ…Ñ¥½¸°½ÈÉ•‘•¹Ñ¥…°µÁÉ•Í•¹”µ•Ñ…‘…Ñ„¸4(€€€€€€€ÁÉ¥¹Ð¡©Í½¸¹‘ÕµÁÌ¡ì‰•á•ÕÑ¥½¹}½¹Ñ•áÐˆè½¹Ñ•áÐ°€‰É½±±½ÕÑ}Í…™•Ñäˆè…ÍÍ•ÍÍµ•¹Ñô°Í½ÉÑ}­•åÌõQÉÕ”¤¤4(€€€•±Í”è4(€€€€€€€ÁÉ¥¹Ð¡©Í½¸¹‘ÕµÁÌ¡É•Á½ÉÐ°Í½ÉÑ}­•åÌõQÉÕ”¤¤4(€€€¥˜ÁÕÉÁ½Í”€ôô€‰É½±±½ÕÐˆ…¹É½±±½ÕÑ}Í…™”è4(€€€€€€€É•ÑÕÉ¸4(€€€¥˜ÁÕÉÁ½Í”€ôô€‰É½±±½ÕÐˆ½ÈÉ•ÍÕ±Ð¹É•ÑÕÉ¹½‘”½ÈÉ•Á½ÉÐ¹•Ð ‰ÍÑ…ÑÕÌˆ¤€„ô€‰É•…‘äˆè4(€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È ‰	¥±±¥¹œÁÉ•™±¥¡ÐÉ•ÅÕ¥É•ÌÉ•Ù¥•ÜìÍ•”Ñ¡”É•‘…Ñ•)M=8É•Á½ÉÐˆ¤4(4(4)½Á•É…Ñ¥½¹Í}…ÁÀ¹™Õ¹Ñ¥½¸¡¥µ…”õµ¥É…Ñ•}¥µ…”°Í•É•ÑÌõ}Í•É•ÑÌ°Ñ¥µ•½ÕÐôäÀÀ¤4)‘•˜Íå¹}Ñ•µÁ±…Ñ•Ì ¤€´ø9½¹”è4(€€€€ˆˆ‰I•½¹¥±”Ñ¡”ÁÉ½‘ÕÑ¥½¸Ñ•µÁ±…Ñ”…Ñ…±½œÝ¥Ñ Ñ¡”Í½ÕÉ”µ½Ý¹•Í••™¥±•Ì¸ˆˆˆ4(€€€¥µÁ½ÉÐÍÕ‰ÁÉ½•ÍÌ4(4(€€€É•ÍÕ±Ð€ôÍÕ‰ÁÉ½•ÍÌ¹ÉÕ¸ 4(€€€€€€€l‰ÁåÑ¡½¸ˆ°€ˆµ´ˆ°€‰…ÁÀ¹ÍÉ¥ÁÑÌ¹Í••‘}Ñ•µÁ±…Ñ•Ì‰t°4(€€€€€€€Ýôˆ½‰…­•¹ˆ°4(€€€€€€€…ÁÑÕÉ•}½ÕÑÁÕÐõQÉÕ”°4(€€€€€€€Ñ•áÐõQÉÕ”°4(€€€€¤4(€€€ÁÉ¥¹Ð¡É•ÍÕ±Ð¹ÍÑ‘½ÕÐ¤4(€€€¥˜É•ÍÕ±Ð¹É•ÑÕÉ¹½‘”€„ô€Àè4(€€€€€€€ÁÉ¥¹Ð¡É•ÍÕ±Ð¹ÍÑ‘•ÉÈ¤4(€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È¡˜‰Ñ•µÁ±…Ñ”Íå¹¡É½¹¥é…Ñ¥½¸™…¥±•Ý¥Ñ ½‘”íÉ•ÍÕ±Ð¹É•ÑÕÉ¹½‘•ôˆ¤4(4(4(Œ€´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´4(Œ…ÍÑA$M$•¹‘Á½¥¹Ð4(Œ€´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´4(4(4)…ÁÀ¹™Õ¹Ñ¥½¸ 4(€€€¥µ…”õ…Á¥}¥µ…”°4(€€€Í•É•ÑÌõ}…Á¥}Í•É•ÑÌ°4(€€€µ¥¹}½¹Ñ…¥¹•ÉÌôÄ°4(€€€Ñ¥µ•½ÕÐôÌØÀÀ°4(€€€Í…±•‘½Ý¹}Ý¥¹‘½ÜôÌÀÀ°4(¤4)µ½‘…°¹½¹ÕÉÉ•¹Ð¡µ…á}¥¹ÁÕÑÌôÄÀÀ¤4)µ½‘…°¹…Í¥}…ÁÀ ¤4)‘•˜™…ÍÑ…Á¥}…ÁÀ ¤è4(€€€€Œ5½‘…°Í•ÉÙ•ÌÑ¡¥ÌM$…ÁÀÑ¡É½Õ ¥ÑÌµ…¹…•¥¹É•ÍÌÉ…Ñ¡•ÈÑ¡…¸4(€€€€ŒUÙ¥½É¸°Í¼UÙ¥½É¸Ì€´µÝÌµµ…àµÍ¥é•€½ÁÑ¥½¸¥Ì¹½Ð…ÁÁ±¥…‰±”¡•É”¸4(€€€€ŒQ¡”©½‰Ì½½±±…‰½É…Ñ¥½¸¡…¹‘±•ÉÌÉ•Ñ…¥¸Ñ¡•¥È€ØÐ-¥¼ÈÔØ-¥…ÁÀµ±•Ù•°4(€€€€ŒÁÉ½Ñ½½°‰½Õ¹‘Ì‰•™½É”Á…ÉÍ¥¹œ½ÈÉ•±…å¥¹œ™É…µ•Ì¸4(€€€¥µÁ½ÉÐÍåÌ4(4(€€€ÍåÌ¹Á…Ñ ¹¥¹Í•ÉÐ À°€ˆ½‰…­•¹ˆ¤4(€€€™É½´…ÁÀ¹µ…¥¸¥µÁ½ÉÐ…ÁÀ…Ì}…ÁÀ4(4(€€€É•ÑÕÉ¸}…ÁÀ4(