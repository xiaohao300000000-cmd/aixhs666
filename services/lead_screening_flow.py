from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.models import LeadScreeningResult


PENDING_LLM = "pending_llm"
LLM_DONE = "llm_done"
PENDING_FEISHU = "pending_feishu"
SENT = "sent"
REVIEWED = "reviewed"


def advance_llm_done_to_pending_feishu(
    session: Session,
    *,
    limit: int | None = None,
    screening_ids: set[int] | None = None,
) -> dict[str, int]:
    statement = (
        select(LeadScreeningResult)
        .where(LeadScreeningResult.workflow_status == LLM_DONE)
        .where(LeadScreeningResult.review_status == "needs_review")
        .where(LeadScreeningResult.human_review_status.is_(None))
        .where(LeadScreeningResult.feishu_message_id.is_(None))
        .order_by(LeadScreeningResult.id.asc())
    )
    if screening_ids:
        statement = statement.where(LeadScreeningResult.id.in_(screening_ids))
    if limit is not None:
        statement = statement.limit(limit)

    counts = {"advanced": 0, "skipped": 0}
    now = _utc_now()
    for screening in session.scalars(statement).all():
        if screening.id is None:
            counts["skipped"] += 1
            continue
        screening.workflow_status = PENDING_FEISHU
        screening.last_error = None
        screening.updated_at = now
        counts["advanced"] += 1
    session.flush()
    return counts


def _utc_now() -> datetime:
    return datetime.now(UTC)
