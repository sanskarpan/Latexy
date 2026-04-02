"""add_collaboration

Revision ID: 0013_add_collaboration
Revises: 0012_add_github_integration
Create Date: 2026-04-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013_add_collaboration"
down_revision: Union[str, Sequence[str], None] = "0012_add_github_integration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "resume_collaborators" not in tables:
        op.create_table(
            "resume_collaborators",
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
            sa.Column(
                "user_id",
                sa.String,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(20), nullable=False, server_default="editor"),
            sa.Column(
                "invited_by",
                sa.String,
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "joined_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_unique_constraint(
            "uq_resume_collaborators_resume_user",
            "resume_collaborators",
            ["resume_id", "user_id"],
        )
        op.create_index(
            "idx_resume_collaborators_resume",
            "resume_collaborators",
            ["resume_id"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "resume_collaborators" in tables:
        indexes = [i["name"] for i in inspector.get_indexes("resume_collaborators")]
        if "idx_resume_collaborators_resume" in indexes:
            op.drop_index(
                "idx_resume_collaborators_resume",
                table_name="resume_collaborators",
            )
        op.drop_table("resume_collaborators")
