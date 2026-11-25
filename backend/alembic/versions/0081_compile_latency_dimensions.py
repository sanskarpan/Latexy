"""Persist aggregate compile-latency dimensions on compilation rows.

Plan family, compiler and template id are captured at admission from
server-side user/résumé settings. They are intentionally nullable: rows
created before this migration, guest/developer jobs without a résumé, and
jobs with no selected template cannot be retroactively attributed. The admin
latency rollup reports those gaps explicitly instead of guessing.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0081_compile_latency_dimensions"
down_revision = "0080_queue_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "compilations",
        sa.Column("plan_family", sa.String(32), nullable=True),
    )
    op.add_column(
        "compilations",
        sa.Column("compiler", sa.String(32), nullable=True),
    )
    op.add_column(
        "compilations",
        sa.Column("template_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.create_index(
        "ix_compilations_plan_family", "compilations", ["plan_family"]
    )
    op.create_index("ix_compilations_compiler", "compilations", ["compiler"])
    op.create_index(
        "ix_compilations_template_id", "compilations", ["template_id"]
    )
    op.create_index(
        "idx_compilations_latency_created",
        "compilations",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_compilations_latency_created", table_name="compilations"
    )
    op.drop_index("ix_compilations_template_id", table_name="compilations")
    op.drop_index("ix_compilations_compiler", table_name="compilations")
    op.drop_index("ix_compilations_plan_family", table_name="compilations")
    op.drop_column("compilations", "template_id")
    op.drop_column("compilations", "compiler")
    op.drop_column("compilations", "plan_family")
