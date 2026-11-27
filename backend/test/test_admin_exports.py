"""Admin CSV/PDF exports, signed downloads and scheduled digest contracts."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AdminAuditLog
from app.services import admin_export_service as exports
from app.services.admin_audit_service import AdminActor

SECRET_REASON = "private reason 2061 must never leave the audit log"
SECRET_EMAIL = "secret-reason-owner@example.com"
SECRET_IP = "203.0.113.206"
SECRET_METADATA = "private prompt/document marker 2061"


def _token_suffix() -> str:
    return uuid.uuid4().hex[:10]


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
    status: str = "active",
    verified: bool = True,
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    token = f"test_sess_export_{uuid.uuid4().hex}"
    email = f"test_export_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, :name, :role, :verified, :plan, :status, false)"
        ),
        {
            "id": user_id,
            "email": email,
            "name": "Export Fixture User",
            "role": role,
            "verified": verified,
            "plan": plan,
            "status": status,
        },
    )
    await db.execute(
        text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return user_id, {"Authorization": f"Bearer {token}"}


async def _admin(db: AsyncSession) -> tuple[str, dict[str, str], str]:
    user_id, headers = await _create_user(db, role="admin")
    email = f"test_export_{user_id.replace('-', '')}@example.com"
    return user_id, headers, email


def _parse_csv(text_body: str) -> tuple[list[dict[str, str]], list[str]]:
    rows = list(csv.reader(io.StringIO(text_body)))
    meta = [row for row in rows if row and row[0] == "#meta"]
    header_index = next(
        (index for index, row in enumerate(rows) if row and row[0] != "#meta" and row),
        len(rows),
    )
    header = rows[header_index] if header_index < len(rows) else []
    data_rows = rows[header_index + 1 :]
    records = [dict(zip(header, row, strict=False)) for row in data_rows if row]
    return records, ["".join(row) for row in meta]


async def _seed_audit(
    db: AsyncSession,
    *,
    action: str,
    created_at: datetime | None = None,
    target_type: str = "audit_fixture",
    actor_user_id: str = "export-audit-actor",
) -> str:
    audit_id = str(uuid.uuid4())
    db.add(
        AdminAuditLog(
            id=audit_id,
            actor_user_id=actor_user_id,
            actor_email=SECRET_EMAIL,
            action=action,
            target_type=target_type,
            target_id="target-2061",
            reason=SECRET_REASON,
            ip_address=SECRET_IP,
            before_state={"secret": SECRET_METADATA},
            after_state={"secret": SECRET_METADATA},
            event_metadata={"secret": SECRET_METADATA},
            created_at=created_at or datetime.now(timezone.utc) - timedelta(minutes=2),
        )
    )
    await db.commit()
    return audit_id


async def _seed_compilation(db: AsyncSession, user_id: str, *, plan: str) -> None:
    await db.execute(
        text(
            "INSERT INTO compilations (id, user_id, job_id, status, plan_family, compiler, created_at) "
            "VALUES (:id, :uid, :job, 'completed', :plan, 'pdflatex', :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "job": f"export_cap_{uuid.uuid4().hex}",
            "plan": plan,
            "created": datetime.now(timezone.utc) - timedelta(minutes=5),
        },
    )
    await db.commit()


class TestCsvContract:
    async def test_streamed_csv_embeds_metadata_and_neutralizes_formula_cells(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        plan = f"=cmd,payload-{_token_suffix()}"
        for _ in range(5):
            await _create_user(db_session, plan=plan)
        _admin_id, headers, _email = await _admin(db_session)

        response = await client.get(
            "/admin/exports/stream",
            params={"report": "users", "format": "csv", "role": "user"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        assert response.headers["cache-control"].startswith("private")
        body = response.text
        assert "#meta" in body
        assert "schema_version" in body
        assert "generated_at" in body
        assert "filters" in body
        assert "row_cap" in body
        # Formula injection is neutralized and the comma forces CSV quoting.
        assert f"\"'{plan}" in body

    async def test_get_exports_accepts_analytics_alias_and_streams_csv(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, headers, _email = await _admin(db_session)
        response = await client.get(
            "/admin/exports",
            params={"report": "analytics", "format": "csv", "days": 7},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        assert "#meta,report,overview" in response.text
        assert "#meta,days,7" in response.text

    async def test_row_cap_truncates_and_reports_it(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        action = f"audit.test.cap.{_token_suffix()}"
        for index in range(9):
            await _seed_audit(
                db_session,
                action=action,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=index + 1),
            )
        _admin_id, headers, _email = await _admin(db_session)
        monkeypatch.setattr(exports, "MAX_CSV_ROWS", 4)
        monkeypatch.setattr(exports, "AUDIT_BATCH_SIZE", 2)

        response = await client.get(
            "/admin/exports/stream",
            params={"report": "audit", "format": "csv", "action": action},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.headers["x-export-truncated"] == "true"
        records, meta = _parse_csv(response.text)
        assert any("row_cap,4" in line or "row_cap" in line for line in meta)
        assert len(records) == 4
        assert {record["action"] for record in records} == {action}

    async def test_csv_stream_is_lazy_at_the_report_layer(self, db_session: AsyncSession):
        action = f"audit.test.lazy.{_token_suffix()}"
        for index in range(5):
            await _seed_audit(
                db_session,
                action=action,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=index + 1),
            )
        spec = exports.normalize_spec(report="audit", filters={"action": action})
        prepared = await exports.prepare_report(db_session, spec)
        stream = exports.iter_report_csv(db_session, prepared)
        first = await anext(stream)
        second = await anext(stream)
        assert first.startswith("#meta")
        assert second.startswith("#meta")
        assert prepared.row_count == 5
        await stream.aclose()

    async def test_audit_export_redacts_email_ip_reason_and_payloads(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        action = f"audit.test.redaction.{_token_suffix()}"
        await _seed_audit(db_session, action=action)
        _admin_id, headers, _email = await _admin(db_session)

        response = await client.get(
            "/admin/exports/stream",
            params={"report": "audit", "format": "csv", "action": action},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        for secret in (SECRET_REASON, SECRET_EMAIL, SECRET_IP, SECRET_METADATA):
            assert secret not in response.text
        assert action in response.text
        assert "actor_ref" in response.text

    async def test_five_user_suppression_hides_metrics(self, client: AsyncClient, db_session: AsyncSession):
        plan = f"suppress_{_token_suffix()}"
        for _ in range(3):
            user_id, _headers = await _create_user(db_session, plan=plan)
            await _seed_compilation(db_session, user_id, plan=plan)
        _admin_id, headers, _email = await _admin(db_session)

        response = await client.get(
            "/admin/exports/stream",
            params={"report": "overview", "format": "csv", "plan": plan},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.headers["x-export-suppressed"] == "true"
        records, meta = _parse_csv(response.text)
        assert records == []
        assert any("suppressed,true" in line or "suppressed" in line for line in meta)


class TestSignedDownloads:
    async def test_token_is_actor_bound_tamper_evident_and_expires(
        self,
    ):
        spec = exports.normalize_spec(report="overview", export_format="csv", days=7)
        token, expires_at, export_id = exports.issue_export_token(
            spec, actor_user_id="admin-a", now=datetime.now(timezone.utc)
        )
        assert expires_at <= datetime.now(timezone.utc) + timedelta(minutes=15)
        validated, validated_id = exports.validate_export_token(token, actor_user_id="admin-a")
        assert validated.report == "overview"
        assert validated_id == export_id

        with pytest.raises(exports.AdminExportForbidden):
            exports.validate_export_token(token, actor_user_id="admin-b")

        tampered = token[:-2] + ("aa" if token[-2:] != "aa" else "bb")
        with pytest.raises(exports.AdminExportForbidden):
            exports.validate_export_token(tampered, actor_user_id="admin-a")

        with pytest.raises(exports.AdminExportForbidden):
            exports.validate_export_token(
                token,
                actor_user_id="admin-a",
                now=expires_at + timedelta(seconds=1),
            )

    async def test_create_and_download_requires_the_same_admin(self, client: AsyncClient, db_session: AsyncSession):
        _admin_id, headers, _email = await _admin(db_session)
        _other_id, other_headers, _other_email = await _admin(db_session)

        created = await client.post(
            "/admin/exports",
            json={"report": "overview", "format": "csv", "days": 7},
            headers=headers,
        )
        assert created.status_code == 200, created.text
        payload = created.json()
        assert payload["delivery"] == "signed_url"
        assert payload["download_url"].startswith("/admin/exports/download?token=")
        assert payload["metadata"]["schema_version"] == exports.REPORT_SCHEMA_VERSION
        assert payload["metadata"]["generated_at"]
        assert payload["metadata"]["filters"] == {}

        downloaded = await client.get(payload["download_url"], headers=headers)
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.headers["content-disposition"].endswith('.csv"')

        forbidden = await client.get(payload["download_url"], headers=other_headers)
        assert forbidden.status_code == 403

        tampered_url = payload["download_url"][:-2] + ("aa" if not payload["download_url"].endswith("aa") else "bb")
        tampered = await client.get(tampered_url, headers=headers)
        assert tampered.status_code == 403

    async def test_pdf_export_includes_filter_summary_and_generation_time(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, headers, _email = await _admin(db_session)
        created = await client.post(
            "/admin/exports",
            json={"report": "overview", "format": "pdf", "days": 30},
            headers=headers,
        )
        assert created.status_code == 200, created.text
        payload = created.json()
        assert payload["format"] == "pdf"
        assert payload["large_job"] is True

        downloaded = await client.get(payload["download_url"], headers=headers)
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.headers["content-type"].startswith("application/pdf")
        assert downloaded.content.startswith(b"%PDF-1.4")
        assert b"Generated at:" in downloaded.content
        assert b"Filters:" in downloaded.content
        assert b"Schema version:" in downloaded.content

    async def test_create_rejects_unknown_filter_and_inverted_range(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, headers, _email = await _admin(db_session)
        unknown = await client.post(
            "/admin/exports",
            json={"report": "overview", "format": "csv", "email": "leak@example.com"},
            headers=headers,
        )
        assert unknown.status_code == 422

        inverted = await client.post(
            "/admin/exports",
            json={
                "report": "overview",
                "format": "csv",
                "start_date": "2026-05-02",
                "end_date": "2026-05-01",
            },
            headers=headers,
        )
        assert inverted.status_code == 422


class TestExportRbacAndAudit:
    async def test_export_surfaces_are_admin_only(self, client: AsyncClient, db_session: AsyncSession):
        _user_id, user_headers = await _create_user(db_session)
        anonymous = await client.get("/admin/exports")
        assert anonymous.status_code == 401
        forbidden = await client.get("/admin/exports", headers=user_headers)
        assert forbidden.status_code == 403
        forbidden_create = await client.post(
            "/admin/exports",
            json={"report": "overview", "format": "csv"},
            headers=user_headers,
        )
        assert forbidden_create.status_code == 403
        forbidden_digest = await client.put(
            "/admin/exports/digest",
            json={"enabled": True, "reason": "admin only", "confirm": True},
            headers=user_headers,
        )
        assert forbidden_digest.status_code == 403

    async def test_history_is_scoped_to_the_requesting_admin(self, client: AsyncClient, db_session: AsyncSession):
        admin_a, headers_a, _email_a = await _admin(db_session)
        _admin_b, _headers_b, _email_b = await _admin(db_session)
        created = await client.post(
            "/admin/exports",
            json={"report": "billing", "format": "csv", "days": 7},
            headers=headers_a,
        )
        assert created.status_code == 200, created.text

        history = await client.get("/admin/exports/history", headers=headers_a)
        assert history.status_code == 200, history.text
        items = history.json()["items"]
        assert items
        assert all(item["export_id"] for item in items)
        assert any(item["metadata"].get("report") == "billing" for item in items)

        rows = (
            (
                await db_session.execute(
                    select(AdminAuditLog).where(
                        AdminAuditLog.actor_user_id == admin_a,
                        AdminAuditLog.action == exports.EXPORT_ACTIONS[0],
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows
        assert rows[-1].event_metadata["row_cap"] == exports.MAX_CSV_ROWS

    async def test_repeated_exports_are_rate_limited(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        _admin_id, headers, _email = await _admin(db_session)

        async def _deny(*_args, **_kwargs):
            return False

        monkeypatch.setattr(exports, "allow_export_request", _deny)
        response = await client.post(
            "/admin/exports",
            json={"report": "overview", "format": "csv"},
            headers=headers,
        )
        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"


class TestScheduledDigest:
    async def test_digest_update_requires_reason_confirm_and_approved_recipients(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_id, headers, _email = await _admin(db_session)
        non_admin_id, _non_admin_headers = await _create_user(db_session)

        missing_confirm = await client.put(
            "/admin/exports/digest",
            json={"enabled": True, "reason": "enable digest"},
            headers=headers,
        )
        assert missing_confirm.status_code == 422

        bad_recipient = await client.put(
            "/admin/exports/digest",
            json={
                "enabled": True,
                "reason": "enable digest",
                "confirm": True,
                "recipient_user_ids": [non_admin_id],
            },
            headers=headers,
        )
        assert bad_recipient.status_code == 422

        good = await client.put(
            "/admin/exports/digest",
            json={
                "enabled": True,
                "reason": "enable digest",
                "confirm": True,
                "recipient_user_ids": [admin_id],
                "frequency": "daily",
                "report": "overview",
                "format": "summary",
                "days": 7,
            },
            headers=headers,
        )
        assert good.status_code == 200, good.text
        body = good.json()
        assert body["enabled"] is True
        assert body["updated"] is True
        assert body["recipient_user_ids"] == [admin_id]

        repeated = await client.put(
            "/admin/exports/digest",
            json={
                "enabled": True,
                "reason": "enable digest",
                "confirm": True,
                "recipient_user_ids": [admin_id],
                "frequency": "daily",
                "report": "overview",
                "format": "summary",
                "days": 7,
            },
            headers=headers,
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["updated"] is False
        count = (
            await db_session.execute(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(
                    AdminAuditLog.actor_user_id == admin_id,
                    AdminAuditLog.action == exports.DIGEST_CONFIG_ACTION,
                )
            )
        ).scalar_one()
        assert count == 1

    async def test_digest_status_exposes_last_run_without_emails(self, client: AsyncClient, db_session: AsyncSession):
        admin_id, headers, _email = await _admin(db_session)
        status = await client.get("/admin/exports/digest", headers=headers)
        assert status.status_code == 200, status.text
        body = status.json()
        assert body["enabled"] is False
        assert body["last_run"] is None
        assert any(item["user_id"] == admin_id for item in body["available_recipients"])
        assert "@" not in status.text

    async def test_dry_run_never_sends_and_contains_no_emails(self, client: AsyncClient, db_session: AsyncSession):
        admin_id, headers, admin_email = await _admin(db_session)
        response = await client.post(
            "/admin/exports/digest/dry-run",
            json={
                "enabled": False,
                "frequency": "weekly",
                "recipient_user_ids": [admin_id],
                "report": "billing",
                "format": "summary",
                "days": 30,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["sent"] is False
        assert body["dry_run"] is True
        assert "Latexy admin digest" in body["subject"]
        assert admin_email not in body["text_body"]
        assert "@" not in body["text_body"]
        assert body["recipient_count"] == 1

        dry_runs = (
            (
                await db_session.execute(
                    select(AdminAuditLog).where(
                        AdminAuditLog.actor_user_id == admin_id,
                        AdminAuditLog.action == exports.DIGEST_DRY_RUN_ACTION,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(dry_runs) == 1

    async def test_scheduler_payload_is_due_and_aggregate_only(self, db_session: AsyncSession):
        admin_id, _headers, admin_email = await _admin(db_session)
        configured_at = datetime.now(timezone.utc) - timedelta(days=2)
        db_session.add(
            AdminAuditLog(
                id=str(uuid.uuid4()),
                actor_user_id=admin_id,
                action=exports.DIGEST_CONFIG_ACTION,
                target_type="admin_digest",
                target_id=admin_id,
                after_state={
                    "enabled": True,
                    "frequency": "daily",
                    "recipient_user_ids": [admin_id],
                    "report": "overview",
                    "format": "summary",
                    "days": 7,
                    "start_date": None,
                    "end_date": None,
                    "filters": {},
                    "schema_version": exports.REPORT_SCHEMA_VERSION,
                },
                event_metadata={"enabled": True, "frequency": "daily"},
                created_at=configured_at,
            )
        )
        await db_session.commit()

        due = await exports.due_digest_configs(db_session, now=datetime.now(timezone.utc))
        assert any(owner == admin_id for owner, _config, _row in due)
        config = next(config for owner, config, _row in due if owner == admin_id)
        actor = AdminActor(user_id=admin_id, email=None, role="admin")
        payload = await exports.build_digest_payload(db_session, actor=actor, config=config)
        assert payload["recipient_user_ids"] == [admin_id]
        assert admin_email not in payload["text_body"]
        assert admin_email not in payload["html_body"]
        assert payload["metadata"]["schema_version"] == exports.REPORT_SCHEMA_VERSION
        assert payload["metadata"]["row_cap"] == exports.MAX_PDF_ROWS

    async def test_send_digest_uses_only_approved_admin_addresses_and_audits(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        admin_id, headers, admin_email = await _admin(db_session)
        good = await client.put(
            "/admin/exports/digest",
            json={
                "enabled": True,
                "reason": "enable digest",
                "confirm": True,
                "recipient_user_ids": [admin_id],
                "frequency": "daily",
                "report": "overview",
                "format": "summary",
                "days": 7,
            },
            headers=headers,
        )
        assert good.status_code == 200, good.text
        config = await exports.load_digest_config(db_session, AdminActor(user_id=admin_id, email=None, role="admin"))

        sent_to: list[str] = []
        bodies: list[str] = []

        async def _fake_send(**kwargs):
            sent_to.append(kwargs["to"])
            bodies.append(kwargs["text_body"])
            return True

        monkeypatch.setattr(exports.email_service, "send_email", _fake_send)
        result = await exports.send_digest(
            db_session,
            actor=AdminActor(user_id=admin_id, email=None, role="admin"),
            config=config,
        )
        assert result["status"] == "sent"
        assert result["delivered"] == 1
        assert sent_to == [admin_email]
        assert admin_email not in bodies[0]

        runs = (
            (
                await db_session.execute(
                    select(AdminAuditLog).where(
                        AdminAuditLog.actor_user_id == admin_id,
                        AdminAuditLog.action == exports.DIGEST_SENT_ACTION,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(runs) == 1
        assert runs[0].event_metadata["delivered_count"] == 1
        assert "email" not in (runs[0].event_metadata or {})

    async def test_send_digest_records_failure_when_no_approved_recipient(self, db_session: AsyncSession):
        admin_id, _headers, _email = await _admin(db_session)
        actor = AdminActor(user_id=admin_id, email=None, role="admin")
        config = exports.DigestConfig(
            enabled=True,
            frequency="daily",
            recipient_user_ids=("not-a-user-id",),
            report="overview",
            format="summary",
            days=7,
            start_date=None,
            end_date=None,
            filters={},
        )
        result = await exports.send_digest(db_session, actor=actor, config=config)
        assert result["status"] == "failed"
        assert result["error_class"] == "no_approved_recipients"

        failures = (
            (
                await db_session.execute(
                    select(AdminAuditLog).where(
                        AdminAuditLog.actor_user_id == admin_id,
                        AdminAuditLog.action == exports.DIGEST_FAILED_ACTION,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(failures) == 1
        assert failures[0].event_metadata["error_class"] == "no_approved_recipients"

    async def test_digest_task_and_beat_entry_are_registered(self):
        from app.core.celery_app import celery_app
        from app.workers.email_worker import send_admin_digests

        assert hasattr(send_admin_digests, "apply_async")
        assert "admin-digest-dispatch" in (celery_app.conf.beat_schedule or {})
        assert (
            celery_app.conf.beat_schedule["admin-digest-dispatch"]["task"]
            == "app.workers.email_worker.send_admin_digests"
        )


class TestPdfRenderer:
    def test_pdf_is_well_formed_and_embeds_metadata(self):
        spec = exports.normalize_spec(report="billing", export_format="pdf", days=7, filters={"status": "active"})
        prepared = exports.PreparedReport(
            spec=spec,
            headers=exports._csv_headers("billing"),
            generated_at=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            row_count=1,
            rows=[
                [
                    "subscriptions",
                    "pro",
                    "active",
                    "",
                    6,
                    "",
                    6,
                    "2026-05-01",
                    "2026-05-01",
                    "2026-05-01T12:00:00+00:00",
                    "1",
                ]
            ],
            suppressed=False,
            truncated=False,
            notes=exports._billing_notes(),
        )
        pdf = exports.render_report_pdf(prepared)
        assert pdf.startswith(b"%PDF-1.4")
        assert b"startxref" in pdf
        assert b"%%EOF" in pdf
        assert b"Generated at: 2026-05-01T12:00:00+00:00" in pdf
        assert b'Filters: {"status":"active"}' in pdf
        assert b"Schema version: 1" in pdf

        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf)) as document:
            assert len(document.pages) == 1
            text = document.pages[0].extract_text() or ""
        assert "Latexy admin export" in text
        assert "Generated at: 2026-05-01T12:00:00+00:00" in text
        assert "Filters:" in text


def test_safe_csv_cell_handles_all_formula_prefixes():
    for value in ("=1+1", "+SUM(A1)", "-2+3", "@cmd", "\tdata", "\rdata", " =1+1", "\ufeff@cmd"):
        assert exports.safe_csv_cell(value).startswith("'")
    assert exports.safe_csv_cell("safe") == "safe"
    assert exports.safe_csv_cell(42) == 42
