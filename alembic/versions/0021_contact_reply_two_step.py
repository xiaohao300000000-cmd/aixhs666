"""Add versioned two-step public reply commands.

Revision ID: 0021_contact_reply_two_step
Revises: 0020_review_queue_idempotency
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0021_contact_reply_two_step"
down_revision = "0020_review_queue_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_comment_replies",
        sa.Column("draft_revision", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "lead_comment_replies",
        sa.Column("approved_revision", sa.Integer(), nullable=True),
    )
    op.add_column(
        "lead_comment_replies",
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE lead_comment_replies "
            "SET approved_revision = draft_revision "
            "WHERE approved_text IS NOT NULL AND approved_revision IS NULL"
        )
    )
    op.create_table(
        "contact_command_operations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("operation_scope", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operation_scope",
            "entity_id",
            "idempotency_key_hash",
            name="uq_contact_command_operations_scope_entity_key",
        ),
    )
    op.create_index(
        "ix_contact_command_operations_scope_entity_created",
        "contact_command_operations",
        ["operation_scope", "entity_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_contact_command_operations_scope_entity_created",
        table_name="contact_command_operations",
    )
    op.drop_table("contact_command_operations")
    op.drop_column("lead_comment_replies", "queued_at")
    op.drop_column("lead_comment_replies", "approved_revision")
    op.drop_column("lead_comment_replies", "draft_revision")
