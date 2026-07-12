"""lead comment replies

Revision ID: 0015_lead_comment_replies
Revises: 0014_lead_outreach_messages
Create Date: 2026-07-12 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0015_lead_comment_replies"
down_revision: str | None = "0014_lead_outreach_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("followup_status", sa.String(length=50), nullable=True))
    op.add_column("leads", sa.Column("next_followup_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "lead_comment_replies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("screening_result_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("target_comment_id", sa.Integer(), nullable=True),
        sa.Column("target_platform_comment_id", sa.String(length=255), nullable=False),
        sa.Column("target_content_id", sa.Integer(), nullable=True),
        sa.Column("target_platform_content_id", sa.String(length=255), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=True),
        sa.Column("draft_text", sa.Text(), nullable=False),
        sa.Column("approved_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="pending_review", nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("feishu_chat_id", sa.String(length=255), nullable=True),
        sa.Column("feishu_message_id", sa.String(length=255), nullable=True),
        sa.Column("feishu_card_status", sa.String(length=50), nullable=True),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("platform_reply_id", sa.String(length=255), nullable=True),
        sa.Column("platform_response_json", sa.JSON(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("feishu_sync_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["screening_result_id"], ["lead_screening_results.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_comment_id"], ["comments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_content_id"], ["contents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("screening_result_id", name="uq_lead_comment_replies_screening_result_id"),
        sa.UniqueConstraint(
            "target_platform_comment_id",
            name="uq_lead_comment_replies_target_platform_comment_id",
        ),
    )
    op.create_index(
        "ix_lead_comment_replies_target_status",
        "lead_comment_replies",
        ["target_comment_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_lead_comment_replies_target_status", table_name="lead_comment_replies")
    op.drop_table("lead_comment_replies")
    op.drop_column("leads", "next_followup_at")
    op.drop_column("leads", "followup_status")
