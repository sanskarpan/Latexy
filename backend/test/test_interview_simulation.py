"""B18.7 text-only Coach and Mock interview simulation regressions."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_routes import ResolvedAIKey
from app.services.entitlement_service import _clear_cache, entitlement_service

QUESTIONS = [
    {
        "category": "behavioral",
        "question": "Tell me about a reliability improvement you led.",
        "what_interviewer_assesses": "Ownership and measurable impact",
        "ideal_response_outline": ["Set context", "Explain action", "Quantify result"],
    },
    {
        "category": "technical",
        "question": "How would you design a resilient job queue?",
        "what_interviewer_assesses": "Tradeoffs and failure handling",
        "ideal_response_outline": ["State assumptions", "Describe retries", "Cover observability"],
    },
]


@pytest.fixture
async def simulation_prep_id(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> str:
    resume = await client.post(
        "/resumes/",
        headers=auth_headers,
        json={
            "title": "Simulation Resume",
            "latex_content": r"\documentclass{article}\begin{document}Engineer\end{document}",
        },
    )
    assert resume.status_code == 201
    token = auth_headers["Authorization"].removeprefix("Bearer ")
    user_id = (
        await db_session.execute(
            text('SELECT "userId" FROM session WHERE token = :token'), {"token": token}
        )
    ).scalar_one()
    prep_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO interview_prep "
            "(id, user_id, resume_id, questions, created_at, updated_at) "
            "VALUES (:id, :user_id, :resume_id, CAST(:questions AS jsonb), now(), now())"
        ),
        {
            "id": prep_id,
            "user_id": user_id,
            "resume_id": resume.json()["id"],
            "questions": json.dumps(QUESTIONS),
        },
    )
    await db_session.commit()
    return prep_id


def _provider_response(indexes: list[int], scores: list[int]) -> MagicMock:
    feedback = [
        {
            "question_index": index,
            "score": score,
            "strengths": ["Uses a concrete example"],
            "improvements": ["Quantify the result more clearly"],
            "suggested_outline": ["Context", "Action", "Measured result"],
        }
        for index, score in zip(indexes, scores, strict=True)
    ]
    choice = MagicMock()
    choice.message.content = json.dumps(
        {"feedback": feedback, "overall_feedback": "Grounded answers with room for specificity."}
    )
    response = MagicMock()
    response.choices = [choice]
    return response


def _ai_patches(response: MagicMock):
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return (
        patch(
            "app.api.interview_routes._resolve_ai_api_key",
            AsyncMock(return_value=ResolvedAIKey("sk-test", False)),
        ),
        patch("app.api.interview_routes._charge_ai_assist", AsyncMock(return_value=None)),
        patch("app.api.interview_routes.openai.AsyncOpenAI", return_value=client),
        client,
    )


@pytest.mark.asyncio
class TestInterviewSimulation:
    async def test_requires_auth(
        self, client: AsyncClient, simulation_prep_id: str
    ) -> None:
        response = await client.post(
            f"/interview-prep/{simulation_prep_id}/simulate",
            json={"mode": "coach", "answers": [{"question_index": 0, "answer": "x" * 20}]},
        )
        assert response.status_code == 401

    async def test_coach_mode_evaluates_one_answer_immediately(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        simulation_prep_id: str,
    ) -> None:
        resolve_patch, charge_patch, provider_patch, provider = _ai_patches(
            _provider_response([0], [84])
        )
        with resolve_patch, charge_patch, provider_patch:
            response = await client.post(
                f"/interview-prep/{simulation_prep_id}/simulate",
                headers=auth_headers,
                json={
                    "mode": "coach",
                    "answers": [{
                        "question_index": 0,
                        "answer": "I led a retry redesign that reduced failed jobs by thirty percent.",
                    }],
                },
            )
        assert response.status_code == 200
        assert response.json()["mode"] == "coach"
        assert response.json()["average_score"] == 84
        call = provider.chat.completions.create.await_args.kwargs
        supplied = json.loads(call["messages"][1]["content"])
        assert supplied["mode"] == "coach"
        assert supplied["answers"][0]["question"] == QUESTIONS[0]["question"]
        assert "Do not infer hiring outcomes" in call["messages"][0]["content"]

    async def test_mock_mode_returns_ordered_end_of_session_feedback(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        simulation_prep_id: str,
    ) -> None:
        resolve_patch, charge_patch, provider_patch, _ = _ai_patches(
            _provider_response([0, 1], [80, 91])
        )
        with resolve_patch, charge_patch, provider_patch:
            response = await client.post(
                f"/interview-prep/{simulation_prep_id}/simulate",
                headers=auth_headers,
                json={
                    "mode": "mock",
                    "answers": [
                        {"question_index": 0, "answer": "I improved reliability with measured retries."},
                        {"question_index": 1, "answer": "I use idempotency, backoff, and dead letter queues."},
                    ],
                },
            )
        assert response.status_code == 200
        assert [item["question_index"] for item in response.json()["feedback"]] == [0, 1]
        assert response.json()["average_score"] == 86

    @pytest.mark.parametrize(
        "payload",
        [
            {"mode": "unknown", "answers": [{"question_index": 0, "answer": "x" * 20}]},
            {"mode": "coach", "answers": [{"question_index": 0, "answer": "too short"}]},
            {
                "mode": "mock",
                "answers": [
                    {"question_index": 0, "answer": "x" * 20},
                    {"question_index": 0, "answer": "y" * 20},
                ],
            },
        ],
    )
    async def test_rejects_invalid_session_input(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        simulation_prep_id: str,
        payload: dict,
    ) -> None:
        response = await client.post(
            f"/interview-prep/{simulation_prep_id}/simulate",
            headers=auth_headers,
            json=payload,
        )
        assert response.status_code == 422

    async def test_rejects_question_outside_owned_session_before_ai(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        simulation_prep_id: str,
    ) -> None:
        with patch("app.api.interview_routes._resolve_ai_api_key") as resolve:
            response = await client.post(
                f"/interview-prep/{simulation_prep_id}/simulate",
                headers=auth_headers,
                json={
                    "mode": "coach",
                    "answers": [{"question_index": 9, "answer": "A sufficiently long answer."}],
                },
            )
        assert response.status_code == 422
        resolve.assert_not_called()

    async def test_malformed_provider_feedback_is_refunded(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        simulation_prep_id: str,
    ) -> None:
        malformed = _provider_response([1], [80])
        resolve_patch, _, provider_patch, _ = _ai_patches(malformed)
        with (
            resolve_patch,
            provider_patch,
            patch("app.api.interview_routes._charge_ai_assist", AsyncMock(return_value="ticket")),
            patch("app.api.interview_routes.entitlement_service.refund_quota", AsyncMock()) as refund,
        ):
            response = await client.post(
                f"/interview-prep/{simulation_prep_id}/simulate",
                headers=auth_headers,
                json={
                    "mode": "coach",
                    "answers": [{"question_index": 0, "answer": "A sufficiently detailed answer."}],
                },
            )
        assert response.status_code == 502
        refund.assert_awaited_once_with("ticket")

    async def test_no_key_reports_unavailable(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        simulation_prep_id: str,
    ) -> None:
        with patch(
            "app.api.interview_routes._resolve_ai_api_key", AsyncMock(return_value=None)
        ):
            response = await client.post(
                f"/interview-prep/{simulation_prep_id}/simulate",
                headers=auth_headers,
                json={
                    "mode": "coach",
                    "answers": [{"question_index": 0, "answer": "A sufficiently detailed answer."}],
                },
            )
        assert response.status_code == 503

    async def test_e03_live_controls_deny_recover_and_preserve_owned_prep(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        auth_headers2: dict[str, str],
        simulation_prep_id: str,
        db_session: AsyncSession,
    ) -> None:
        """Exercise the real route and entitlement DB across global, role and plan gates."""
        owner_token = auth_headers["Authorization"].removeprefix("Bearer ")
        owner_id = (
            await db_session.execute(
                text('SELECT "userId" FROM session WHERE token = :token'),
                {"token": owner_token},
            )
        ).scalar_one()
        original_identity = (
            await db_session.execute(
                text("SELECT role, subscription_plan FROM users WHERE id = :id"),
                {"id": owner_id},
            )
        ).one()

        async def saved_row(query: str, params: dict) -> tuple:
            row = (await db_session.execute(text(query), params)).one_or_none()
            assert row is not None
            return tuple(row)

        old_kill = {
            key: await saved_row(
                "SELECT enabled, updated_at FROM feature_flags WHERE key = :key",
                {"key": key},
            )
            for key in ("e02", "e03")
        }
        old_role = {
            role: await saved_row(
                "SELECT enabled, updated_at FROM role_features "
                "WHERE role = :role AND feature_key = 'e03'",
                {"role": role},
            )
            for role in ("user", "support")
        }
        old_plan = {
            plan: await saved_row(
                "SELECT enabled, updated_at FROM plan_features "
                "WHERE plan_family = :plan AND feature_key = 'e03'",
                {"plan": plan},
            )
            for plan in ("free", "pro")
        }
        payload = {
            "mode": "coach",
            "answers": [{
                "question_index": 0,
                "answer": "I led a retry redesign that reduced failed jobs by thirty percent.",
            }],
        }

        async def assert_denied_before_evaluator(headers: dict[str, str]) -> None:
            with (
                patch("app.api.interview_routes._resolve_ai_api_key", new_callable=AsyncMock) as resolve,
                patch("app.api.interview_routes._charge_ai_assist", new_callable=AsyncMock) as charge,
            ):
                denied = await client.post(
                    f"/interview-prep/{simulation_prep_id}/simulate",
                    headers=headers,
                    json=payload,
                )
            assert denied.status_code == 403, denied.text
            assert "feature_disabled" in denied.text
            assert "e03" in denied.text
            resolve.assert_not_awaited()
            charge.assert_not_awaited()

        try:
            # Normalize this synthetic account's effective baseline so the
            # denial/recovery assertions do not depend on a prior test run.
            await entitlement_service.set_role_cell("user", "e03", True, db_session)
            await entitlement_service.set_role_cell("support", "e03", True, db_session)
            await entitlement_service.set_matrix_cell("free", "e03", True, db_session)
            await entitlement_service.set_matrix_cell("pro", "e03", True, db_session)
            await db_session.execute(
                text(
                    "UPDATE users SET role = 'user', subscription_plan = 'free' "
                    "WHERE id = :id"
                ),
                {"id": owner_id},
            )
            await db_session.commit()

            # Global E03 OFF blocks new evaluation before key resolution/quota
            # admission, while the previously saved prep stays readable.
            await entitlement_service.set_kill_switch("e03", False, db_session)
            await assert_denied_before_evaluator(auth_headers)
            readable = await client.get(
                f"/interview-prep/{simulation_prep_id}", headers=auth_headers
            )
            assert readable.status_code == 200
            assert readable.json()["questions"] == QUESTIONS

            # E03 is a sibling of E02. Turning E02 off must not block a saved
            # E03 evaluation once E03 is re-enabled.
            await entitlement_service.set_kill_switch("e03", True, db_session)
            await entitlement_service.set_kill_switch("e02", False, db_session)
            resolve_patch, charge_patch, provider_patch, provider = _ai_patches(
                _provider_response([0], [84])
            )
            with resolve_patch, charge_patch, provider_patch:
                recovered = await client.post(
                    f"/interview-prep/{simulation_prep_id}/simulate",
                    headers=auth_headers,
                    json=payload,
                )
            assert recovered.status_code == 200, recovered.text
            assert recovered.json()["average_score"] == 84
            assert provider.chat.completions.create.await_count == 1

            # Role restrictions narrow access even when global and plan grants
            # remain on; changing this synthetic account to support restores it.
            await entitlement_service.set_role_cell("user", "e03", False, db_session)
            await assert_denied_before_evaluator(auth_headers)
            await entitlement_service.set_role_cell("user", "e03", True, db_session)
            await db_session.execute(
                text("UPDATE users SET role = 'support' WHERE id = :id"),
                {"id": owner_id},
            )
            await db_session.commit()

            # Prove role recovery on the still-enabled Free family before
            # introducing the separate plan-family denial below.
            with resolve_patch, charge_patch, provider_patch:
                role_recovered = await client.post(
                    f"/interview-prep/{simulation_prep_id}/simulate",
                    headers=auth_headers,
                    json=payload,
                )
            assert role_recovered.status_code == 200, role_recovered.text
            assert role_recovered.json()["average_score"] == 84
            assert provider.chat.completions.create.await_count == 2

            # A plan-family denial is independent from role and the sibling
            # capability. The same account recovers on the enabled Pro family.
            await entitlement_service.set_matrix_cell("free", "e03", False, db_session)
            await assert_denied_before_evaluator(auth_headers)
            await entitlement_service.set_matrix_cell("free", "e03", True, db_session)
            await db_session.execute(
                text("UPDATE users SET subscription_plan = 'pro' WHERE id = :id"),
                {"id": owner_id},
            )
            await db_session.commit()
            with resolve_patch, charge_patch, provider_patch:
                planned = await client.post(
                    f"/interview-prep/{simulation_prep_id}/simulate",
                    headers=auth_headers,
                    json=payload,
                )
            assert planned.status_code == 200, planned.text
            assert provider.chat.completions.create.await_count == 3

            # Another ordinary synthetic user cannot evaluate an owner's prep;
            # the ownership 404 precedes key resolution and provider use.
            with patch(
                "app.api.interview_routes._resolve_ai_api_key", new_callable=AsyncMock
            ) as resolve:
                foreign = await client.post(
                    f"/interview-prep/{simulation_prep_id}/simulate",
                    headers=auth_headers2,
                    json=payload,
                )
            assert foreign.status_code == 404
            resolve.assert_not_awaited()

            # Evaluation answers are transient, and recovery reads/deletes
            # remain available after the simulation has completed.
            reread = await client.get(
                f"/interview-prep/{simulation_prep_id}", headers=auth_headers
            )
            assert reread.status_code == 200
            assert reread.json()["questions"] == QUESTIONS
            assert payload["answers"][0]["answer"] not in reread.text
            deleted = await client.delete(
                f"/interview-prep/{simulation_prep_id}", headers=auth_headers
            )
            assert deleted.status_code == 204
            missing = await client.get(
                f"/interview-prep/{simulation_prep_id}", headers=auth_headers
            )
            assert missing.status_code == 404
        finally:
            for key, (enabled, updated_at) in old_kill.items():
                await db_session.execute(
                    text(
                        "UPDATE feature_flags SET enabled = :enabled, updated_at = :updated_at "
                        "WHERE key = :key"
                    ),
                    {"key": key, "enabled": enabled, "updated_at": updated_at},
                )
            for role, (enabled, updated_at) in old_role.items():
                await db_session.execute(
                    text(
                        "UPDATE role_features SET enabled = :enabled, updated_at = :updated_at "
                        "WHERE role = :role AND feature_key = 'e03'"
                    ),
                    {"role": role, "enabled": enabled, "updated_at": updated_at},
                )
            for plan, (enabled, updated_at) in old_plan.items():
                await db_session.execute(
                    text(
                        "UPDATE plan_features SET enabled = :enabled, updated_at = :updated_at "
                        "WHERE plan_family = :plan AND feature_key = 'e03'"
                    ),
                    {"plan": plan, "enabled": enabled, "updated_at": updated_at},
                )
            await db_session.execute(
                text(
                    "UPDATE users SET role = :role, subscription_plan = :plan WHERE id = :id"
                ),
                {"id": owner_id, "role": original_identity.role, "plan": original_identity.subscription_plan},
            )
            await db_session.commit()
            _clear_cache()
