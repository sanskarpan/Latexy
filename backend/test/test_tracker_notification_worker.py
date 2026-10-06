"""Unit coverage for application-reminder and saved-search notification delivery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import UpdateBase
from sqlalchemy.sql.selectable import Select

from app.database.models import ApplicationReminder, JobAlert, JobApplication, User
from app.workers import tracker_notification_worker as worker

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def _result(rows):
    """Return the small synchronous result surface used by ``AsyncSession.execute``."""
    return SimpleNamespace(all=lambda: rows)


def _session(*result_sets, claim_exists=True):
    session = AsyncMock(spec=AsyncSession)

    remaining = list(result_sets)

    async def execute(statement):
        if isinstance(statement, UpdateBase):
            return SimpleNamespace(rowcount=1)
        if isinstance(statement, Select) and len(statement.selected_columns) == 1:
            value = "claimed" if claim_exists else None
            return SimpleNamespace(scalar_one_or_none=lambda: value)
        return _result(remaining.pop(0))

    session.execute = AsyncMock(side_effect=execute)
    return session


def _selection_queries(session):
    return [
        entry.args[0]
        for entry in session.execute.await_args_list
        if getattr(entry.args[0], "_for_update_arg", None) is not None
    ]


def _user(*, notifications=None, name="Taylor"):
    return User(
        id=str(uuid4()),
        email="taylor@example.com",
        name=name,
        email_notifications=notifications,
    )


def _application(user, *, company="Example Labs", role="Platform Engineer"):
    return JobApplication(
        id=str(uuid4()),
        user_id=user.id,
        company_name=company,
        role_title=role,
    )


def _reminder(user, application, *, remind_at, note="Follow up"):
    return ApplicationReminder(
        id=str(uuid4()),
        user_id=user.id,
        application_id=application.id,
        remind_at=remind_at,
        note=note,
    )


def _alert(user, *, frequency="daily", created_at=None, last_notified_at=None):
    return JobAlert(
        id=str(uuid4()),
        user_id=user.id,
        query="backend engineer",
        source_url="https://jobs.example.test/search?q=backend",
        frequency=frequency,
        active=True,
        created_at=created_at or NOW - timedelta(days=10),
        last_notified_at=last_notified_at,
    )


async def _deliver(session, sender):
    return await worker.deliver_tracker_notifications(
        session,
        now=NOW,
        send_email=sender,
    )


@pytest.mark.asyncio
async def test_due_reminder_is_sent_but_future_reminder_is_not_selected():
    user = _user()
    application = _application(user)
    due = _reminder(user, application, remind_at=NOW - timedelta(minutes=1))
    future = _reminder(user, application, remind_at=NOW + timedelta(minutes=1))
    sender = AsyncMock(return_value=True)
    # This models the rows returned by the database's remind_at <= now predicate.
    session = _session([(due, application, user)], [])

    counts = await _deliver(session, sender)

    assert counts == {"reminders": 1, "alerts": 0, "failed": 0}
    assert due.sent_at == NOW
    assert future.sent_at is None
    sender.assert_awaited_once()
    assert sender.await_args.args[0] == user.email
    assert "Platform Engineer" in sender.await_args.args[2]

    reminder_query = _selection_queries(session)[0]
    sql = str(reminder_query.compile(dialect=postgresql.dialect()))
    assert "application_reminders.remind_at <=" in sql
    assert "application_reminders.sent_at IS NULL" in sql


@pytest.mark.asyncio
async def test_daily_and_weekly_alerts_are_sent_only_when_their_intervals_are_due():
    user = _user()
    daily_due = _alert(user, frequency="daily", last_notified_at=NOW - timedelta(days=1))
    weekly_due = _alert(user, frequency="weekly", last_notified_at=NOW - timedelta(days=7))
    daily_future = _alert(user, frequency="daily", last_notified_at=NOW - timedelta(hours=23))
    weekly_future = _alert(user, frequency="weekly", last_notified_at=NOW - timedelta(days=6, hours=23))
    sender = AsyncMock(return_value=True)
    # As above, rows not satisfying the interval predicate are absent from the DB result.
    session = _session(
        [],
        [(daily_due, user), (weekly_due, user)],
    )

    counts = await _deliver(session, sender)

    assert counts == {"reminders": 0, "alerts": 2, "failed": 0}
    assert daily_due.last_notified_at == NOW
    assert weekly_due.last_notified_at == NOW
    assert daily_future.last_notified_at == NOW - timedelta(hours=23)
    assert weekly_future.last_notified_at == NOW - timedelta(days=6, hours=23)
    assert sender.await_count == 2
    subjects = [call.args[1] for call in sender.await_args_list]
    assert subjects == ["Review your saved job search", "Review your saved job search"]

    alert_query = _selection_queries(session)[1]
    sql = str(alert_query.compile(dialect=postgresql.dialect()))
    assert "job_alerts.active IS true" in sql
    assert "job_alerts.last_notified_at" in sql
    assert "job_alerts.frequency" in sql


@pytest.mark.asyncio
async def test_never_notified_old_alert_is_due_from_creation_time():
    user = _user()
    alert = _alert(user, frequency="weekly", created_at=NOW - timedelta(days=8))
    sender = AsyncMock(return_value=True)
    session = _session([], [(alert, user)])

    counts = await _deliver(session, sender)

    assert counts["alerts"] == 1
    assert alert.last_notified_at == NOW
    assert sender.await_count == 1


@pytest.mark.asyncio
async def test_tracker_opt_out_suppresses_delivery_and_consumes_due_rows():
    user = _user(notifications={"tracker_updates": False})
    application = _application(user)
    reminder = _reminder(user, application, remind_at=NOW - timedelta(days=1))
    alert = _alert(user, frequency="daily", last_notified_at=NOW - timedelta(days=2))
    sender = AsyncMock(return_value=True)
    session = _session([(reminder, application, user)], [(alert, user)])

    counts = await _deliver(session, sender)

    assert counts == {"reminders": 0, "alerts": 0, "failed": 0}
    assert reminder.sent_at == NOW
    assert alert.last_notified_at == NOW
    sender.assert_not_awaited()
    # A claim and each terminal state transition are committed independently.
    assert session.commit.await_count == 4


@pytest.mark.asyncio
async def test_missing_tracker_preferences_default_to_opted_in():
    user = _user(notifications=None)
    application = _application(user)
    reminder = _reminder(user, application, remind_at=NOW - timedelta(minutes=1))
    sender = AsyncMock(return_value=True)
    session = _session([(reminder, application, user)], [])

    counts = await _deliver(session, sender)

    assert counts["reminders"] == 1
    sender.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_failure_leaves_reminder_retryable_and_does_not_claim_success():
    user = _user()
    application = _application(user)
    reminder = _reminder(user, application, remind_at=NOW - timedelta(minutes=1))
    sender = AsyncMock(return_value=False)
    session = _session([(reminder, application, user)], [])

    counts = await _deliver(session, sender)

    assert counts == {"reminders": 0, "alerts": 0, "failed": 1}
    assert reminder.sent_at is None
    sender.assert_awaited_once()
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_claim_is_durable_before_send_and_attempt_is_incremented():
    user = _user()
    application = _application(user)
    reminder = _reminder(user, application, remind_at=NOW - timedelta(minutes=1))
    sender = AsyncMock(return_value=True)
    session = _session([(reminder, application, user)], [])

    async def send_and_observe(*args, **kwargs):
        assert reminder.delivery_claimed_at == NOW
        assert reminder.delivery_claim_token
        assert reminder.delivery_attempts == 1
        assert session.commit.await_count == 1
        assert kwargs["idempotency_key"] == f"latexy-tracker-reminder:{reminder.id}"
        return True

    sender.side_effect = send_and_observe
    counts = await _deliver(session, sender)

    assert counts["reminders"] == 1
    assert reminder.delivery_claimed_at is None
    assert reminder.delivery_claim_token is None
    assert reminder.delivery_attempts == 1


@pytest.mark.asyncio
async def test_stale_claim_is_selected_and_fresh_claim_is_excluded():
    user = _user()
    application = _application(user)
    stale = _reminder(user, application, remind_at=NOW - timedelta(minutes=1))
    stale.delivery_claimed_at = NOW - worker.CLAIM_TTL - timedelta(seconds=1)
    fresh = _reminder(user, application, remind_at=NOW - timedelta(minutes=1))
    fresh.delivery_claimed_at = NOW - timedelta(minutes=1)
    sender = AsyncMock(return_value=True)
    session = _session([(stale, application, user)], [])

    await _deliver(session, sender)

    query = _selection_queries(session)[0]
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "application_reminders.delivery_claimed_at IS NULL" in sql
    assert "application_reminders.delivery_claimed_at <=" in sql
    assert fresh.sent_at is None
    sender.assert_awaited_once()


@pytest.mark.asyncio
async def test_lost_claim_cannot_finalize_another_workers_delivery():
    user = _user()
    application = _application(user)
    reminder = _reminder(user, application, remind_at=NOW - timedelta(minutes=1))
    reminder.delivery_claim_token = "old-worker-token"
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=0))

    finalized = await worker._persist_delivery_state(session, reminder, sent_at=NOW)

    assert finalized is False
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
    assert reminder.sent_at is None


@pytest.mark.asyncio
async def test_invalidated_claim_is_rechecked_before_provider_call():
    user = _user()
    application = _application(user)
    reminder = _reminder(user, application, remind_at=NOW - timedelta(minutes=1))
    sender = AsyncMock(return_value=True)
    # Simulates an API edit clearing the token after the worker's claim commit.
    session = _session([(reminder, application, user)], [], claim_exists=False)

    counts = await _deliver(session, sender)

    assert counts == {"reminders": 0, "alerts": 0, "failed": 0}
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivated_alert_is_rechecked_before_provider_call():
    user = _user()
    alert = _alert(user, frequency="daily", last_notified_at=NOW - timedelta(days=2))
    sender = AsyncMock(return_value=True)
    session = _session([], [(alert, user)], claim_exists=False)

    counts = await _deliver(session, sender)

    assert counts == {"reminders": 0, "alerts": 0, "failed": 0}
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_failure_leaves_alert_retryable_on_next_delivery():
    user = _user()
    alert = _alert(user, frequency="daily", last_notified_at=NOW - timedelta(days=2))
    sender = AsyncMock(return_value=False)
    session = _session([], [(alert, user)], [], [(alert, user)])

    first = await _deliver(session, sender)
    second = await _deliver(session, sender)

    assert first["failed"] == 1
    assert second["failed"] == 1
    assert alert.last_notified_at == NOW - timedelta(days=2)
    assert sender.await_count == 2


@pytest.mark.asyncio
async def test_successful_delivery_is_state_transitioned_once_when_next_query_is_empty():
    user = _user()
    application = _application(user)
    reminder = _reminder(user, application, remind_at=NOW - timedelta(minutes=1))
    sender = AsyncMock(return_value=True)
    # A subsequent transaction sees sent_at and therefore does not send again.
    session = _session([(reminder, application, user)], [], [], [])

    first = await _deliver(session, sender)
    second = await _deliver(session, sender)

    assert first["reminders"] == 1
    assert second == {"reminders": 0, "alerts": 0, "failed": 0}
    assert reminder.sent_at == NOW
    sender.assert_awaited_once()


@pytest.mark.asyncio
async def test_each_selection_uses_skip_locked_row_lock_for_duplicate_suppression():
    user = _user()
    application = _application(user)
    reminder = _reminder(user, application, remind_at=NOW - timedelta(minutes=1))
    sender = AsyncMock(return_value=True)
    session = _session([(reminder, application, user)], [])

    await _deliver(session, sender)

    reminder_query, alert_query = _selection_queries(session)
    for query in (reminder_query, alert_query):
        lock = query._for_update_arg
        assert lock is not None
        assert lock.skip_locked is True


def test_reminder_body_escapes_all_user_controlled_html_fields():
    user = _user(name='<img src=x onerror="alert(1)">')
    application = _application(user, company='<script>alert("company")</script>', role="R&D <lead>")
    reminder = _reminder(user, application, remind_at=NOW, note="<b>private & unsafe</b>")

    html, text = worker._reminder_bodies(user, application, reminder)

    assert '<img src=x onerror="alert(1)">' not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "&lt;script&gt;alert(&quot;company&quot;)&lt;/script&gt;" in html
    assert "R&amp;D &lt;lead&gt;" in html
    assert "&lt;b&gt;private &amp; unsafe&lt;/b&gt;" in html
    # Plain text remains readable and is never treated as an HTML document.
    assert "<b>private & unsafe</b>" in text


def test_alert_body_escapes_query_and_attribute_url_and_discloses_non_aggregator_behavior():
    user = _user(name="A < B")
    alert = _alert(user)
    alert.query = '<backend> & "senior"'
    alert.source_url = 'https://jobs.example.test/search?q=x" onmouseover="alert(1)&page=2'

    html, text = worker._alert_bodies(user, alert)

    assert "&lt;backend&gt; &amp; &quot;senior&quot;" in html
    assert 'onmouseover="alert(1)' not in html
    assert "&quot; onmouseover= &quot;" not in html
    assert "Latexy does not scrape this source or claim that new jobs were found." in html
    assert "Latexy does not scrape this source or claim that new jobs were found." in text
    assert alert.query in text
    assert alert.source_url in text
