"""Add persistent Skill Runtime facts.

Revision ID: 0016_skill_runs
Revises: 0015_lead_comment_replies
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0016_skill_runs"
down_revision = "0015_lead_comment_replies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("skill_key", sa.String(length=100), nullable=False),
        sa.Column("skill_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="draft", nullable=False),
        sa.Column("current_stage", sa.String(length=100), nullable=True),
        sa.Column("progress_current", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress_percent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=True),
        sa.Column("preview_json", sa.JSON(), nullable=True),
        sa.Column("checkpoint_json", sa.JSON(), nullable=True),
        sa.Column("result_summary_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("feishu_chat_id", sa.String(length=255), nullable=True),
        sa.Column("feishu_message_id", sa.String(length=255), nullable=True),
        sa.Column("feishu_card_status", sa.String(length=50), nullable=True),
        sa.Column("feishu_sync_error", sa.Text(), nullable=True),
        sa.Column("copied_from_run_id", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["copied_from_run_id"], ["skill_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_skill_runs_idempotency_key"),
    )
    op.create_index("ix_skill_runs_status_updated_at", "skill_runs", ["status", "updated_at"])
    op.create_index("ix_skill_runs_stage_status", "skill_runs", ["current_stage", "status"])
    op.create_table(
        "skill_run_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("skill_run_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("stage", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("progress_current", sa.Integer(), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("data_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["skill_run_id"], ["skill_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uq_skill_run_events_event_key"),
        sa.UniqueConstraint("skill_run_id", "sequence", name="uq_skill_run_events_run_sequence"),
    )
    op.create_index("ix_skill_run_events_run_created_at", "skill_run_events", ["skill_run_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_skill_run_events_run_created_at", table_name="skill_run_events")
    op.drop_table("skill_run_events")
    op.drop_index("ix_skill_runs_stage_status", table_name="skill_runs")
    op.drop_index("ix_skill_runs_status_updated_at", table_name="skill_runs")
    op.drop_table("skill_runs")
