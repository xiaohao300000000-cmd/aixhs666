"""Add worker heartbeat table.

Revision ID: 0004_worker_heartbeats
Revises: 0003_task_claiming_discovery
Create Date: 2026-07-02 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_worker_heartbeats"
down_revision: str | None = "0003_task_claiming_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(length=255), primary_key=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="idle"),
        sa.Column("current_task_id", sa.Integer(), sa.ForeignKey("collection_tasks.id", ondelete="SET NULL")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_task_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_task_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("metadata_json", sa.JSON()),
    )


def downgrade() -> None:
    op.drop_table("worker_heartbeats")
