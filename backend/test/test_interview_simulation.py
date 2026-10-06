"""B18.7 text-only Coach and Mock interview simulation regressions."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_routes import ResolvedAIKey

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

