"""Make task claiming and discovery ingestion concurrency safe.

Revision ID: 0003_task_claiming_and_discovery_uniqueness
Revises: 0002_core_data_models
Create Date: 2026-07-02 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_task_claiming_and_discovery_uniqueness"
down_revision: str | None = "0002_core_data_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_discovery_relations_query_id_content_id",
        "discovery_relations",
        ["query_id", "content_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_discovery_relations_query_id_content_id",
        "discovery_relations",
        type_="unique",
    )
