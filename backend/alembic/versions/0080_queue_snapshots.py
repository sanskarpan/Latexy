"""Periodic Celery queue snapshots for admin operations.

One row per sampled queue per sampling tick. The sampler (Celery Beat's
``sample_queue_depths``) records pending depth, the age of the oldest pending
message, and cumulative enqueue/completion totals so the admin operations view
can surface depth, age and throughput. Rows are operational metadata only —
never job payloads or Redis credentials — and are pruned on a bounded window
by the sampler itself.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0080_queue_snapshots"
down_revision = "0079_tenant_domain_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "celery_queue_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("queue", sa.String(64), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("oldest_age_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "enqueued_total",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "completed_total",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "sampled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("depth >= 0", name="ck_queue_snapshots_depth"),
        sa.CheckConstraint(
            "oldest_age_seconds IS NULL OR oldest_age_seconds >= 0",
            name="ck_queue_snapshots_age",
        ),
    )
    op.create_index(
        "idx_queue_snapshots_queue_sampled",
        "celery_queue_snapshots",
        ["queue", "sampled_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_queue_snapshots_queue_sampled", table_name="celery_queue_snapshots"
    )
    op.drop_table("celery_queue_snapshots")
