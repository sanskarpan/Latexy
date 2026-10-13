"""Seed exactly five D14 admission controls without replacing existing choices.

Each leaf starts enabled underneath D14 and ai_writing. Existing global, role,
family and SKU denials remain authoritative. The frozen keys/defaults here do not
follow future registry changes. No user, subscription or baseline rows are edited.
"""
import sqlalchemy as sa

from alembic import op

revision = "0073_d14_subfeatures"
down_revision = "0072_capability_roles"
branch_labels = None
depends_on = None

KEYS = ["d14_latex", "d14_table_text", "d14_table_image", "d14_math_text", "d14_math_image"]
PLAN_KEYS = ["free", "basic", "basic_annual", "pro", "pro_annual", "byok", "byok_annual", "student", "team", "weekly", "lifetime"]
ROLES = ["anonymous", "user", "support", "admin"]


def upgrade() -> None:
    conn = op.get_bind()
    for key in KEYS:
        conn.execute(sa.text(
            "INSERT INTO feature_flags (key, enabled, label, description) "
            "VALUES (:key, true, :key, 'D14 subfeature admission control') "
            "ON CONFLICT (key) DO NOTHING"
        ), {"key": key})
        for plan in PLAN_KEYS:
            conn.execute(sa.text(
                "INSERT INTO plan_features (plan_family, feature_key, enabled) "
                "VALUES (:plan, :key, true) ON CONFLICT (plan_family, feature_key) DO NOTHING"
            ), {"plan": plan, "key": key})
        for role in ROLES:
            conn.execute(sa.text(
                "INSERT INTO role_features (role, feature_key, enabled) "
                "VALUES (:role, :key, true) ON CONFLICT (role, feature_key) DO NOTHING"
            ), {"role": role, "key": key})


def downgrade() -> None:
    # Old code ignores unknown leaves. Preserve operator choices on re-upgrade.
    pass
