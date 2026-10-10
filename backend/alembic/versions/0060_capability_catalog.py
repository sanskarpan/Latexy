"""Seed the complete capability inventory and concrete-SKU restrictions.

Existing settings are preserved. Granular controls start enabled underneath their
existing family switches, so an existing denial remains a denial. No user data or
subscription is rewritten. This branch must be reconciled with other unmerged
migration heads before release; it intentionally does not import their schemas.
"""
import sqlalchemy as sa
from alembic import op

revision = "0060_capability_catalog"
down_revision = "0059"
branch_labels = None
depends_on = None

KEYS = ['llm_optimize', 'ats_score', 'ats_deep', 'resume_builder', 'cover_letters', 'batch_tailor', 'templates', 'exports', 'ai_writing', 'macros', 'snippets', 'career_paths', 'interview_prep', 'application_tracker', 'one_click_apply', 'byok', 'collaboration', 'team_workspaces', 'portfolio', 'developer_api', 'references', 'integration_github', 'integration_dropbox', 'integration_google_drive', 'integration_zotero', 'integration_mendeley', 'ai_import_github', 'ai_import_url', 'ai_import_linkedin', 'analytics', 'a06', 'a09', 'b02', 'b03', 'b04', 'b05', 'b06', 'b07', 'b08', 'b09', 'b10', 'b11', 'b12', 'b13', 'b14', 'c02', 'c03', 'c04', 'c06', 'c07', 'c10', 'c11', 'c12', 'c13', 'c14', 'c15', 'c16', 'c17', 'c18', 'c19', 'c20', 'c21', 'c22', 'c23', 'c24', 'd01', 'd02', 'd03', 'd04', 'd05', 'd06', 'd07', 'd08', 'd09', 'd10', 'd11', 'd12', 'd13', 'd14', 'd15', 'd16', 'd17', 'd18', 'd19', 'd20', 'd21', 'd22', 'd23', 'd24', 'd25', 'd26', 'e01', 'e02', 'e03', 'e04', 'e05', 'e06', 'e07', 'e08', 'e09', 'e10', 'e11', 'e12', 'e13', 'f01', 'f02', 'f03', 'f04', 'f05', 'f06', 'f07', 'f08', 'f09', 'g01', 'g02', 'g03', 'g04', 'g05', 'g06', 'g07', 'g08', 'g09', 'g10', 'g11', 'g12', 'g13', 'h01', 'h02', 'h03', 'h04', 'h05', 'h06', 'h07', 'h08', 'h09', 'i02', 'i03']
PLAN_KEYS = ["free", "basic", "basic_annual", "pro", "pro_annual", "byok", "byok_annual", "student", "team", "weekly", "lifetime"]


def upgrade() -> None:
    conn = op.get_bind()
    for key in KEYS:
        conn.execute(sa.text("INSERT INTO feature_flags (key, enabled, label, description) VALUES (:key, true, :key, 'Capability control') ON CONFLICT (key) DO NOTHING"), {"key": key})
        for plan in PLAN_KEYS:
            conn.execute(sa.text("INSERT INTO plan_features (plan_family, feature_key, enabled) VALUES (:plan, :key, true) ON CONFLICT (plan_family, feature_key) DO NOTHING"), {"plan": plan, "key": key})


def downgrade() -> None:
    # Settings are user-owned once deployed. Old code ignores unknown keys;
    # deleting them would destroy administrator choices on a rollback/re-upgrade.
    pass
