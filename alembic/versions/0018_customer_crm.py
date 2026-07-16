"""Add customer CRM facts and follow-up records.

Revision ID: 0018_customer_crm
Revises: 0017_customer_timeline_events
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018_customer_crm"
down_revision = "0017_customer_timeline_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("crm_stage", sa.String(length=50), server_default="candidate", nullable=False),
    )
    op.add_column(
        "leads",
        sa.Column("customer_tags_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column("leads", sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("last_contact_result", sa.String(length=100), nullable=True))
    op.add_column(
        "leads",
        sa.Column("crm_sync_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.execute(
        """
        UPDATE leads
        SET crm_stage = CASE
            WHEN status = 'qualified' AND followup_status = 'pending' THEN 'awaiting_first_contact'
            WHEN status = 'qualified' THEN 'new_customer'
            WHEN status = 'watch' OR followup_status = 'deferred' THEN 'deferred'
            WHEN status = 'ignored' THEN 'invalid'
            ELSE 'candidate'
        END
        """
    )

    op.create_table(
        "customer_followup_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("channel", sa.String(length=100), nullable=True),
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("customer_reply", sa.Text(), nullable=True),
        sa.Column("result", sa.String(length=100), nullable=True),
        sa.Column("next_step", sa.Text(), nullable=True),
        sa.Column("next_followup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_entry", sa.String(length=100), nullable=True),
        sa.Column("platform_evidence_json", sa.JSON(), nullable=True),
        sa.Column("is_completed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uq_customer_followup_records_event_key"),
    )
    op.create_index(
        "ix_customer_followup_records_lead_occurred",
        "customer_followup_records",
        ["lead_id", "occurred_at"],
    )
    op.execute(
        """
        INSERT INTO customer_followup_records (
            lead_id,
            event_key,
            occurred_at,
            action_type,
            result,
            next_step,
            source_entry,
            is_completed
        )
        SELECT
            id,
            'crm-migration-customer:' || id::text,
            COALESCE(updated_at, created_at, CURRENT_TIMESTAMP),
            CASE WHEN followup_status = 'pending' THEN '待首次联系' ELSE '新客户' END,
            CASE WHEN followup_status = 'pending' THEN 'pending' ELSE 'completed' END,
            recommended_next_step,
            '0018_customer_crm',
            CASE WHEN followup_status = 'pending' THEN FALSE ELSE TRUE END
        FROM leads
        WHERE status = 'qualified'
        ON CONFLICT (event_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_customer_followup_records_lead_occurred", table_name="customer_followup_records")
    op.drop_table("customer_followup_records")
    op.drop_column("leads", "crm_sync_version")
    op.drop_column("leads", "last_contact_result")
    op.drop_column("leads", "last_contact_at")
    op.drop_column("leads", "customer_tags_json")
    op.drop_column("leads", "crm_stage")
