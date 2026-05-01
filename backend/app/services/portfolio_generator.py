"""
Portfolio Generator Service (Feature 68).

Renders a resume + user profile into a self-contained HTML portfolio page
and stores it in MinIO under ``portfolio/{user_id}/{resume_id}/index.html``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader

from ..core.logging import get_logger
from . import storage_service

if TYPE_CHECKING:
    from ..database.models import Resume, User

logger = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "portfolio"

_VALID_THEMES = frozenset({"minimal", "dark", "professional"})


class PortfolioGenerator:
    """Generate a static HTML portfolio page from a resume + user profile."""

    def __init__(self) -> None:
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=True,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        resume: "Resume",
        user: "User",
        theme: str = "minimal",
    ) -> str:
        """
        Render the portfolio template, upload to MinIO, and return the public URL.

        Returns the public path ``/portfolio/{user_id}/{resume_id}/index.html``
        (served via MinIO presigned URL or a reverse-proxy rewrite in production).
        """
        if theme not in _VALID_THEMES:
            theme = "minimal"

        html = self._render(resume, user, theme)
        key = f"portfolio/{user.id}/{resume.id}/index.html"

        try:
            storage_service.upload_bytes(key, html.encode(), content_type="text/html")
            logger.info("Portfolio uploaded: %s", key)
        except Exception as exc:
            logger.warning("MinIO upload failed for %s: %s", key, exc)
            # Return a data URI fallback so the endpoint is still usable in
            # environments without MinIO (e.g. local dev without Docker).
            import base64
            data_uri = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
            return data_uri

        # Generate a presigned URL (1-hour TTL by default)
        try:
            url = storage_service.generate_presigned_url(key, ttl=3600)
            return url
        except Exception:
            return f"/portfolio/{user.id}/{resume.id}/index.html"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _render(self, resume: "Resume", user: "User", theme: str) -> str:
        template_name = f"{theme}.html.j2"
        # Fall back to minimal if the theme template is missing
        try:
            template = self._jinja_env.get_template(template_name)
        except Exception:
            template = self._jinja_env.get_template("minimal.html.j2")

        return template.render(
            username=user.public_username or user.id,
            name=user.name,
            tagline=user.portfolio_tagline,
            theme=theme,
            resumes=[resume],
        )


portfolio_generator = PortfolioGenerator()
