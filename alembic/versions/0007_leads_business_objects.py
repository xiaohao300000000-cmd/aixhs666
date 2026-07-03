"""Add lead business objects.

Revision ID: 0007_leads_business_objects
Revises: 0006_analysis_processing_states
Create Date: 2026-07-03 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007_leads_business_objects"
down_revision: str | None = "0006_analysis_processing_states"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("public_profile_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="new", nullable=False),
        sa.Column("region_text", sa.String(length=255), nullable=True),
        sa.Column("demand_type", sa.String(length=100), nullable=True),
        sa.Column("product", sa.String(length=100), nullable=True),
        sa.Column("intent_stage", sa.String(length=100), nullable=True),
        sa.Column("intent_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("information_completeness", sa.Integer(), server_default="0", nullable=False),
        sa.Column("known_info_json", sa.JSON(), nullable=True),
        sa.Column("missing_info_json", sa.JSON(), nullable=True),
        sa.Column("recommended_next_step", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["public_profile_id"], ["public_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "public_profile_id", name="uq_leads_platform_public_profile_id"),
    )
    op.create_index("ix_leads_status_updated_at", "leads", ["status", "updated_at"], unique=False)
    op.create_index("ix_leads_intent_score", "leads", ["intent_score"], unique=False)

    op.create_table(
        "lead_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("source_entity_type", sa.String(length=50), nullable=False),
        sa.Column("source_entity_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=True),
        sa.Column("comment_id", sa.Integer(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("demand_type", sa.String(length=100), nullable=True),
        sa.Column("intent_stage", sa.String(length=100), nullable=True),
        sa.Column("score_contribution", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["content_id"], ["contents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lead_id", "source_entity_type", "source_entity_id", name="uq_lead_evidence_lead_source"),
    )
    op.create_index("ix_lead_evidence_lead_id", "lead_evidence", ["lead_id"], unique=False)

    op.create_table(
        "enrichment_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="pending", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lead_id", "task_type", name="uq_enrichment_tasks_lead_task_type"),
    )
    op.create_index("ix_enrichment_tasks_status_updated_at", "enrichment_tasks", ["status", "updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_enrichment_tasks_status_updated_at", table_name="enrichment_tasks")
    op.drop_table("enrichment_tasks")
    op.drop_index("ix_lead_evidence_lead_id", table_name="lead_evidence")
    op.drop_table("lead_evidence")
    op.drop_index("ix_leads_intent_score", table_name="leads")
    op.drop_index("ix_leads_status_updated_at", table_name="leads")
    op.drop_table("leads")
