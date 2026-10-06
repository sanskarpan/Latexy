"""Unit coverage for the B50d durable state contract."""

import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


def test_public_status_exposes_provider_acceptance_without_private_fields():
    from app.services.document_delivery_service import public_status

    delivery = SimpleNamespace(
        id="delivery-1",
        status="accepted",
        attempts=1,
        accepted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        recipient_email="owner@example.com",
        provider_message_id="provider-secret-id",
        last_error=None,
    )
    assert public_status(delivery) == {
        "id": "delivery-1",
        "status": "accepted",
        "attempts": 1,
        "retryable": False,
        "accepted_at": "2026-01-02T00:00:00+00:00",
    }
    assert "recipient_email" not in public_status(delivery)
    assert "provider_message_id" not in public_status(delivery)


@pytest.mark.asyncio
async def test_failed_provider_attempt_remains_retryable_until_max_attempts():
    from app.services.document_delivery_service import mark_failed

    delivery = SimpleNamespace(
        attempts=1,
        status="processing",
        next_attempt_at=None,
        claimed_at="claim",
        claim_token="token",
        last_error=None,
    )
    db = SimpleNamespace(commit=lambda: None)
    # AsyncSession.commit is awaited by the service; keep this tiny fake free
    # of SQLAlchemy/database dependencies.
    async def commit():
        return None
    db.commit = commit
    await mark_failed(db, delivery, "provider_rejected")
    assert delivery.status == "pending"
    assert delivery.last_error == "provider_rejected"
    assert delivery.claimed_at is None
    assert delivery.claim_token is None
    assert delivery.next_attempt_at is not None


@pytest.mark.asyncio
async def test_idempotency_key_changes_when_verified_recipient_changes():
    from app.services.document_delivery_service import get_or_create_delivery

    class Result:
        def scalar_one_or_none(self):
            return None

    class FakeDB:
        def __init__(self):
            self.added = []

        async def execute(self, _statement):
            return Result()

        def add(self, value):
            self.added.append(value)

        async def flush(self):
            return None

    first_db = FakeDB()
    second_db = FakeDB()
    first = await get_or_create_delivery(
        first_db,
        user_id="user-1",
        resume_id="resume-1",
        compilation_id="compilation-1",
        recipient_email="old@example.com",
    )
    second = await get_or_create_delivery(
        second_db,
        user_id="user-1",
        resume_id="resume-1",
        compilation_id="compilation-1",
        recipient_email="new@example.com",
    )
    assert first.idempotency_key != second.idempotency_key


@pytest.mark.asyncio
async def test_claim_token_cas_does_not_finalize_a_stolen_delivery():
    from app.services.document_delivery_service import mark_accepted

    class Result:
        rowcount = 0

    class FakeDB:
        async def execute(self, _statement):
            return Result()

        async def rollback(self):
            return None

        async def commit(self):
            raise AssertionError("stolen claim must not commit a final state")

    delivery = SimpleNamespace(id="delivery-1", status="processing", claim_token="old-token")
    assert await mark_accepted(FakeDB(), delivery, claim_token="old-token") is False


@pytest.mark.asyncio
async def test_claim_query_can_reclaim_a_stale_processing_row():
    from app.services.document_delivery_service import claim_delivery

    class Result:
        def scalar_one_or_none(self):
            return None

    class FakeDB:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            return Result()

        async def commit(self):
            return None

    db = FakeDB()
    assert await claim_delivery(db, "delivery-1") is None
    assert len(db.statements) == 1
    # The processing branch is the recovery path for a worker crash after its
    # claim was committed; without it CLAIM_TTL could never be reached.
    assert "processing" in str(db.statements[0].compile().params.values())


def test_recovery_worker_is_bound_to_original_compilation():
    from app.workers.email_worker import _async_send_document_email_delivery

    source = inspect.getsource(_async_send_document_email_delivery)
    assert "if not delivery.compilation_id" in source
    assert "compilation_id=str(delivery.compilation_id)" in source
