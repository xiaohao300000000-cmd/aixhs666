"""lead screening workflow state

Revision ID: 0011_lead_flow_state
Revises: 0010_feishu_llm_review_loop
Create Date: 2026-07-07 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0011_lead_flow_state"
down_revision: str | None = "0010_feishu_llm_review_loop"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lead_screening_results",
        sa.Column("workflow_status", sa.String(length=50), server_default="pending_llm", nullable=False),
    )
    op.add_column(
        "lead_screening_results",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("lead_screening_results", sa.Column("last_error", sa.Text(), nullable=True))
    op.create_index("ix_lead_screening_workflow_status", "lead_screening_results", ["workflow_status"])

    op.execute(
        """
        UPDATE lead_screening_results
        SET workflow_status = CASE
            WHEN human_review_status IS NOT NULL THEN 'reviewed'
            WHEN feishu_message_id IS NOT NULL THEN 'sent'
            WHEN review_status = 'needs_review' THEN 'pending_feishu'
            ELSE 'llm_done'
        END
        """
    )


def downgrade() -> None:
    op.drop_index("ix_lead_screening_workflow_status", table_name="lead_screening_results")
    op.drop_column("lead_screening_results", "last_error")
    op.drop_column("lead_screening_results", "attempt_count")
    op.drop_column("lead_screening_results", "workflow_status")
