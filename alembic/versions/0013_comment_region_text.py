"""comment region text

Revision ID: 0013_comment_region_text
Revises: 0012_qualification_results
Create Date: 2026-07-07 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0013_comment_region_text"
down_revision: str | None = "0012_qualification_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("comments", sa.Column("region_text", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("comments", "region_text")
