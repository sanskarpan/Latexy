"""Add saved jobs, alerts, reminders, interview records, and contacts CRM.

Revision ID: 0045
Revises: 0044
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def _identity() -> list[sa.Column]:
    return [
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "saved_jobs",
        *_identity(),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("role_title", sa.String(200), nullable=False),
        sa.Column("job_url", sa.String(500)),
        sa.Column("job_description_text", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "job_alerts",
        *_identity(),
        sa.Column("query", sa.String(300), nullable=False),
        sa.Column("company_name", sa.String(200)),
        sa.Column("location", sa.String(200)),
        sa.Column("source_url", sa.String(500), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False, server_default="daily"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_notified_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_claimed_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_claim_token", sa.String(64)),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivery_last_error", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "application_reminders",
        *_identity(),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("job_applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(1000)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_claimed_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_claim_token", sa.String(64)),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivery_last_error", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "application_interviews",
        *_identity(),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("job_applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round_name", sa.String(200), nullable=False),
        sa.Column("interview_format", sa.String(30), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("timezone", sa.String(100), nullable=False, server_default="UTC"),
        sa.Column("location", sa.String(500)),
        sa.Column("interviewers", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "tracker_companies",
        *_identity(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("website", sa.String(500)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_tracker_company_user_name"),
    )
    op.create_table(
        "tracker_contacts",
        *_identity(),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tracker_companies.id", ondelete="SET NULL"),
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("role_title", sa.String(200)),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(100)),
        sa.Column("linkedin_url", sa.String(500)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for table in (
        "saved_jobs",
        "job_alerts",
        "application_reminders",
        "application_interviews",
        "tracker_companies",
        "tracker_contacts",
    ):
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])
    op.create_index("ix_application_reminders_application_id", "application_reminders", ["application_id"])
    op.create_index("ix_application_reminders_remind_at", "application_reminders", ["remind_at"])
    op.create_index("ix_application_interviews_application_id", "application_interviews", ["application_id"])
    op.create_index("ix_application_interviews_starts_at", "application_interviews", ["starts_at"])
    op.create_index("ix_tracker_contacts_company_id", "tracker_contacts", ["company_id"])
    op.create_index("ix_saved_jobs_user_created", "saved_jobs", ["user_id", "created_at"])
    op.create_index("ix_job_alerts_user_created", "job_alerts", ["user_id", "created_at"])
    op.create_index(
        "ix_job_alerts_delivery",
        "job_alerts",
        ["active", "frequency", "last_notified_at", "delivery_claimed_at", "created_at"],
    )
    op.create_index(
        "ix_application_reminders_delivery",
        "application_reminders",
        ["sent_at", "remind_at", "delivery_claimed_at"],
    )
    op.create_index(
        "ix_application_interviews_user_start",
        "application_interviews",
        ["user_id", "starts_at"],
    )
    op.create_index("ix_tracker_contacts_user_name", "tracker_contacts", ["user_id", "name"])


def downgrade() -> None:
    for table in (
        "tracker_contacts",
        "tracker_companies",
        "application_interviews",
        "application_reminders",
        "job_alerts",
        "saved_jobs",
    ):
        op.drop_table(table)
