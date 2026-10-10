"""Role restrictions preserve existing access and all administrator choices."""
import sqlalchemy as sa
from alembic import op

revision = "0063_capability_roles"
down_revision = "0062_plan_quotas"
branch_labels = None
depends_on = None

ROLES = ["anonymous", "user", "support", "admin"]
KEYS = ['llm_optimize', 'ats_score', 'ats_deep', 'resume_builder', 'cover_letters', 'batch_tailor', 'templates', 'exports', 'ai_writing', 'macros', 'snippets', 'career_paths', 'interview_prep', 'application_tracker', 'one_click_apply', 'byok', 'collaboration', 'team_workspaces', 'portfolio', 'developer_api', 'references', 'integration_github', 'integration_dropbox', 'integration_google_drive', 'integration_zotero', 'integration_mendeley', 'ai_import_github', 'ai_import_url', 'ai_import_linkedin', 'analytics', 'a06', 'a09', 'b02', 'b03', 'b04', 'b05', 'b06', 'b07', 'b08', 'b09', 'b10', 'b11', 'b12', 'b13', 'b14', 'c02', 'c03', 'c04', 'c06', 'c07', 'c10', 'c11', 'c12', 'c13', 'c14', 'c15', 'c16', 'c17', 'c18', 'c19', 'c20', 'c21', 'c22', 'c23', 'c24', 'd01', 'd02', 'd03', 'd04', 'd05', 'd06', 'd07', 'd08', 'd09', 'd10', 'd11', 'd12', 'd13', 'd14', 'd15', 'd16', 'd17', 'd18', 'd19', 'd20', 'd21', 'd22', 'd23', 'd24', 'd25', 'd26', 'e01', 'e02', 'e03', 'e04', 'e05', 'e06', 'e07', 'e08', 'e09', 'e10', 'e11', 'e12', 'e13', 'f01', 'f02', 'f03', 'f04', 'f05', 'f06', 'f07', 'f08', 'f09', 'g01', 'g02', 'g03', 'g04', 'g05', 'g06', 'g07', 'g08', 'g09', 'g10', 'g11', 'g12', 'g13', 'h01', 'h02', 'h03', 'h04', 'h05', 'h06', 'h07', 'h08', 'h09', 'i02', 'i03']


def upgrade() -> None:
    conn = op.get_bind()
    if not op.get_context().as_sql and sa.inspect(conn).has_table("role_features"):
        inspector = sa.inspect(conn)
        columns = {column["name"]: column for column in inspector.get_columns("role_features")}
        expected = {"role": (sa.String(20), False), "feature_key": (sa.String(100), False),
                    "enabled": (sa.Boolean(), False), "updated_at": (sa.DateTime(timezone=True), False)}
        if set(columns) != set(expected):
            raise RuntimeError("Cannot reuse role_features: unexpected preserved schema")
        for name, (kind, nullable) in expected.items():
            actual = columns[name]
            if not isinstance(actual["type"], type(kind)) or actual["nullable"] != nullable:
                raise RuntimeError(f"Cannot reuse role_features.{name}: incompatible schema")
            for attr in ("length", "timezone"):
                if getattr(kind, attr, None) != getattr(actual["type"], attr, None):
                    raise RuntimeError(f"Cannot reuse role_features.{name}: incompatible {attr}")
        if set(inspector.get_pk_constraint("role_features")["constrained_columns"]) != {"role", "feature_key"}:
            raise RuntimeError("Cannot reuse role_features: incompatible primary key")
        constraints = {row["name"]: row["sqltext"] for row in inspector.get_check_constraints("role_features")}
        if "ck_capability_role" not in constraints:
            raise RuntimeError("Cannot reuse role_features: missing account-role constraint")
        # PostgreSQL normalizes IN to ANY(ARRAY[...]); compare values rather
        # than formatting while refusing an operator-created widened domain.
        import re
        expression = re.sub(r"::(?:character varying|text)(?:\[\])?", "", constraints["ck_capability_role"])
        expression = re.sub(r"[()\s]", "", expression).lower()
        values = ",".join(repr(role) for role in ROLES)
        if expression not in {f"role=anyarray[{values}]", f"rolein{values}"}:
            raise RuntimeError("Cannot reuse role_features: incompatible account-role constraint")
    else:
        op.create_table(
            "role_features",
            sa.Column("role", sa.String(20), primary_key=True),
            sa.Column("feature_key", sa.String(100), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("role IN ('anonymous', 'user', 'support', 'admin')", name="ck_capability_role"),
        )
    for role in ROLES:
        for key in KEYS:
            conn.execute(sa.text(
                "INSERT INTO role_features (role, feature_key, enabled) VALUES (:role, :key, true) "
                "ON CONFLICT (role, feature_key) DO NOTHING"
            ), {"role": role, "key": key})


def downgrade() -> None:
    # Older code ignores the table; administrator choices survive rollback.
    pass
