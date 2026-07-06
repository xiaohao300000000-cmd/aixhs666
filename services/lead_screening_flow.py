from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from storage.models import CollectionEvent, LeadScreeningResult


PENDING_LLM = "pending_llm"
SCREENING = "screening"
LLM_DONE = "llm_done"
PENDING_FEISHU = "pending_feishu"
SENDING = "sending"
SENT = "sent"
SEND_UNCERTAIN = "send_uncertain"
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


def claim_pending_llm_screenings(
    session: Session,
    *,
    limit: int = 10,
    screening_ids: set[int] | None = None,
    source_entity_types: set[str] | None = None,
) -> list[LeadScreeningResult]:
    statement = (
        select(LeadScreeningResult)
        .where(LeadScreeningResult.workflow_status == PENDING_LLM)
        .order_by(LeadScreeningResult.id.asc())
        .with_for_update(skip_locked=True)
    )
    if screening_ids:
        statement = statement.where(LeadScreeningResult.id.in_(screening_ids))
    if source_entity_types:
        statement = statement.where(LeadScreeningResult.source_entity_type.in_(source_entity_types))
    screenings = session.scalars(statement.limit(limit)).all()
    now = _utc_now()
    for screening in screenings:
        screening.workflow_status = SCREENING
        screening.last_error = None
        screening.updated_at = now
    session.flush()
    return screenings


def diagnose_lead_screening_workflow(
    session: Session,
    *,
    now: datetime | None = None,
    sending_timeout: timedelta = timedelta(minutes=30),
    pending_llm_timeout: timedelta = timedelta(hours=24),
    high_attempt_threshold: int = 3,
    limit: int = 50,
) -> dict[str, Any]:
    now = now or _utc_now()
    screenings = session.scalars(select(LeadScreeningResult).order_by(LeadScreeningResult.id.asc())).all()
    counts_by_status: dict[str, int] = {}
    issue_counts = {
        "stale_sending": 0,
        "stale_pending_llm": 0,
        "high_attempt_count": 0,
        "empty_error_abnormal_state": 0,
        "send_uncertain": 0,
    }
    issues: list[dict[str, Any]] = []
    for screening in screenings:
        status = screening.workflow_status
        counts_by_status[status] = counts_by_status.get(status, 0) + 1
        updated_at = _aware_utc(screening.updated_at or screening.created_at)
        detected: list[str] = []
        recommended_action = "inspect"
        if status == SENDING and now - updated_at > sending_timeout:
            detected.append("stale_sending")
            recommended_action = "manual_check"
        if status == PENDING_LLM and now - updated_at > pending_llm_timeout:
            detected.append("stale_pending_llm")
        if status == SEND_UNCERTAIN:
            detected.append("send_uncertain")
            recommended_action = "manual_check"
        if (screening.attempt_count or 0) >= high_attempt_threshold:
            detected.append("high_attempt_count")
        if status in {SENDING, SCREENING, SEND_UNCERTAIN} and not screening.last_error:
            detected.append("empty_error_abnormal_state")
        for item in detected:
            issue_counts[item] += 1
        if detected and len(issues) < limit:
            issues.append(
                {
                    "screening_result_id": screening.id,
                    "workflow_status": status,
                    "source_entity_type": screening.source_entity_type,
                    "source_entity_id": screening.source_entity_id,
                    "attempt_count": screening.attempt_count,
                    "last_error": screening.last_error,
                    "updated_at": updated_at.isoformat(),
                    "issues": detected,
                    "recommended_action": recommended_action,
                }
            )
    return {"counts_by_status": counts_by_status, "issue_counts": issue_counts, "issues": issues}


def lead_screening_flow_stats(session: Session) -> dict[str, Any]:
    workflow_counts = {
        PENDING_LLM: 0,
        SCREENING: 0,
        LLM_DONE: 0,
        PENDING_FEISHU: 0,
        SENDING: 0,
        SENT: 0,
        SEND_UNCERTAIN: 0,
        REVIEWED: 0,
        "failed": 0,
    }
    for status, count in session.execute(
        select(LeadScreeningResult.workflow_status, func.count(LeadScreeningResult.id)).group_by(LeadScreeningResult.workflow_status)
    ):
        workflow_counts[str(status)] = int(count)
    workflow_counts["failed"] = int(
        session.scalar(select(func.count(LeadScreeningResult.id)).where(LeadScreeningResult.last_error.is_not(None))) or 0
    )

    review_counts = {"accepted": 0, "rejected": 0, "needs_review": 0}
    for status, count in session.execute(
        select(LeadScreeningResult.review_status, func.count(LeadScreeningResult.id)).group_by(LeadScreeningResult.review_status)
    ):
        review_counts[str(status)] = int(count)

    return {"workflow_counts": workflow_counts, "review_counts": review_counts}


def recover_stale_lead_screening(
    session: Session,
    *,
    screening_id: int,
    from_status: str,
    to_status: str,
    reason: str,
    operator: str,
    now: datetime | None = None,
) -> bool:
    screening = session.get(LeadScreeningResult, screening_id)
    if screening is None or screening.workflow_status != from_status:
        return False
    now = now or _utc_now()
    screening.workflow_status = to_status
    screening.last_error = reason
    screening.updated_at = now
    session.add(
        CollectionEvent(
            event_type="lead_screening_manual_recovery",
            entity_type="lead_screening_result",
            entity_id=screening_id,
            event_data={
                "from_status": from_status,
                "to_status": to_status,
                "reason": reason,
                "operator": operator,
            },
            occurred_at=now,
        )
    )
    session.flush()
    return True


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)
