"""feishu llm review loop

Revision ID: 0010_feishu_llm_review_loop
Revises: 0009_llm_lead_screening
Create Date: 2026-07-06 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0010_feishu_llm_review_loop"
down_revision: str | None = "0009_llm_lead_screening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("lead_screening_results", sa.Column("feishu_message_id", sa.String(length=255), nullable=True))
    op.add_column("lead_screening_results", sa.Column("feishu_chat_id", sa.String(length=255), nullable=True))
    op.add_column("lead_screening_results", sa.Column("feishu_card_status", sa.String(length=50), nullable=True))
    op.add_column("lead_screening_results", sa.Column("human_review_status", sa.String(length=50), nullable=True))
    op.add_column("lead_screening_results", sa.Column("human_reviewer_id", sa.String(length=255), nullable=True))
    op.add_column("lead_screening_results", sa.Column("human_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_lead_screening_feishu_message_id", "lead_screening_results", ["feishu_message_id"])
    op.create_index("ix_lead_screening_human_review_status", "lead_screening_results", ["human_review_status"])


def downgrade() -> None:
    op.drop_index("ix_lead_screening_human_review_status", table_name="lead_screening_results")
    op.drop_index("ix_lead_screening_feishu_message_id", table_name="lead_screening_results")
    op.drop_column("lead_screening_results", "human_reviewed_at")
    op.drop_column("lead_screening_results", "human_reviewer_id")
    op.drop_column("lead_screening_results", "human_review_status")
    op.drop_column("lead_screening_results", "feishu_card_status")
    op.drop_column("lead_screening_results", "feishu_chat_id")
    op.drop_column("lead_screening_results", "feishu_message_id")
