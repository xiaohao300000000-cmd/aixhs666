"""lead outreach messages

Revision ID: 0014_lead_outreach_messages
Revises: 0013_comment_region_text
Create Date: 2026-07-09 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0014_lead_outreach_messages"
down_revision: str | None = "0013_comment_region_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lead_outreach_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("screening_result_id", sa.Integer(), nullable=False),
        sa.Column("public_profile_id", sa.Integer(), nullable=True),
        sa.Column("platform", sa.String(length=50), server_default="xhs", nullable=False),
        sa.Column("target_profile_url", sa.Text(), nullable=True),
        sa.Column("generated_text", sa.Text(), nullable=False),
        sa.Column("final_text", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="draft", nullable=False),
        sa.Column("feishu_message_id", sa.String(length=255), nullable=True),
        sa.Column("feishu_chat_id", sa.String(length=255), nullable=True),
        sa.Column("feishu_card_status", sa.String(length=50), nullable=True),
        sa.Column("reviewer_id", sa.String(length=255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["public_profile_id"], ["public_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["screening_result_id"], ["lead_screening_results.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("screening_result_id", name="uq_lead_outreach_screening_result_id"),
    )
    op.create_index("ix_lead_outreach_status", "lead_outreach_messages", ["status"])
    op.create_index("ix_lead_outreach_feishu_message_id", "lead_outreach_messages", ["feishu_message_id"])


def downgrade() -> None:
    op.drop_index("ix_lead_outreach_feishu_message_id", table_name="lead_outreach_messages")
    op.drop_index("ix_lead_outreach_status", table_name="lead_outreach_messages")
    op.drop_table("lead_outreach_messages")
