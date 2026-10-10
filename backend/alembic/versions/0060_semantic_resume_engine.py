"""Versioned semantic documents and durable optimization stages.

Revision ID: 0060
Revises: 0059
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("resumes", sa.Column("content_revision", sa.Integer(), nullable=False, server_default="1"))
    op.create_check_constraint("ck_resumes_content_revision_positive", "resumes", "content_revision > 0")
    # Every write surface, including integrations/finalization, participates.
    # structured_version remains the schema version, not an edit counter.
    op.execute("""CREATE FUNCTION latexy_resume_revision() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NEW.latex_content IS DISTINCT FROM OLD.latex_content
           OR NEW.structured_content IS DISTINCT FROM OLD.structured_content THEN
          NEW.content_revision := OLD.content_revision + 1;
        ELSE NEW.content_revision := OLD.content_revision; END IF;
        RETURN NEW;
      END $$;""")
    op.execute("""CREATE TRIGGER resumes_content_revision BEFORE UPDATE ON resumes
      FOR EACH ROW EXECUTE FUNCTION latexy_resume_revision();""")
    op.create_table("resume_optimization_runs",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("job_id", sa.String(255), sa.ForeignKey("job_finalizations.job_id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("resume_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column("effort", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("credential_scope", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="running"),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("context_payload", postgresql.JSONB(), nullable=False),
        sa.Column("budget", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("decisions", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("base_revision > 0", name="ck_optimization_run_revision"),
        sa.CheckConstraint("effort IN ('quick','standard','deep')", name="ck_optimization_run_effort"),
        sa.CheckConstraint("status IN ('running','completed','partial','failed','cancelled')", name="ck_optimization_run_status"))
    op.create_index("ix_optimization_runs_owner_resume", "resume_optimization_runs", ["user_id", "resume_id", "created_at"])
    op.create_index("ix_optimization_runs_expiry", "resume_optimization_runs", ["expires_at"])
    op.create_table("resume_optimization_stages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(255), sa.ForeignKey("resume_optimization_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_key", sa.String(128), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="requesting"),
        sa.Column("owner_token", sa.String(128), nullable=False),
        sa.Column("owner_epoch", sa.Integer(), nullable=False),
        sa.Column("reserved_usage", postgresql.JSONB(), nullable=False),
        sa.Column("usage", postgresql.JSONB(), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "stage_key", name="uq_optimization_stage_key"),
        sa.CheckConstraint("status IN ('requesting','completed','failed','ambiguous')", name="ck_optimization_stage_status"),
        sa.CheckConstraint("owner_epoch > 0", name="ck_optimization_stage_epoch"))
    op.create_table("resume_requirement_contexts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jd_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("requirements", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "jd_hash", "version", "language", name="uq_resume_requirement_context"))


def downgrade():
    op.drop_table("resume_requirement_contexts")
    op.drop_table("resume_optimization_stages")
    op.drop_index("ix_optimization_runs_expiry", table_name="resume_optimization_runs")
    op.drop_index("ix_optimization_runs_owner_resume", table_name="resume_optimization_runs")
    op.drop_table("resume_optimization_runs")
    op.execute("DROP TRIGGER resumes_content_revision ON resumes")
    op.execute("DROP FUNCTION latexy_resume_revision()")
    op.drop_constraint("ck_resumes_content_revision_positive", "resumes", type_="check")
    op.drop_column("resumes", "content_revision")
