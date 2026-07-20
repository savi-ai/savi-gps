"""Add repo_analysis_views table for derived analysis artifacts (Phase 0)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_repo_analysis_views"
down_revision: Union[str, None] = "001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("repo_analysis_views"):
        return

    op.create_table(
        "repo_analysis_views",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("repository_id", sa.String(), nullable=False),
        sa.Column("view_type", sa.String(), nullable=False),
        sa.Column("anchor_symbol", sa.String(), nullable=True),
        sa.Column("summary_sentence", sa.Text(), nullable=False),
        sa.Column("mermaid", sa.Text(), nullable=True),
        sa.Column("derivation_json", sa.JSON(), nullable=True),
        sa.Column("index_run_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.ForeignKeyConstraint(["index_run_id"], ["index_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_repo_analysis_views_tenant_id",
        "repo_analysis_views",
        ["tenant_id"],
    )
    op.create_index(
        "ix_repo_analysis_views_repository_id",
        "repo_analysis_views",
        ["repository_id"],
    )
    op.create_index(
        "ix_repo_analysis_views_view_type",
        "repo_analysis_views",
        ["view_type"],
    )
    op.create_index(
        "idx_repo_analysis_view_lookup",
        "repo_analysis_views",
        ["repository_id", "view_type", "anchor_symbol"],
    )


def downgrade() -> None:
    op.drop_index("idx_repo_analysis_view_lookup", table_name="repo_analysis_views")
    op.drop_index("ix_repo_analysis_views_view_type", table_name="repo_analysis_views")
    op.drop_index("ix_repo_analysis_views_repository_id", table_name="repo_analysis_views")
    op.drop_index("ix_repo_analysis_views_tenant_id", table_name="repo_analysis_views")
    op.drop_table("repo_analysis_views")
