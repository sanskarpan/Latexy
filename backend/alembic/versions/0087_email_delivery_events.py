"""Persist Resend delivery, bounce and complaint evidence.

Provider message ids map webhook events back to ``document_email_deliveries``.
The event inbox is append-only and deduplicates on the signed webhook id. Only a
one-way recipient digest is stored, never the mailbox address or provider
payload. Current suppression state is mirrored separately so a hard bounce or
complaint can block a later document send without retaining the address.

Revision ID: 0087_email_delivery_events
Revises: 0086_trial_attribution
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0087_email_delivery_events"
down_revision = "0086_trial_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_delivery_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "provider",
            sa.String(length=32),
            nullable=False,
            server_default="resend",
        ),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column(
            "delivery_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("document_email_deliveries.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("recipient_hash", sa.String(length=64), nullable=True),
        sa.Column("bounce_type", sa.String(length=32), nullable=True),
        sa.Column("bounce_subtype", sa.String(length=64), nullable=True),
        sa.Column(
            "retryable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_email_delivery_events_provider_event",
        ),
    )
    op.create_index(
        "ix_email_delivery_events_provider_message",
        "email_delivery_events",
        ["provider_message_id"],
    )
    op.create_index(
        "ix_email_delivery_events_type_occurred",
        "email_delivery_events",
        ["event_type", "occurred_at"],
    )
    op.create_index(
        "ix_email_delivery_events_delivery",
        "email_delivery_events",
        ["delivery_id"],
    )
    op.create_index(
        "ix_email_delivery_events_recipient_hash",
        "email_delivery_events",
        ["recipient_hash"],
    )

    op.create_table(
        "email_recipient_suppressions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "provider",
            sa.String(length=32),
            nullable=False,
            server_default="resend",
        ),
        sa.Column("recipient_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=True),
        sa.Column(
            "delivery_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("document_email_deliveries.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "provider",
            "recipient_hash",
            name="uq_email_recipient_suppressions_provider_hash",
        ),
    )
    op.create_index(
        "ix_email_recipient_suppressions_created",
        "email_recipient_suppressions",
        ["created_at"],
    )
    op.create_index(
        "ix_email_recipient_suppressions_delivery",
        "email_recipient_suppressions",
        ["delivery_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_recipient_suppressions_delivery",
        table_name="email_recipient_suppressions",
    )
    op.drop_index(
        "ix_email_recipient_suppressions_created",
        table_name="email_recipient_suppressions",
    )
    op.drop_table("email_recipient_suppressions")
    op.drop_index(
        "ix_email_delivery_events_recipient_hash",
        table_name="email_delivery_events",
    )
    op.drop_index(
        "ix_email_delivery_events_delivery",
        table_name="email_delivery_events",
    )
    op.drop_index(
        "ix_email_delivery_events_type_occurred",
        table_name="email_delivery_events",
    )
    op.drop_index(
        "ix_email_delivery_events_provider_message",
        table_name="email_delivery_events",
    )
    op.drop_table("email_delivery_events")
