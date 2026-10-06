"""Add immutable per-element resume version history (B52).

Revision ID: 0051
Revises: 0050
"""

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE resume_element_versions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            resume_id uuid NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
            element_key varchar(200) NOT NULL,
            element_type varchar(30) NOT NULL DEFAULT 'bullet',
            content text NOT NULL,
            content_hash varchar(64) NOT NULL,
            parent_version_id uuid REFERENCES resume_element_versions(id) ON DELETE SET NULL,
            root_version_id uuid NOT NULL,
            operation varchar(20) NOT NULL DEFAULT 'create',
            source varchar(20) NOT NULL DEFAULT 'manual',
            provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
            application_id uuid REFERENCES job_applications(id) ON DELETE SET NULL,
            idempotency_key varchar(100),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_resume_element_versions_key CHECK (element_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$'),
            CONSTRAINT ck_resume_element_versions_type CHECK (element_type IN ('bullet', 'paragraph', 'equation', 'figure', 'other')),
            CONSTRAINT ck_resume_element_versions_operation CHECK (operation IN ('create', 'edit', 'restore', 'fork')),
            CONSTRAINT ck_resume_element_versions_source CHECK (source IN ('manual', 'ai', 'import', 'restore', 'fork')),
            CONSTRAINT ck_resume_element_versions_content_size CHECK (octet_length(content) BETWEEN 1 AND 20000),
            CONSTRAINT ck_resume_element_versions_content_hash CHECK (content_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_resume_element_versions_provenance_object CHECK (jsonb_typeof(provenance) = 'object'),
            CONSTRAINT ck_resume_element_versions_provenance_size CHECK (octet_length(provenance::text) <= 4096)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_resume_element_versions_idempotency "
        "ON resume_element_versions (user_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_resume_element_versions_resume_element_created "
        "ON resume_element_versions (resume_id, element_key, created_at, id)"
    )
    op.execute(
        "CREATE INDEX ix_resume_element_versions_user_created "
        "ON resume_element_versions (user_id, created_at)"
    )
    op.execute(
        "CREATE INDEX ix_resume_element_versions_application "
        "ON resume_element_versions (application_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS resume_element_versions")
