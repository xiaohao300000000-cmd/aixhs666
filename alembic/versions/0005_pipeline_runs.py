"""Add pipeline run records.

Revision ID: 0005_pipeline_runs
Revises: 0004_worker_heartbeats
Create Date: 2026-07-03 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005_pipeline_runs"
down_revision: str | None = "0004_worker_heartbeats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="pending", nullable=False),
        sa.Column("requested_by", sa.String(length=100), nullable=True),
        sa.Column("request_data", sa.JSON(), nullable=True),
        sa.Column("progress_data", sa.JSON(), nullable=True),
        sa.Column("result_data", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_pipeline_runs_idempotency_key"),
    )
    op.create_index("ix_pipeline_runs_status_started_at", "pipeline_runs", ["status", "started_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pipeline_runs_status_started_at", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
