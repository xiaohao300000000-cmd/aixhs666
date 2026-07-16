"""Add customer timeline events.

Revision ID: 0017_customer_timeline_events
Revises: 0016_skill_runs
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_customer_timeline_events"
down_revision = "0016_skill_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_timeline_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("data_json", sa.JSON(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uq_customer_timeline_events_event_key"),
    )
    op.create_index(
        "ix_customer_timeline_events_lead_occurred",
        "customer_timeline_events",
        ["lead_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_customer_timeline_events_lead_occurred", table_name="customer_timeline_events")
    op.drop_table("customer_timeline_events")
