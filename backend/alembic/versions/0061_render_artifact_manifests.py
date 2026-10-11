"""Durable immutable renderer references and bounded retention.

Revision ID: 0061
Revises: 0060
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("render_artifact_manifests",
        sa.Column("artifact_id", sa.String(64), primary_key=True),
        sa.Column("job_id", sa.String(255), sa.ForeignKey("job_finalizations.job_id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_epoch", sa.Integer(), nullable=False),
        sa.Column("owner_token_sha256", sa.String(64), nullable=False),
        sa.Column("owner_scope_kind", sa.String(8), nullable=False),
        sa.Column("manifest_key", sa.String(500), nullable=False),
        sa.Column("pdf_key", sa.String(500), nullable=False),
        sa.Column("synctex_key", sa.String(500)), sa.Column("geometry_key", sa.String(500)),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("owner_epoch > 0", name="ck_render_manifest_epoch"),
        sa.CheckConstraint("owner_scope_kind IN ('user','device')", name="ck_render_manifest_scope"))
    for field in ("job_id", "manifest_key", "pdf_key", "synctex_key", "geometry_key", "expires_at"):
        op.create_index("ix_render_artifact_manifests_" + field, "render_artifact_manifests", [field])


def downgrade():
    op.drop_table("render_artifact_manifests")
