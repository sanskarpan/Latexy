"""Add team seat and coupon tables for Feature 32.

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "team_seats",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "owner_user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("member_email", sa.Text(), nullable=False),
        sa.Column(
            "member_user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="invited"),
        sa.Column(
            "invited_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("owner_user_id", "member_email", name="uq_team_seats_owner_email"),
    )
    op.create_index("ix_team_seats_owner_user_id", "team_seats", ["owner_user_id"])

    op.create_table(
        "coupon_codes",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("discount_percent", sa.Integer(), nullable=False),
        sa.Column("applicable_plans", ARRAY(sa.String()), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint("uq_coupon_codes_code", "coupon_codes", ["code"])

    op.create_table(
        "coupon_redemptions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "coupon_id",
            UUID(as_uuid=False),
            sa.ForeignKey("coupon_codes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_coupon_redemptions_user_id", "coupon_redemptions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_coupon_redemptions_user_id", table_name="coupon_redemptions")
    op.drop_table("coupon_redemptions")
    op.drop_constraint("uq_coupon_codes_code", "coupon_codes", type_="unique")
    op.drop_table("coupon_codes")
    op.drop_index("ix_team_seats_owner_user_id", table_name="team_seats")
    op.drop_table("team_seats")
