"""Add human Skill Run reports and persistent daily review queue facts.

Revision ID: 0019_review_queue
Revises: 0018_customer_crm
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0019_review_queue"
down_revision = "0018_customer_crm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skill_runs", sa.Column("business_report_json", sa.JSON(), nullable=True))
    op.create_table(
        "review_queue_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("queue_date", sa.Date(), nullable=False),
        sa.Column("candidate_key", sa.String(length=255), nullable=False),
        sa.Column("representative_screening_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("public_profile_id", sa.Integer(), nullable=True),
        sa.Column("source_run_id", sa.Integer(), nullable=True),
        sa.Column("screening_ids_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("layer", sa.String(length=50), nullable=False),
        sa.Column("slot_type", sa.String(length=50), nullable=False),
        sa.Column("priority_rank", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="pending", nullable=False),
        sa.Column("is_emergency", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("queue_reason", sa.Text(), nullable=False),
        sa.Column("exclusion_sample_reason", sa.Text(), nullable=True),
        sa.Column("human_decision", sa.String(length=50), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["representative_screening_id"], ["lead_screening_results.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["public_profile_id"], ["public_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_run_id"], ["skill_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "queue_date", "candidate_key", name="uq_review_queue_items_date_candidate"
        ),
    )
    op.create_index(
        "ix_review_queue_items_date_status_position",
        "review_queue_items",
        ["queue_date", "status", "position"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_queue_items_date_status_position", table_name="review_queue_items")
    op.drop_table("review_queue_items")
    op.drop_column("skill_runs", "business_report_json")
