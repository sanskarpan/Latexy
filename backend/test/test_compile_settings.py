"""Tests for Feature 38 — Compiler Settings per Resume."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.resume_routes import ALLOWED_LATEXMK_FLAGS, ResumeSettingsUpdate
from app.workers.latex_worker import _inject_packages

# ── ResumeSettingsUpdate validation ──────────────────────────────────────────


class TestResumeSettingsValidation:
    """Unit tests for ResumeSettingsUpdate validators."""

    def test_latexmk_flags_injection_rejected(self):
        """Flags with injection attempts are rejected with 422."""
        with pytest.raises(Exception):
            ResumeSettingsUpdate(latexmk_flags=["--shell-escape; rm -rf /"])

    def test_latexmk_unknown_flag_rejected(self):
        """Any flag not in the whitelist is rejected."""
        with pytest.raises(Exception):
            ResumeSettingsUpdate(latexmk_flags=["--unknown-flag"])

    def test_latexmk_allowed_flags_accepted(self):
        """All flags from the whitelist are accepted."""
        body = ResumeSettingsUpdate(latexmk_flags=ALLOWED_LATEXMK_FLAGS)
        assert body.latexmk_flags == ALLOWED_LATEXMK_FLAGS

    def test_main_file_path_traversal_rejected(self):
        """Path traversal attempts in main_file are rejected."""
        with pytest.raises(Exception):
            ResumeSettingsUpdate(main_file="../../etc/passwd")

    def test_main_file_directory_separator_rejected(self):
        """Slashes in main_file are rejected."""
        with pytest.raises(Exception):
            ResumeSettingsUpdate(main_file="subdir/main.tex")

    def test_main_file_valid_accepted(self):
        """Valid main_file names are accepted."""
        body = ResumeSettingsUpdate(main_file="my-resume_v2.tex")
        assert body.main_file == "my-resume_v2.tex"

    def test_main_file_default_resume_accepted(self):
        """The default 'resume.tex' filename is accepted."""
        body = ResumeSettingsUpdate(main_file="resume.tex")
        assert body.main_file == "resume.tex"

    def test_texlive_version_2023_accepted(self):
        """A valid 4-digit TeX Live year is accepted and stored correctly."""
        body = ResumeSettingsUpdate(texlive_version="2023")
        assert body.texlive_version == "2023"

    def test_texlive_version_invalid_rejected(self):
        """An invalid TeX Live version is rejected."""
        with pytest.raises(Exception):
            ResumeSettingsUpdate(texlive_version="2020")

    def test_texlive_version_arbitrary_string_rejected(self):
        """Arbitrary strings for texlive_version are rejected."""
        with pytest.raises(Exception):
            ResumeSettingsUpdate(texlive_version="latest; rm -rf /")

    def test_extra_packages_valid_accepted(self):
        """Valid package names are accepted."""
        body = ResumeSettingsUpdate(extra_packages=["xcolor", "multicol", "fontawesome5"])
        assert body.extra_packages == ["xcolor", "multicol", "fontawesome5"]

    def test_extra_packages_too_long_rejected(self):
        """Package names exceeding 50 chars are rejected."""
        with pytest.raises(Exception):
            ResumeSettingsUpdate(extra_packages=["a" * 51])

    def test_extra_packages_special_chars_rejected(self):
        """Package names with special characters are rejected."""
        with pytest.raises(Exception):
            ResumeSettingsUpdate(extra_packages=["xcolor; rm -rf /"])

    def test_extra_packages_underscore_rejected(self):
        """Underscores in package names are rejected (only alphanum + hyphens)."""
        with pytest.raises(Exception):
            ResumeSettingsUpdate(extra_packages=["my_package"])

    def test_none_fields_accepted(self):
        """All-None body is valid (no-op update)."""
        body = ResumeSettingsUpdate()
        assert body.compiler is None
        assert body.main_file is None
        assert body.extra_packages is None


# ── Package injection helper ──────────────────────────────────────────────────


class TestInjectPackages:
    """Unit tests for the _inject_packages worker helper."""

    BASIC_LATEX = (
        r"\documentclass{article}" + "\n"
        r"\begin{document}" + "\n"
        r"Hello" + "\n"
        r"\end{document}" + "\n"
    )

    def test_injects_missing_package(self):
        """A package not present in source is injected."""
        result = _inject_packages(self.BASIC_LATEX, ["xcolor"])
        assert r"\usepackage{xcolor}" in result

    def test_does_not_duplicate_existing_package(self):
        """A package already present is not injected again."""
        source = r"\documentclass{article}" + "\n" + r"\usepackage{xcolor}" + "\n" + r"\begin{document}" + "\n" + r"\end{document}"
        result = _inject_packages(source, ["xcolor"])
        assert result.count(r"\usepackage{xcolor}") == 1

    def test_injects_after_documentclass(self):
        r"""Packages are injected after \documentclass, not before \begin{document}."""
        result = _inject_packages(self.BASIC_LATEX, ["xcolor"])
        docclass_pos = result.index(r"\documentclass")
        package_pos = result.index(r"\usepackage{xcolor}")
        begin_pos = result.index(r"\begin{document}")
        assert docclass_pos < package_pos < begin_pos

    def test_multiple_packages_all_injected(self):
        """Multiple packages are all injected."""
        result = _inject_packages(self.BASIC_LATEX, ["xcolor", "multicol"])
        assert r"\usepackage{xcolor}" in result
        assert r"\usepackage{multicol}" in result

    def test_no_documentclass_unchanged(self):
        """Content without \\documentclass is returned unchanged."""
        content = "Hello world"
        result = _inject_packages(content, ["xcolor"])
        assert result == content

    def test_empty_package_list_unchanged(self):
        """Empty package list returns content unchanged."""
        result = _inject_packages(self.BASIC_LATEX, [])
        assert result == self.BASIC_LATEX


# ── Endpoint tests ────────────────────────────────────────────────────────────


@pytest.fixture()
def authed_client():
    """Create a TestClient with auth dependency overridden."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.middleware.auth_middleware import get_current_user_required

    app.dependency_overrides[get_current_user_required] = lambda: "test-user-id"
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.pop(get_current_user_required, None)


def _make_mock_resume(extra_meta=None):
    """Helper: return a MagicMock Resume with configurable metadata."""
    resume = MagicMock()
    resume.id = "test-resume-id"
    resume.user_id = "test-user-id"
    resume.title = "Test Resume"
    resume.latex_content = r"\documentclass{article}\begin{document}Hi\end{document}"
    resume.is_template = False
    resume.tags = []
    resume.parent_resume_id = None
    resume.variant_count = 0
    resume.resume_settings = extra_meta or {}
    resume.share_token = None
    resume.share_url = None
    resume.github_sync_enabled = False
    resume.github_repo_name = None
    resume.github_last_sync_at = None
    from datetime import datetime
    resume.created_at = datetime(2024, 1, 1)
    resume.updated_at = datetime(2024, 1, 1)
    return resume


class TestCompileSettingsEndpoint:
    """Integration-style tests for PATCH /resumes/{id}/settings."""

    def test_invalid_flag_returns_422(self, authed_client):
        """Sending an unknown latexmk flag returns 422 Unprocessable Entity."""
        resp = authed_client.patch(
            "/resumes/fake-id/settings",
            json={"latexmk_flags": ["--shell-escape; rm -rf /"]},
        )
        assert resp.status_code == 422

    def test_path_traversal_main_file_returns_422(self, authed_client):
        """Sending a path traversal main_file returns 422."""
        resp = authed_client.patch(
            "/resumes/fake-id/settings",
            json={"main_file": "../../etc/passwd"},
        )
        assert resp.status_code == 422

    def test_invalid_texlive_version_returns_422(self, authed_client):
        """Sending an invalid texlive_version returns 422."""
        resp = authed_client.patch(
            "/resumes/fake-id/settings",
            json={"texlive_version": "2020"},
        )
        assert resp.status_code == 422

    def test_valid_settings_stored_correctly(self, authed_client):
        """Valid compile settings are saved and reflected in the response."""
        from app.database.connection import get_db
        from app.main import app

        mock_resume = _make_mock_resume()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_resume

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = authed_client.patch(
                "/resumes/fake-id/settings",
                json={
                    "texlive_version": "2023",
                    "main_file": "main.tex",
                    "latexmk_flags": ["--shell-escape"],
                    "extra_packages": ["xcolor"],
                },
            )
            # Should succeed (200) — the endpoint finds the resume via mock
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_extra_packages_with_special_chars_returns_422(self, authed_client):
        """Package names with special chars are rejected before hitting the DB."""
        resp = authed_client.patch(
            "/resumes/fake-id/settings",
            json={"extra_packages": ["xcolor; rm -rf /"]},
        )
        assert resp.status_code == 422

    def test_package_name_too_long_returns_422(self, authed_client):
        """Package names exceeding 50 chars are rejected."""
        resp = authed_client.patch(
            "/resumes/fake-id/settings",
            json={"extra_packages": ["a" * 51]},
        )
        assert resp.status_code == 422
