"""Add durable review queue operation idempotency facts.

Revision ID: 0020_review_queue_idempotency
Revises: 0019_review_queue
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0020_review_queue_idempotency"
down_revision = "0019_review_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_queue_operations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("operation_kind", sa.String(length=50), nullable=False),
        sa.Column("queue_date", sa.Date(), nullable=False),
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
            "idempotency_key_hash",
            name="uq_review_queue_operations_key_hash",
        ),
    )
    op.create_index(
        "ix_review_queue_operations_kind_date_created",
        "review_queue_operations",
        ["operation_kind", "queue_date", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_review_queue_operations_kind_date_created",
        table_name="review_queue_operations",
    )
    op.drop_table("review_queue_operations")
