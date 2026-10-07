"""Retain original PDFs privately until explicit supported-template adaptation."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("resume_pdf_imports",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resume_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("resumes.id", ondelete="CASCADE"), nullable=True, unique=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("original_pdf", sa.LargeBinary(), nullable=False),
        sa.Column("structured_seed", postgresql.JSONB(), nullable=False),
        sa.Column("extraction_status", sa.String(16), nullable=False),
        sa.Column("adaptation_sha256", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("size_bytes > 0 AND size_bytes <= 10485760", name="ck_pdf_import_size"),
        sa.CheckConstraint("octet_length(original_pdf) = size_bytes", name="ck_pdf_import_bytes"),
        sa.CheckConstraint("octet_length(structured_seed::text) <= 1048576", name="ck_pdf_import_seed"),
    )
    op.create_index("ix_resume_pdf_imports_user_id", "resume_pdf_imports", ["user_id"])
    op.create_index("ix_resume_pdf_imports_expires_at", "resume_pdf_imports", ["expires_at"])


def downgrade():
    op.drop_table("resume_pdf_imports")
