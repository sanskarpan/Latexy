"""Classify refund versus goodwill requests and retain reviewer evidence.

Revision ID: 0104_refund_requests
Revises: 0100_daily_metrics
Create Date: 2026-11-27
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0104_refund_requests"
down_revision = "0103_abuse_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admin_refund_requests",
        sa.Column(
            "request_kind",
            sa.String(length=16),
            nullable=False,
            server_default="refund",
        ),
    )
    op.add_column("admin_refund_requests", sa.Column("evidence", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_admin_refund_request_kind",
        "admin_refund_requests",
        "request_kind IN ('refund', 'goodwill')",
    )


def downgrade() -> None:
    # Evidence may be the only record of why money left the business. Refuse a
    # destructive downgrade once a request carries it rather than silently
    # discarding financial-review context.
    bind = op.get_bind()
    has_evidence = bool(
        bind.execute(
            sa.text(
                "SELECT 1 FROM admin_refund_requests "
                "WHERE evidence IS NOT NULL AND btrim(evidence) <> '' LIMIT 1"
            )
        ).scalar_one_or_none()
    )
    if has_evidence:
        raise RuntimeError(
            "cannot downgrade refund requests while reviewer evidence is retained"
        )
    op.drop_constraint(
        "ck_admin_refund_request_kind", "admin_refund_requests", type_="check"
    )
    op.drop_column("admin_refund_requests", "evidence")
    op.drop_column("admin_refund_requests", "request_kind")
