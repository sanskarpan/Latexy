"""Bounded persistent IDs for source-authoritative imported resume fields."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("resumes", sa.Column("imported_projection", postgresql.JSONB(), nullable=True))
    op.create_check_constraint("ck_resumes_imported_projection_bounded", "resumes",
                               "imported_projection IS NULL OR octet_length(imported_projection::text) <= 131072")


def downgrade():
    op.drop_constraint("ck_resumes_imported_projection_bounded", "resumes", type_="check")
    op.drop_column("resumes", "imported_projection")
