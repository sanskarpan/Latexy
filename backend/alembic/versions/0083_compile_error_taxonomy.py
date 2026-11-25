"""Persist a normalized compile-error class on compilation rows.

Only the allowlisted class is stored. Raw compiler logs, error excerpts,
document source and provider diagnostics are never copied into this column or
returned by analytics. Existing rows keep the ``unknown`` default; no historic
failure is reclassified.
"""

import sqlalchemy as sa

from alembic import op

revision = "0083_compile_error_taxonomy"
down_revision = "0082_signup_funnel_providers"
branch_labels = None
depends_on = None

ERROR_CLASSES = (
    "syntax",
    "missing_package",
    "timeout",
    "engine",
    "storage",
    "pdf_limit",
    "unknown",
)


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.add_column(
        "compilations",
        sa.Column(
            "error_class",
            sa.String(32),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.create_check_constraint(
        "ck_compilations_error_class",
        "compilations",
        _in_clause("error_class", ERROR_CLASSES),
    )
    op.create_index(
        "idx_compilations_error_class_created",
        "compilations",
        ["error_class", "created_at"],
        postgresql_where=sa.text("status = 'failed'"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_compilations_error_class_created",
        table_name="compilations",
    )
    op.drop_constraint(
        "ck_compilations_error_class",
        "compilations",
        type_="check",
    )
    op.drop_column("compilations", "error_class")
