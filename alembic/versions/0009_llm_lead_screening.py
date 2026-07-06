"""llm lead screening results

Revision ID: 0009_llm_lead_screening
Revises: 0008_feishu_bitable_sync
Create Date: 2026-07-06 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0009_llm_lead_screening"
down_revision: str | None = "0008_feishu_bitable_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lead_screening_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("source_entity_type", sa.String(length=50), nullable=False),
        sa.Column("source_entity_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=True),
        sa.Column("comment_id", sa.Integer(), nullable=True),
        sa.Column("public_profile_id", sa.Integer(), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("valuable", sa.Boolean(), nullable=True),
        sa.Column("demand_type", sa.String(length=100), nullable=True),
        sa.Column("intent_strength", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("judgment_evidence_json", sa.JSON(), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("llm_raw_json", sa.JSON(), nullable=True),
        sa.Column("review_status", sa.String(length=50), server_default="needs_review", nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["content_id"], ["contents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["public_profile_id"], ["public_profiles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_entity_type", "source_entity_id", name="uq_lead_screening_source"),
    )
    op.create_index("ix_lead_screening_profile_id", "lead_screening_results", ["public_profile_id"])
    op.create_index("ix_lead_screening_review_status", "lead_screening_results", ["review_status"])


def downgrade() -> None:
    op.drop_index("ix_lead_screening_review_status", table_name="lead_screening_results")
    op.drop_index("ix_lead_screening_profile_id", table_name="lead_screening_results")
    op.drop_table("lead_screening_results")
