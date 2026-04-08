"""add_resume_views

Revision ID: 0014_add_resume_views
Revises: 0013_add_collaboration
Create Date: 2026-04-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_add_resume_views"
down_revision: Union[str, Sequence[str], None] = "0013_add_collaboration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "resume_views" not in tables:
        op.create_table(
            "resume_views",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=False),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "resume_id",
                postgresql.UUID(as_uuid=False),
                sa.ForeignKey("resumes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("share_token", sa.Text(), nullable=False),
            sa.Column(
                "viewed_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("country_code", sa.String(2), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("referrer", sa.Text(), nullable=True),
            # hash(ip+ua) for debounce — NOT stored raw
            sa.Column("session_id", sa.Text(), nullable=True),
        )

    # Always reconcile indexes — create if missing regardless of table creation above
    existing_indexes = {i["name"] for i in inspector.get_indexes("resume_views")} if "resume_views" in tables or True else set()
    # Re-inspect after potential table creation
    existing_indexes = {i["name"] for i in sa.inspect(conn).get_indexes("resume_views")}
    if "idx_resume_views_resume_id" not in existing_indexes:
        op.create_index("idx_resume_views_resume_id", "resume_views", ["resume_id"])
    if "idx_resume_views_viewed_at" not in existing_indexes:
        op.create_index("idx_resume_views_viewed_at", "resume_views", ["viewed_at"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "resume_views" in tables:
        existing_indexes = {i["name"] for i in inspector.get_indexes("resume_views")}
        for idx in ("idx_resume_views_resume_id", "idx_resume_views_viewed_at"):
            if idx in existing_indexes:
                op.drop_index(idx, table_name="resume_views")
        op.drop_table("resume_views")
