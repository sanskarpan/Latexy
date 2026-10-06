"""Concurrency and authorization tests for server-authoritative suggestions."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.database.connection import get_db
from app.main import app


def _decision_body(expected: str, *, suggestion_id: str = "peer-a:suggestion-1") -> dict:
    return {
        "suggestion_id": suggestion_id,
        "status": "accepted",
        "expected_content": expected,
        "original_text": "Target",
        "replacement_text": "Changed",
        "prefix": "Before ",
        "suffix": " After",
    }


@pytest.mark.asyncio
class TestSuggestionDecisions:
    async def test_decision_actor_fk_preserves_tombstone_on_account_delete(self):
        from app.database.models import ResumeSuggestionDecision

        column = ResumeSuggestionDecision.__table__.c.decided_by_user_id
        foreign_key = next(iter(column.foreign_keys))
        assert column.nullable is True
        assert foreign_key.ondelete == "SET NULL"

    async def _make_resume(self, client, auth_headers, content="Before Target After"):
        response = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "Suggestion concurrency", "latex_content": content},
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    async def test_accept_is_atomic_and_replayable(self, client, auth_headers):
        resume_id = await self._make_resume(client, auth_headers)
        body = _decision_body("Before Target After")

        first = await client.post(
            f"/resumes/{resume_id}/suggestion-decisions",
            headers=auth_headers,
            json=body,
        )
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "accepted"
        assert first.json()["latex_content"] == "Before Changed After"
        assert first.json()["replayed"] is False

        replay = await client.post(
            f"/resumes/{resume_id}/suggestion-decisions",
            headers=auth_headers,
            json=body,
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["replayed"] is True
        assert replay.json()["latex_content"] == "Before Changed After"

        current = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert current.status_code == 200
        assert current.json()["latex_content"] == "Before Changed After"

    async def test_concurrent_accepts_apply_at_most_once(self, client, auth_headers, db_session_factory):
        resume_id = await self._make_resume(client, auth_headers)
        body = _decision_body("Before Target After", suggestion_id="peer-a:suggestion-race")

        # The shared fixture session is convenient for most API tests but
        # cannot model production concurrency. Give each request its own
        # transaction so PostgreSQL's SELECT .. FOR UPDATE is exercised.
        async def independent_db():
            async with db_session_factory() as session:
                yield session

        previous_override = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_db] = independent_db
        try:
            responses = await asyncio.gather(
                client.post(f"/resumes/{resume_id}/suggestion-decisions", headers=auth_headers, json=body),
                client.post(f"/resumes/{resume_id}/suggestion-decisions", headers=auth_headers, json=body),
            )
        finally:
            if previous_override is None:
                app.dependency_overrides.pop(get_db, None)
            else:
                app.dependency_overrides[get_db] = previous_override

        statuses = [response.status_code for response in responses]
        assert statuses == [200, 200], [r.text for r in responses]
        assert sorted(response.json()["replayed"] for response in responses) == [False, True]
        assert {response.json()["latex_content"] for response in responses} == {"Before Changed After"}

        current = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert current.json()["latex_content"] == "Before Changed After"

    async def test_expected_source_mismatch_leaves_decision_pending(self, client, auth_headers):
        resume_id = await self._make_resume(client, auth_headers, "Before Other After")
        response = await client.post(
            f"/resumes/{resume_id}/suggestion-decisions",
            headers=auth_headers,
            json=_decision_body("Before Target After", suggestion_id="peer-a:suggestion-stale"),
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "document_changed"

        current = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert current.json()["latex_content"] == "Before Other After"

    async def test_accepts_one_exact_occurrence_without_surrounding_context(self, client, auth_headers):
        resume_id = await self._make_resume(client, auth_headers, "Target")
        response = await client.post(
            f"/resumes/{resume_id}/suggestion-decisions",
            headers=auth_headers,
            json={
                **_decision_body("Target", suggestion_id="peer-a:whole-document"),
                "prefix": "",
                "suffix": "",
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["latex_content"] == "Changed"

    async def test_recent_rejected_decisions_do_not_copy_source_and_feed_rate_limit(self, client, auth_headers, db_session):
        resume_id = await self._make_resume(client, auth_headers)
        for index in range(25):
            response = await client.post(
                f"/resumes/{resume_id}/suggestion-decisions",
                headers=auth_headers,
                json={
                    **_decision_body("Before Target After", suggestion_id=f"peer-a:reject-{index}"),
                    "status": "rejected",
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["latex_content"] == ""

        count = (
            await db_session.execute(
                text("SELECT count(*) FROM resume_suggestion_decisions WHERE resume_id = :resume_id"),
                {"resume_id": resume_id},
            )
        ).scalar_one()
        # Recent rows are intentionally retained through the one-hour limiter
        # window; otherwise pruning to 20 would make the quota bypassable.
        assert count == 25

    async def test_old_acceptance_is_a_tombstone_not_a_second_mutation(self, client, auth_headers, db_session):
        resume_id = await self._make_resume(client, auth_headers)
        source = "Before Target After"
        first_body = _decision_body(source, suggestion_id="peer-a:accepted-0")

        for index in range(21):
            original = "Target" if index == 0 else f"Changed{index - 1}"
            prefix = "Before "
            suffix = " After"
            response = await client.post(
                f"/resumes/{resume_id}/suggestion-decisions",
                headers=auth_headers,
                json={
                    "suggestion_id": f"peer-a:accepted-{index}",
                    "status": "accepted",
                    "expected_content": source,
                    "original_text": original,
                    "replacement_text": f"Changed{index}",
                    "prefix": prefix,
                    "suffix": suffix,
                },
            )
            assert response.status_code == 200, response.text
            source = response.json()["latex_content"]

        # The first full result is compacted, but its immutable ID remains.
        row = (
            await db_session.execute(
                text(
                    "SELECT result_content FROM resume_suggestion_decisions "
                    "WHERE resume_id = :resume_id AND suggestion_id = :suggestion_id"
                ),
                {"resume_id": resume_id, "suggestion_id": "peer-a:accepted-0"},
            )
        ).one()
        assert row.result_content == ""

        replay = await client.post(
            f"/resumes/{resume_id}/suggestion-decisions",
            headers=auth_headers,
            json=first_body,
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["replayed"] is True
        assert replay.json()["replay_available"] is False
        assert replay.json()["latex_content"] == source

        current = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert current.json()["latex_content"] == source

    async def test_new_decision_ids_are_rate_limited_per_user_and_resume(self, client, auth_headers):
        resume_id = await self._make_resume(client, auth_headers)
        with patch("app.api.suggestion_routes.MAX_DECISIONS_PER_USER_RESUME_PER_HOUR", 2):
            for index in range(2):
                response = await client.post(
                    f"/resumes/{resume_id}/suggestion-decisions",
                    headers=auth_headers,
                    json={
                        **_decision_body("Before Target After", suggestion_id=f"peer-a:rate-{index}"),
                        "status": "rejected",
                    },
                )
                assert response.status_code == 200, response.text

            limited = await client.post(
                f"/resumes/{resume_id}/suggestion-decisions",
                headers=auth_headers,
                json={
                    **_decision_body("Before Target After", suggestion_id="peer-a:rate-new"),
                    "status": "rejected",
                },
            )
            assert limited.status_code == 429, limited.text
            assert limited.json()["detail"]["code"] == "suggestion_decision_rate_limited"

            # Idempotent replay does not consume quota and remains available.
            replay = await client.post(
                f"/resumes/{resume_id}/suggestion-decisions",
                headers=auth_headers,
                json={
                    **_decision_body("Before Target After", suggestion_id="peer-a:rate-0"),
                    "status": "accepted",
                },
            )
            assert replay.status_code == 200, replay.text
            assert replay.json()["replayed"] is True

    async def test_expired_accepted_tombstones_are_cleaned_after_replay_lifetime(
        self, client, auth_headers, db_session
    ):
        resume_id = await self._make_resume(client, auth_headers)
        first = await client.post(
            f"/resumes/{resume_id}/suggestion-decisions",
            headers=auth_headers,
            json=_decision_body("Before Target After", suggestion_id="peer-a:expired-tombstone"),
        )
        assert first.status_code == 200, first.text

        # Simulate the collaboration replay lifetime elapsing. Cleanup runs
        # while the next decision holds the resume lock.
        await db_session.execute(
            text(
                "UPDATE resume_suggestion_decisions SET created_at = :created_at "
                "WHERE resume_id = :resume_id AND suggestion_id = :suggestion_id"
            ),
            {
                "created_at": datetime.now(timezone.utc) - timedelta(days=31),
                "resume_id": resume_id,
                "suggestion_id": "peer-a:expired-tombstone",
            },
        )
        await db_session.commit()
        second = await client.post(
            f"/resumes/{resume_id}/suggestion-decisions",
            headers=auth_headers,
            json={
                **_decision_body("Before Changed After", suggestion_id="peer-a:new-after-expiry"),
                "original_text": "Changed",
                "replacement_text": "Final",
            },
        )
        assert second.status_code == 200, second.text
        remaining = (
            await db_session.execute(
                text(
                    "SELECT count(*) FROM resume_suggestion_decisions "
                    "WHERE resume_id = :resume_id AND suggestion_id = :suggestion_id"
                ),
                {"resume_id": resume_id, "suggestion_id": "peer-a:expired-tombstone"},
            )
        ).scalar_one()
        assert remaining == 0

    async def test_invalid_unicode_is_rejected_as_validation_error(self, client, auth_headers):
        resume_id = await self._make_resume(client, auth_headers)
        payload = {
            **_decision_body("Before Target After", suggestion_id="peer-a:invalid-unicode"),
            "expected_content": "Before \ud800 After",
        }
        response = await client.post(
            f"/resumes/{resume_id}/suggestion-decisions",
            headers={**auth_headers, "Content-Type": "application/json"},
            content=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        )
        assert response.status_code == 422

    async def test_accepted_replacement_enforces_utf8_byte_limit(self, client, auth_headers):
        resume_id = await self._make_resume(client, auth_headers)
        with patch("app.api.suggestion_routes.MAX_LATEX_CONTENT_BYTES", 10):
            response = await client.post(
                f"/resumes/{resume_id}/suggestion-decisions",
                headers=auth_headers,
                json=_decision_body("Before Target After", suggestion_id="peer-a:byte-limit"),
            )
        assert response.status_code == 422, response.text
        assert "byte limit" in response.text

    async def test_only_editor_or_owner_can_use_authority(self, client, auth_headers, auth_headers2, db_session):
        resume_id = await self._make_resume(client, auth_headers)
        owner_token = auth_headers["Authorization"].split(" ", 1)[1]
        collaborator_token = auth_headers2["Authorization"].split(" ", 1)[1]
        owner_id = (
            await db_session.execute(
                text('SELECT "userId" FROM session WHERE token = :token'), {"token": owner_token}
            )
        ).scalar_one()
        collaborator_id = (
            await db_session.execute(
                text('SELECT "userId" FROM session WHERE token = :token'), {"token": collaborator_token}
            )
        ).scalar_one()
        await db_session.execute(
            text(
                "INSERT INTO resume_collaborators (resume_id, user_id, role, invited_by) "
                "VALUES (:resume_id, :user_id, 'commenter', :owner_id)"
            ),
            {"resume_id": resume_id, "user_id": collaborator_id, "owner_id": owner_id},
        )
        await db_session.commit()

        response = await client.post(
            f"/resumes/{resume_id}/suggestion-decisions",
            headers=auth_headers2,
            json=_decision_body("Before Target After", suggestion_id="peer-a:suggestion-denied"),
        )
        assert response.status_code == 403

    async def test_commenter_can_confirm_owner_decision(self, client, auth_headers, auth_headers2, db_session):
        resume_id = await self._make_resume(client, auth_headers)
        owner_token = auth_headers["Authorization"].split(" ", 1)[1]
        commenter_token = auth_headers2["Authorization"].split(" ", 1)[1]
        owner_id = (
            await db_session.execute(
                text('SELECT "userId" FROM session WHERE token = :token'), {"token": owner_token}
            )
        ).scalar_one()
        commenter_id = (
            await db_session.execute(
                text('SELECT "userId" FROM session WHERE token = :token'), {"token": commenter_token}
            )
        ).scalar_one()
        await db_session.execute(
            text(
                "INSERT INTO resume_collaborators (resume_id, user_id, role, invited_by) "
                "VALUES (:resume_id, :user_id, 'commenter', :owner_id)"
            ),
            {"resume_id": resume_id, "user_id": commenter_id, "owner_id": owner_id},
        )
        await db_session.commit()

        resolved = await client.post(
            f"/resumes/{resume_id}/suggestion-decisions",
            headers=auth_headers,
            json=_decision_body("Before Target After", suggestion_id="peer-a:commenter-read"),
        )
        assert resolved.status_code == 200, resolved.text

        confirmed = await client.get(
            f"/resumes/{resume_id}/suggestion-decisions/peer-a:commenter-read",
            headers=auth_headers2,
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "accepted"
        assert confirmed.json()["latex_content"] == "Before Changed After"

    async def test_authorization_is_rechecked_after_resume_lock(self, client, auth_headers):
        resume_id = await self._make_resume(client, auth_headers)
        from fastapi import HTTPException

        # Simulate a collaborator revocation observed after the initial access
        # query but before the locked mutation. The route must not commit.
        with patch(
            "app.api.suggestion_routes._access_role",
            new=AsyncMock(side_effect=["editor", HTTPException(status_code=403, detail="revoked")]),
        ):
            response = await client.post(
                f"/resumes/{resume_id}/suggestion-decisions",
                headers=auth_headers,
                json=_decision_body("Before Target After", suggestion_id="peer-a:suggestion-revoked"),
            )
        assert response.status_code == 403

        current = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert current.json()["latex_content"] == "Before Target After"
