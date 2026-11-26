"""Tenant-scoped custom-domain verification history.

Every DNS verification attempt needs an outcome and a timestamp that outlive
the tenant's current ``custom_domain`` value. The existing ``tenants`` row only
holds the latest verification timestamp, so removing or replacing a domain
erased the only evidence of what happened. This ledger keeps an allowlisted
event per attempt (verified, failed, error, removed), the hostname it applied
to and an optional error class.

Privacy
-------
The table stores a tenant UUID, a tenant-owned hostname, an allowlisted event
type and checksum-free error class, and a timestamp. It never stores a TXT
record value, DNS response payload, certificate material, user identifier or
email. History is tenant-scoped and survives domain removal; deleting the
tenant still cascades as required by data-retention policy.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0099_tenant_domain_health"
down_revision = "0097_two_person_approvals"
branch_labels = None
depends_on = None

EVENT_TYPES = ("verified", "failed", "error", "removed")
ERROR_CLASSES = ("txt_missing", "dns_unavailable")


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "tenant_domain_events",
        sa.Column(
            "id",
            sa.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("error_class", sa.String(32), nullable=True),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            _in_clause("event_type", EVENT_TYPES),
            name="ck_tenant_domain_events_event_type",
        ),
        sa.CheckConstraint(
            f"error_class IS NULL OR {_in_clause('error_class', ERROR_CLASSES)}",
            name="ck_tenant_domain_events_error_class",
        ),
    )
    op.create_index(
        "idx_tenant_domain_events_tenant_checked",
        "tenant_domain_events",
        ["tenant_id", "checked_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_tenant_domain_events_tenant_checked",
        table_name="tenant_domain_events",
    )
    op.drop_table("tenant_domain_events")
