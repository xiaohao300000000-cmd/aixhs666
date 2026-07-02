"""Add analysis processing states.

Revision ID: 0006_analysis_processing_states
Revises: 0005_pipeline_runs
Create Date: 2026-07-03 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006_analysis_processing_states"
down_revision: str | None = "0005_pipeline_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_processing_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("analysis_version", sa.String(length=100), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_pipeline_run_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["last_pipeline_run_id"], ["pipeline_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_type",
            "entity_id",
            "analysis_version",
            name="uq_analysis_processing_states_entity_version",
        ),
    )
    op.create_index(
        "ix_analysis_processing_states_entity",
        "analysis_processing_states",
        ["entity_type", "entity_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_processing_states_entity", table_name="analysis_processing_states")
    op.drop_table("analysis_processing_states")
