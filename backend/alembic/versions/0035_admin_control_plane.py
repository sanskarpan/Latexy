"""Admin Control Plane: RBAC role, plan_features matrix, feature kill-switch seed.

Adds the data layer for the Admin Control Plane:
- users.role (RBAC): user | support | admin.
- plan_features (per-plan feature matrix): (plan_family, feature_key) -> enabled.
- Data seed: launch default = every gateable feature enabled for every plan family.
- feature_flags kill-switch row per gateable feature (inserted only if absent —
  the 6 pre-existing operational flags are left untouched).

Revision ID: 0035
Revises: 0034
Create Date: 2026-07-25
"""

import sqlalchemy as sa

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


# Launch catalog (mirrors feature_registry). "compile" is NOT gateable — excluded.
PLAN_FAMILIES = ["free", "basic", "pro", "byok", "team"]
GATEABLE_KEYS = [
    "llm_optimize",
    "ats_score",
    "ats_deep",
    "resume_builder",
    "cover_letters",
    "batch_tailor",
    "templates",
    "exports",
    "ai_writing",
    "macros",
    "snippets",
    "career_paths",
    "interview_prep",
    "application_tracker",
    "one_click_apply",
    "byok",
    "collaboration",
    "team_workspaces",
    "portfolio",
    "developer_api",
    "references",
    "integration_github",
    "integration_dropbox",
    "integration_zotero",
    "integration_mendeley",
    "analytics",
]


def _title_case(key: str) -> str:
    return key.replace("_", " ").title()


def upgrade() -> None:
    # RBAC: add users.role (default 'user').
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=20), nullable=False, server_default="user"),
    )

    # Per-plan feature matrix.
    op.create_table(
        "plan_features",
        sa.Column("plan_family", sa.String(length=20), nullable=False),
        sa.Column("feature_key", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("plan_family", "feature_key"),
    )

    # Seed: every (family x gateable feature) enabled (launch default = all on).
    plan_features = sa.table(
        "plan_features",
        sa.column("plan_family", sa.String),
        sa.column("feature_key", sa.String),
        sa.column("enabled", sa.Boolean),
    )
    rows = [
        {"plan_family": family, "feature_key": key, "enabled": True}
        for family in PLAN_FAMILIES
        for key in GATEABLE_KEYS
    ]
    op.bulk_insert(plan_features, rows)

    # Seed: one kill-switch row per gateable feature in feature_flags, only if the
    # key is not already present (the 6 operational flags must stay untouched).
    conn = op.get_bind()
    insert_flag = sa.text(
        """
        INSERT INTO feature_flags (key, enabled, label, description)
        VALUES (:key, true, :label, 'Feature kill-switch')
        ON CONFLICT (key) DO NOTHING
        """
    )
    for key in GATEABLE_KEYS:
        conn.execute(insert_flag, {"key": key, "label": _title_case(key)})


def downgrade() -> None:
    # Remove only the kill-switch rows we inserted (gateable feature keys).
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM feature_flags WHERE key = ANY(:keys)"),
        {"keys": GATEABLE_KEYS},
    )

    op.drop_table("plan_features")
    op.drop_column("users", "role")
