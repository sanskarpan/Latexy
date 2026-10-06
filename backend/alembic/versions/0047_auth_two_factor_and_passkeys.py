"""Add Better Auth two-factor and passkey plugin tables.

Better Auth's application tables are managed by the repository's Alembic
chain. Keep the model/column names below aligned with the plugin schemas in
better-auth 1.6.25 and @better-auth/passkey 1.6.25.

Revision ID: 0047
Revises: 0046
Create Date: 2026-09-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The existing user table uses snake_case application columns while
    # Better Auth's logical field is twoFactorEnabled. auth.ts maps the field
    # explicitly, preserving the plugin's public API.
    op.add_column(
        "users",
        sa.Column(
            "two_factor_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # auth.ts explicitly configures encrypted backup-code storage. The TOTP
    # secret and backup-code payload must never be returned by the adapter API.
    op.create_table(
        "twoFactor",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("userId", sa.String(255), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("backupCodes", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("failedVerificationCount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lockedUntil", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("userId", name="uq_two_factor_user_id"),
        # Better Auth's encrypted representation is bare hex ciphertext when
        # using BETTER_AUTH_SECRET, or a versioned `$ba$<version>$<hex>`
        # envelope when key rotation is configured. Legacy plaintext backup
        # codes are a JSON array. Keep the invariant in the database so a
        # future adapter/config regression cannot write plaintext or malformed
        # values back into the database.
        sa.CheckConstraint(
            '(("backupCodes" ~ \'^([0-9A-Fa-f]{2}){32,}$\') OR '
            '("backupCodes" ~ \'^\\$ba\\$[0-9]+\\$([0-9A-Fa-f]{2}){32,}$\'))',
            name="ck_two_factor_backup_codes_encrypted",
        ),
        # The TOTP seed is encrypted through the same Better Auth helper and
        # therefore has the same two supported ciphertext representations.
        # Enforce this separately so a future adapter/configuration regression
        # cannot persist the account's reusable seed in plaintext either.
        sa.CheckConstraint(
            '((secret ~ \'^([0-9A-Fa-f]{2}){32,}$\') OR '
            '(secret ~ \'^\\$ba\\$[0-9]+\\$([0-9A-Fa-f]{2}){32,}$\'))',
            name="ck_two_factor_secret_encrypted",
        ),
    )
    # Better Auth marks this column as indexed even though it is encrypted;
    # retain the generated schema's index for adapter/schema parity.
    op.create_index("idx_two_factor_secret", "twoFactor", ["secret"])
    op.create_index("idx_two_factor_user_id", "twoFactor", ["userId"])

    op.create_table(
        "passkey",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("publicKey", sa.Text(), nullable=False),
        sa.Column("userId", sa.String(255), nullable=False),
        sa.Column("credentialID", sa.String(1024), nullable=False),
        sa.Column("counter", sa.BigInteger(), nullable=False),
        sa.Column("deviceType", sa.String(64), nullable=False),
        sa.Column("backedUp", sa.Boolean(), nullable=False),
        sa.Column("transports", sa.Text(), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aaguid", sa.String(255), nullable=True),
        sa.UniqueConstraint("credentialID", name="uq_passkey_credential_id"),
    )
    op.create_index("idx_passkey_user_id", "passkey", ["userId"])
    op.create_index("idx_passkey_credential_id", "passkey", ["credentialID"])


def downgrade() -> None:
    op.drop_index("idx_passkey_credential_id", table_name="passkey")
    op.drop_index("idx_passkey_user_id", table_name="passkey")
    op.drop_table("passkey")
    op.drop_index("idx_two_factor_user_id", table_name="twoFactor")
    op.drop_index("idx_two_factor_secret", table_name="twoFactor")
    op.drop_table("twoFactor")
    op.drop_column("users", "two_factor_enabled")
