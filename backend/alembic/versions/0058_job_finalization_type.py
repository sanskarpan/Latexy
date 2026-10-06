"""Add a durable job-type discriminator for terminal recovery.

Revision ID: 0058
Revises: 0057
"""

import sqlalchemy as sa

from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_finalizations",
        sa.Column("job_type", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_job_finalizations_job_type",
        "job_finalizations",
        ["job_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_finalizations_job_type", table_name="job_finalizations")
    op.drop_column("job_finalizations", "job_type")
