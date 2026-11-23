"""Custom-domain expiry metadata for the operations attention queue.

The columns are nullable because the DNS/certificate automation that will
populate them is external to the application. A null value means "unknown",
never "expires never"; the attention view reports that distinction explicitly.
"""

import sqlalchemy as sa

from alembic import op

revision = "0079_tenant_domain_expiry"
down_revision = "0078_admin_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("domain_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("domain_certificate_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "domain_certificate_expires_at")
    op.drop_column("tenants", "domain_expires_at")
