"""Add resume_templates table

Revision ID: 0004_add_resume_templates
Revises: 0003_model_fixes
Create Date: 2026-03-12
"""

from alembic import op

revision = "0004_add_resume_templates"
down_revision = "0003_model_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS resume_templates (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            name        TEXT        NOT NULL,
            description TEXT,
            category    TEXT        NOT NULL,
            tags        TEXT[]      NOT NULL DEFAULT '{}',
            thumbnail_url TEXT,
            latex_content TEXT      NOT NULL,
            is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
            sort_order  INTEGER     NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_templates_category ON resume_templates(category);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_templates_active   ON resume_templates(is_active);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_templates_sort     ON resume_templates(category, sort_order);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_templates_sort;")
    op.execute("DROP INDEX IF EXISTS idx_templates_active;")
    op.execute("DROP INDEX IF EXISTS idx_templates_category;")
    op.execute("DROP TABLE IF EXISTS resume_templates;")
