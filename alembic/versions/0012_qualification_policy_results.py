"""qualification policy results

Revision ID: 0012_qualification_results
Revises: 0011_lead_flow_state
Create Date: 2026-07-07 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0012_qualification_results"
down_revision: str | None = "0011_lead_flow_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("lead_screening_results", sa.Column("qualification_decision", sa.String(length=50), nullable=True))
    op.add_column("lead_screening_results", sa.Column("qualification_reason_codes_json", sa.JSON(), nullable=True))
    op.add_column("lead_screening_results", sa.Column("qualification_human_reason", sa.Text(), nullable=True))
    op.add_column("lead_screening_results", sa.Column("qualification_confidence", sa.Integer(), nullable=True))
    op.add_column("lead_screening_results", sa.Column("qualification_evidence_ids_json", sa.JSON(), nullable=True))
    op.add_column("lead_screening_results", sa.Column("qualification_policy_version", sa.String(length=255), nullable=True))
    op.add_column("lead_screening_results", sa.Column("qualification_location_json", sa.JSON(), nullable=True))
    op.create_index("ix_lead_screening_qualification_decision", "lead_screening_results", ["qualification_decision"])


def downgrade() -> None:
    op.drop_index("ix_lead_screening_qualification_decision", table_name="lead_screening_results")
    op.drop_column("lead_screening_results", "qualification_location_json")
    op.drop_column("lead_screening_results", "qualification_policy_version")
    op.drop_column("lead_screening_results", "qualification_evidence_ids_json")
    op.drop_column("lead_screening_results", "qualification_confidence")
    op.drop_column("lead_screening_results", "qualification_human_reason")
    op.drop_column("lead_screening_results", "qualification_reason_codes_json")
    op.drop_column("lead_screening_results", "qualification_decision")
