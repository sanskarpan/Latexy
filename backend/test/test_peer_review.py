"""Security and API contract tests for anonymous peer/mentor review comments."""

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from starlette.requests import Request

from app.api.review_routes import _check_review_rate_limit
from app.database.models import Resume, ResumeReviewComment, Tenant, Workspace, WorkspaceMember, WorkspaceResume


def _allow_limiter(*_args, **_kwargs):
    return [1, 1, 1]


@pytest.mark.asyncio
class TestPeerReview:
    async def _resume_and_token(self, client, auth_headers):
        created = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={
                "title": "Review contract resume",
                "latex_content": r"\documentclass{article}\begin{document}Hello\end{document}",
            },
        )
        assert created.status_code == 201, created.text
        resume_id = created.json()["id"]
        shared = await client.post(
            f"/resumes/{resume_id}/share",
            headers=auth_headers,
            json={"review_comments": True},
        )
        assert shared.status_code == 200, shared.text
        assert shared.json()["review_comments"] is True
        # A legacy privacy update must not silently revoke the capability.
        preserved = await client.post(
            f"/resumes/{resume_id}/share",
            headers=auth_headers,
            json={"anonymous": False},
        )
        assert preserved.status_code == 200
        assert preserved.json()["review_comments"] is True
        return resume_id, shared.json()["share_token"]

    async def test_public_review_is_explicit_and_returns_no_identity_fields(
        self, client, auth_headers
    ):
        resume_id, token = await self._resume_and_token(client, auth_headers)
        response = await client.get(f"/share/{token}/review-comments")
        assert response.status_code == 200, response.text
        assert response.json() == []
        assert "latexy_review_id" in response.cookies

        with patch(
            "app.api.review_routes.redis_core.redis_cache_client",
            AsyncMock(eval=AsyncMock(side_effect=_allow_limiter)),
        ):
            created = await client.post(
                f"/share/{token}/review-comments",
                json={
                    "content": "<script>alert('xss')</script>",
                    "line_number": 12,
                    "section_tag": "Experience",
                },
            )
        assert created.status_code == 201, created.text
        payload = created.json()
        assert payload["content"] == "<script>alert('xss')</script>"
        assert payload["reviewer_label"].startswith("Reviewer ")
        assert payload["line_number"] == 12
        assert payload["section_tag"] == "Experience"
        assert payload["page_number"] is None
        assert payload["x"] is None
        assert payload["y"] is None
        assert "resume_id" not in payload
        assert "author_id" not in payload
        assert "author_email" not in payload

        listed = await client.get(f"/share/{token}/review-comments")
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == payload["id"]

    async def test_unknown_non_review_and_revoked_tokens_are_indistinguishable(
        self, client, auth_headers
    ):
        resume_id, token = await self._resume_and_token(client, auth_headers)
        unknown = await client.get(f"/share/{'a' * 32}/review-comments")
        assert unknown.status_code == 404

        # A normal share token is not a review capability.
        await client.delete(f"/resumes/{resume_id}/share", headers=auth_headers)
        normal_resume = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "Normal", "latex_content": "Hello"},
        )
        normal_id = normal_resume.json()["id"]
        normal_share = await client.post(f"/resumes/{normal_id}/share", headers=auth_headers)
        non_review = await client.get(
            f"/share/{normal_share.json()['share_token']}/review-comments"
        )
        revoked = await client.get(f"/share/{token}/review-comments")
        assert non_review.status_code == revoked.status_code == 404
        assert non_review.json()["detail"] == revoked.json()["detail"]

    async def test_revocation_blocks_creation_even_with_old_cookie(
        self, client, auth_headers
    ):
        resume_id, token = await self._resume_and_token(client, auth_headers)
        await client.get(f"/share/{token}/review-comments")
        await client.delete(f"/resumes/{resume_id}/share", headers=auth_headers)
        with patch(
            "app.api.review_routes.redis_core.redis_cache_client",
            AsyncMock(eval=AsyncMock(side_effect=_allow_limiter)),
        ):
            response = await client.post(
                f"/share/{token}/review-comments", json={"content": "still here?"}
            )
        assert response.status_code == 404

    async def test_revoke_wins_rate_limit_gap_before_public_insert(
        self, client, auth_headers, monkeypatch
    ):
        resume_id, token = await self._resume_and_token(client, auth_headers)
        reached_limiter = asyncio.Event()
        release_limiter = asyncio.Event()

        async def pause_after_capability_check(*_args, **_kwargs):
            reached_limiter.set()
            await release_limiter.wait()

        monkeypatch.setattr("app.api.review_routes._check_review_rate_limit", pause_after_capability_check)
        pending = asyncio.create_task(client.post(
            f"/share/{token}/review-comments", json={"content": "must not survive revoke"}
        ))
        await asyncio.wait_for(reached_limiter.wait(), timeout=2)
        revoked = await client.delete(f"/resumes/{resume_id}/share", headers=auth_headers)
        assert revoked.status_code == 204
        release_limiter.set()
        created = await asyncio.wait_for(pending, timeout=2)
        assert created.status_code == 404

    async def test_owner_can_list_and_editor_can_resolve_but_commenter_cannot(
        self, client, auth_headers, auth_headers2, db_session
    ):
        resume_id, token = await self._resume_and_token(client, auth_headers)
        with patch(
            "app.api.review_routes.redis_core.redis_cache_client",
            AsyncMock(eval=AsyncMock(side_effect=_allow_limiter)),
        ):
            created = await client.post(
                f"/share/{token}/review-comments", json={"content": "Please clarify this."}
            )
        assert created.status_code == 201
        comment_id = created.json()["id"]

        owner_list = await client.get(
            f"/resumes/{resume_id}/review-comments", headers=auth_headers
        )
        assert owner_list.status_code == 200
        assert owner_list.json()[0]["content"] == "Please clarify this."

        # A separate user cannot access the owner's review thread without an
        # explicit collaborator row.
        forbidden = await client.get(
            f"/resumes/{resume_id}/review-comments", headers=auth_headers2
        )
        assert forbidden.status_code == 403

        # The fixture's second user id is available from its bearer session; use
        # a direct lookup to avoid relying on any private auth helper.
        reviewer_id = (await db_session.execute(text(
            'SELECT "userId" FROM session WHERE token = :token'
        ), {"token": auth_headers2["Authorization"].split(" ", 1)[1]})).scalar_one()
        await db_session.execute(
            text(
                "INSERT INTO resume_collaborators (id, resume_id, user_id, role) VALUES (:id, :rid, :uid, 'commenter')"
            ),
            {"id": str(uuid4()), "rid": resume_id, "uid": reviewer_id},
        )
        await db_session.commit()
        commenter_resolve = await client.patch(
            f"/resumes/{resume_id}/review-comments/{comment_id}/resolve",
            headers=auth_headers2,
            json={"resolved": True},
        )
        assert commenter_resolve.status_code == 403
        owner_resolve = await client.patch(
            f"/resumes/{resume_id}/review-comments/{comment_id}/resolve",
            headers=auth_headers,
            json={"resolved": True},
        )
        assert owner_resolve.status_code == 200
        assert owner_resolve.json()["resolved"] is True
        # Replaying the same explicit state is idempotent.
        retry = await client.patch(
            f"/resumes/{resume_id}/review-comments/{comment_id}/resolve",
            headers=auth_headers,
            json={"resolved": True},
        )
        assert retry.status_code == 200
        assert retry.json()["resolved"] is True

        unresolve = await client.patch(
            f"/resumes/{resume_id}/review-comments/{comment_id}/resolve",
            headers=auth_headers,
            json={"resolved": False},
        )
        assert unresolve.status_code == 200
        assert unresolve.json()["resolved"] is False

    async def test_limits_are_atomic_and_fail_closed_on_redis_outage(
        self, client, auth_headers
    ):
        _resume_id, token = await self._resume_and_token(client, auth_headers)
        redis_client = AsyncMock(eval=AsyncMock(side_effect=RuntimeError("down")))
        with patch("app.api.review_routes.redis_core.redis_cache_client", redis_client):
            response = await client.post(
                f"/share/{token}/review-comments", json={"content": "meter me"}
            )
        assert response.status_code == 503
        assert redis_client.eval.await_count == 1

        limited = AsyncMock(eval=AsyncMock(side_effect=lambda *_args, **_kwargs: [0, 21, 0]))
        with patch("app.api.review_routes.redis_core.redis_cache_client", limited):
            response = await client.post(
                f"/share/{token}/review-comments", json={"content": "too many"}
            )
        assert response.status_code == 429

    async def test_live_capability_has_a_bounded_comment_history(
        self, client, auth_headers, monkeypatch
    ):
        _resume_id, token = await self._resume_and_token(client, auth_headers)
        with patch(
            "app.api.review_routes.redis_core.redis_cache_client",
            AsyncMock(eval=AsyncMock(side_effect=_allow_limiter)),
        ):
            first = await client.post(
                f"/share/{token}/review-comments", json={"content": "first"}
            )
            assert first.status_code == 201
            monkeypatch.setattr("app.api.review_routes._MAX_COMMENTS_PER_CAPABILITY", 1)
            second = await client.post(
                f"/share/{token}/review-comments", json={"content": "second"}
            )
        assert second.status_code == 429
        assert "comment limit" in second.json()["detail"]
        listed = await client.get(f"/share/{token}/review-comments")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

    async def test_authenticated_history_keeps_newest_window_in_chronological_order(
        self, client, auth_headers, db_session, monkeypatch
    ):
        resume_id, token = await self._resume_and_token(client, auth_headers)
        resume = await db_session.get(Resume, resume_id)
        assert resume is not None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        db_session.add_all([
            ResumeReviewComment(
                resume_id=resume_id,
                share_token_hash=token_hash,
                reviewer_label="Reviewer TEST01",
                content=f"history-{index}",
                created_at=start + timedelta(minutes=index),
                updated_at=start + timedelta(minutes=index),
            )
            for index in range(4)
        ])
        await db_session.commit()
        monkeypatch.setattr("app.api.review_routes._MAX_AUTHENTICATED_LIST", 3)
        response = await client.get(
            f"/resumes/{resume_id}/review-comments", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        assert [item["content"] for item in response.json()] == [
            "history-1", "history-2", "history-3"
        ]
        assert response.headers["X-Review-Comments-Truncated"] == "true"

    async def test_tenant_workspace_viewer_cannot_read_another_submission(
        self, client, auth_headers, auth_headers2, db_session
    ):
        resume_id, _token = await self._resume_and_token(client, auth_headers)
        owner_id = (await db_session.execute(text(
            'SELECT "userId" FROM session WHERE token = :token'
        ), {"token": auth_headers["Authorization"].split(" ", 1)[1]})).scalar_one()
        viewer_id = (await db_session.execute(text(
            'SELECT "userId" FROM session WHERE token = :token'
        ), {"token": auth_headers2["Authorization"].split(" ", 1)[1]})).scalar_one()

        tenant = Tenant(
            slug=f"test-peer-{uuid4().hex[:12]}",
            name="Peer Review Tenant",
            owner_id=owner_id,
        )
        db_session.add(tenant)
        await db_session.flush()
        workspace = Workspace(
            name="Peer Review Cohort",
            owner_id=owner_id,
            tenant_id=tenant.id,
        )
        db_session.add(workspace)
        await db_session.flush()
        db_session.add_all([
            WorkspaceMember(workspace_id=workspace.id, user_id=owner_id, role="owner"),
            WorkspaceMember(workspace_id=workspace.id, user_id=viewer_id, role="viewer"),
            WorkspaceResume(workspace_id=workspace.id, resume_id=resume_id, shared_by=owner_id),
        ])
        await db_session.commit()

        response = await client.get(
            f"/resumes/{resume_id}/review-comments",
            headers=auth_headers2,
        )
        assert response.status_code == 403

    async def test_resolve_rechecks_an_editor_after_membership_revocation(
        self, client, auth_headers, auth_headers2, db_session
    ):
        resume_id, token = await self._resume_and_token(client, auth_headers)
        with patch(
            "app.api.review_routes.redis_core.redis_cache_client",
            AsyncMock(eval=AsyncMock(side_effect=_allow_limiter)),
        ):
            created = await client.post(
                f"/share/{token}/review-comments", json={"content": "Resolve me"}
            )
        comment_id = created.json()["id"]
        reviewer_id = (await db_session.execute(text(
            'SELECT "userId" FROM session WHERE token = :token'
        ), {"token": auth_headers2["Authorization"].split(" ", 1)[1]})).scalar_one()
        await db_session.execute(text(
            "INSERT INTO resume_collaborators (id, resume_id, user_id, role) VALUES (:id, :rid, :uid, 'editor')"
        ), {"id": str(uuid4()), "rid": resume_id, "uid": reviewer_id})
        await db_session.commit()
        # Simulate an already-won revoke transaction before the resolve call.
        await db_session.execute(text(
            "DELETE FROM resume_collaborators WHERE resume_id = :rid AND user_id = :uid"
        ), {"rid": resume_id, "uid": reviewer_id})
        await db_session.commit()
        response = await client.patch(
            f"/resumes/{resume_id}/review-comments/{comment_id}/resolve",
            headers=auth_headers2,
            json={"resolved": True},
        )
        assert response.status_code == 403

    async def test_validation_rejects_bad_anchors_and_uuid_like_paths(
        self, client, auth_headers
    ):
        _resume_id, token = await self._resume_and_token(client, auth_headers)
        with patch(
            "app.api.review_routes.redis_core.redis_cache_client",
            AsyncMock(eval=AsyncMock(side_effect=_allow_limiter)),
        ):
            bad_line = await client.post(
                f"/share/{token}/review-comments",
                json={"content": "x", "line_number": 0},
            )
        assert bad_line.status_code == 422
        assert (await client.get("/share/not-a-token/review-comments")).status_code == 404

        for content in ("   ", "\n\t"):
            blank = await client.post(
                f"/share/{token}/review-comments", json={"content": content}
            )
            assert blank.status_code == 422
        # Send the JSON escape over the wire; constructing a Python string with
        # a surrogate and passing it through httpx would fail before ASGI sees
        # the request.
        surrogate = await client.post(
            f"/share/{token}/review-comments",
            content=b'{"content":"bad\\ud800"}',
            headers={"content-type": "application/json"},
        )
        assert surrogate.status_code == 422
        oversized = await client.post(
            f"/share/{token}/review-comments", json={"content": "😀" * 5_000}
        )
        assert oversized.status_code == 422

        with patch(
            "app.api.review_routes.redis_core.redis_cache_client",
            AsyncMock(eval=AsyncMock(side_effect=_allow_limiter)),
        ):
            anchored = await client.post(
                f"/share/{token}/review-comments",
                json={"content": "Move this bullet left", "page_number": 2, "x": 0.25, "y": 0.75},
            )
        assert anchored.status_code == 201, anchored.text
        anchor_payload = anchored.json()
        assert anchor_payload["page_number"] == 2
        assert anchor_payload["x"] == pytest.approx(0.25)
        assert anchor_payload["y"] == pytest.approx(0.75)

        for partial in (
            {"page_number": 1, "x": 0.2},
            {"page_number": 1, "y": 0.2},
            {"x": 0.2, "y": 0.2},
            {"page_number": 1, "x": 1.1, "y": 0.2},
            {"page_number": 1, "x": 0.2, "y": -0.1},
        ):
            invalid = await client.post(
                f"/share/{token}/review-comments",
                json={"content": "bad anchor", **partial},
            )
            assert invalid.status_code == 422, (partial, invalid.text)

    async def test_concurrent_limiter_calls_share_one_atomic_token_bucket(self):
        class AtomicFakeRedis:
            def __init__(self):
                self.lock = asyncio.Lock()
                self.token_count = 0

            async def eval(self, *_args, **_kwargs):
                async with self.lock:
                    self.token_count += 1
                    if self.token_count > 20:
                        return [0, self.token_count, 0]
                    return [1, self.token_count, self.token_count]

        fake = AtomicFakeRedis()
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/share/token/review-comments",
            "headers": [],
            "client": ("127.0.0.1", 54321),
            "scheme": "http",
        }
        request = Request(scope)
        with patch("app.api.review_routes.redis_core.redis_cache_client", fake):
            results = await asyncio.gather(
                *(_check_review_rate_limit(request, "a" * 64) for _ in range(25)),
                return_exceptions=True,
            )
        assert sum(result is None for result in results) == 20
        assert sum(getattr(result, "status_code", None) == 429 for result in results) == 5
        assert fake.token_count == 25
