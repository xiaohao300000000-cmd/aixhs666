"""feishu bitable sync

Revision ID: 0008_feishu_bitable_sync
Revises: 0007_leads_business_objects
Create Date: 2026-07-04 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0008_feishu_bitable_sync"
down_revision: str | None = "0007_leads_business_objects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("owner_name", sa.String(length=255), nullable=True))
    op.add_column("leads", sa.Column("operator_note", sa.Text(), nullable=True))
    op.add_column("leads", sa.Column("last_feedback_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "feishu_bitable_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("local_entity_type", sa.String(length=50), nullable=False),
        sa.Column("local_entity_id", sa.Integer(), nullable=False),
        sa.Column("app_token", sa.String(length=255), nullable=False),
        sa.Column("table_id", sa.String(length=255), nullable=False),
        sa.Column("record_id", sa.String(length=255), nullable=True),
        sa.Column("sync_direction", sa.String(length=50), server_default="push", nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_remote_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=50), server_default="pending", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("remote_fields_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "local_entity_type",
            "local_entity_id",
            "app_token",
            "table_id",
            name="uq_feishu_bitable_local_record",
        ),
    )
    op.create_index("ix_feishu_bitable_record_id", "feishu_bitable_records", ["record_id"])


def downgrade() -> None:
    op.drop_index("ix_feishu_bitable_record_id", table_name="feishu_bitable_records")
    op.drop_table("feishu_bitable_records")
    op.drop_column("leads", "last_feedback_at")
    op.drop_column("leads", "operator_note")
    op.drop_column("leads", "owner_name")
