"""Persist bounded document-complexity counts on compilation rows.

Only counts are stored: the compiler-reported page count and a bounded count
of section commands derived from submitted source at admission. LaTeX source,
PDF text and document content are never copied into these columns.

The bounds are enforced in the database so a malformed worker payload or a
future writer cannot persist an unbounded value. Existing rows remain NULL,
which the admin report counts as "missing" rather than guessing.
"""

import sqlalchemy as sa

from alembic import op

revision = "0092_document_complexity"
down_revision = "0091_dunning_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "compilations",
        sa.Column("page_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "compilations",
        sa.Column("section_count", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_compilations_page_count_bounded",
        "compilations",
        "page_count IS NULL OR (page_count >= 1 AND page_count <= 10000)",
    )
    op.create_check_constraint(
        "ck_compilations_section_count_bounded",
        "compilations",
        "section_count IS NULL OR (section_count >= 0 AND section_count <= 500)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_compilations_section_count_bounded",
        "compilations",
        type_="check",
    )
    op.drop_constraint(
        "ck_compilations_page_count_bounded",
        "compilations",
        type_="check",
    )
    op.drop_column("compilations", "section_count")
    op.drop_column("compilations", "page_count")
