"""Keep candidate acceptance distinct after ephemeral job/run ledger expiry."""
import sqlalchemy as sa

from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("compilations", sa.Column("artifact_branch", sa.String(16), nullable=False, server_default="draft"))
    op.add_column("compilations", sa.Column("artifact_accepted", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_check_constraint("ck_compilation_artifact_branch", "compilations", "artifact_branch IN ('draft','candidate')")


def downgrade():
    op.drop_constraint("ck_compilation_artifact_branch", "compilations", type_="check")
    op.drop_column("compilations", "artifact_accepted")
    op.drop_column("compilations", "artifact_branch")
