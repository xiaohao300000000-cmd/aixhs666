from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.skill_run_report import build_candidates_from_screenings, candidate_key
from storage.models import LeadScreeningResult, ReviewQueueItem, SkillRun


BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")
DEFAULT_DAILY_BUDGET = 50
QUALITY_CONTROL_BUDGET = 5


def business_date(now: datetime | None = None) -> date:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(BUSINESS_TIMEZONE).date()


def prepare_daily_review_queue(
    session: Session,
    *,
    queue_date: date | None = None,
    source_run_id: int | None = None,
    budget: int = DEFAULT_DAILY_BUDGET,
) -> dict[str, Any]:
    day = queue_date or business_date()
    bounded_budget = max(1, budget)
    existing = _queue_items(session, day)
    candidates, errors = _eligible_candidates(session, source_run_id=source_run_id)
    existing_keys = {item.candidate_key for item in existing}
    remaining = [item for item in candidates if item["candidate_key"] not in existing_keys]
    regular_existing = [item for item in existing if not item.is_emergency]
    if len(regular_existing) >= bounded_budget:
        return _summary(existing, created=0, backlog=len(remaining), errors=errors)

    by_layer = _by_layer(remaining)
    qc: list[dict[str, Any]] = []
    selected_keys: set[str] = set(existing_keys)
    existing_qc = sum(item.slot_type == "quality_control" for item in regular_existing)
    qc_capacity = max(0, min(QUALITY_CONTROL_BUDGET, bounded_budget) - existing_qc)
    for layer in ("uncertain_review", "automatic_exclusion", "standard_review"):
        for candidate in by_layer[layer]:
            if len(qc) >= qc_capacity:
                break
            qc.append(candidate)
            selected_keys.add(str(candidate["candidate_key"]))

    existing_business = sum(
        item.slot_type != "quality_control" for item in regular_existing
    )
    business_slots = max(
        0,
        max(0, bounded_budget - QUALITY_CONTROL_BUDGET) - existing_business,
    )
    business: list[dict[str, Any]] = []
    for layer in ("priority_review", "standard_review", "uncertain_review"):
        for candidate in by_layer[layer]:
            key = str(candidate["candidate_key"])
            if key in selected_keys:
                continue
            if len(business) >= business_slots:
                break
            business.append(candidate)
            selected_keys.add(key)

    created: list[ReviewQueueItem] = []
    next_position = max((item.position for item in existing), default=0) + 1
    for candidate in qc:
        created.append(
            _new_item(
                day,
                candidate,
                position=next_position + len(created),
                slot_type="quality_control",
                source_run_id=source_run_id,
            )
        )
    for candidate in business:
        created.append(
            _new_item(
                day,
                candidate,
                position=next_position + len(created),
                slot_type="business",
                source_run_id=source_run_id,
            )
        )
    session.add_all(created)
    session.flush()
    backlog = len([item for item in remaining if item["candidate_key"] not in selected_keys])
    return _summary([*existing, *created], created=len(created), backlog=backlog, errors=errors)


def extend_daily_review_queue(
    session: Session,
    *,
    queue_date: date | None = None,
    additional: int = 20,
    priority_only: bool = False,
    source_run_id: int | None = None,
) -> dict[str, Any]:
    day = queue_date or business_date()
    bounded_additional = max(1, additional)
    existing = _queue_items(session, day)
    existing_keys = {item.candidate_key for item in existing}
    candidates, errors = _eligible_candidates(session, source_run_id=source_run_id)
    layers = ("priority_review",) if priority_only else (
        "priority_review",
        "standard_review",
        "uncertain_review",
    )
    remaining = [
        item
        for layer in layers
        for item in candidates
        if item["layer"] == layer and item["candidate_key"] not in existing_keys
    ]
    selected = remaining[:bounded_additional]
    next_position = max((item.position for item in existing), default=0) + 1
    created = [
        _new_item(
            day,
            candidate,
            position=next_position + offset,
            slot_type="continuation",
            source_run_id=source_run_id,
        )
        for offset, candidate in enumerate(selected)
    ]
    session.add_all(created)
    session.flush()
    all_items = [*existing, *created]
    return _summary(
        all_items,
        created=len(created),
        backlog=max(0, len(remaining) - len(created)),
        errors=errors,
    )


def append_emergency_candidate(
    session: Session,
    screening_id: int,
    *,
    reason: str,
    queue_date: date | None = None,
    source_run_id: int | None = None,
) -> ReviewQueueItem:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("emergency reason is required")
    day = queue_date or business_date()
    screening = session.get(LeadScreeningResult, screening_id)
    if screening is None:
        raise LookupError("screening result not found")
    if screening.human_review_status is not None:
        raise ValueError("reviewed candidate cannot be appended as pending")
    if screening.public_profile_id is not None:
        screenings = session.scalars(
            select(LeadScreeningResult).where(
                LeadScreeningResult.public_profile_id == screening.public_profile_id,
                LeadScreeningResult.human_review_status.is_(None),
            )
        ).all()
    else:
        screenings = [screening]
    candidate = build_candidates_from_screenings(
        session, list(screenings), run_id=source_run_id
    )[0]
    existing = session.scalar(
        select(ReviewQueueItem).where(
            ReviewQueueItem.queue_date == day,
            ReviewQueueItem.candidate_key == candidate["candidate_key"],
        )
    )
    if existing is not None:
        existing.is_emergency = True
        existing.queue_reason = normalized_reason
        session.flush()
        return existing
    position = int(
        session.scalar(
            select(func.max(ReviewQueueItem.position)).where(ReviewQueueItem.queue_date == day)
        )
        or 0
    ) + 1
    item = _new_item(
        day,
        candidate,
        position=position,
        slot_type="emergency",
        source_run_id=source_run_id,
        reason=normalized_reason,
        is_emergency=True,
    )
    session.add(item)
    session.flush()
    return item


def list_daily_review_queue(
    session: Session,
    *,
    queue_date: date | None = None,
    layer: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    day = queue_date or business_date()
    statement = select(ReviewQueueItem).where(ReviewQueueItem.queue_date == day)
    if layer is not None:
        statement = statement.where(ReviewQueueItem.layer == layer)
    all_items = session.scalars(
        statement.order_by(ReviewQueueItem.position, ReviewQueueItem.id)
    ).all()
    start = max(0, offset)
    items = all_items[start : start + min(max(limit, 1), 200)]
    return {
        "queue_date": day.isoformat(),
        "total": len(all_items),
        "items": [_item_view(item) for item in items],
        "progress": review_queue_progress(session, queue_date=day),
    }


def review_queue_progress(session: Session, *, queue_date: date | None = None) -> dict[str, int]:
    day = queue_date or business_date()
    items = _queue_items(session, day)
    return {
        "completed": sum(item.status == "completed" for item in items),
        "target": len(items),
        "pending": sum(item.status == "pending" for item in items),
        "quality_control": sum(item.slot_type == "quality_control" for item in items),
    }


def complete_candidate_review(
    session: Session,
    *,
    decision: str,
    reviewed_at: datetime,
    lead_id: int | None = None,
    public_profile_id: int | None = None,
    screening_id: int | None = None,
) -> int:
    pending = session.scalars(
        select(ReviewQueueItem).where(ReviewQueueItem.status == "pending")
    ).all()
    profile_key = f"profile:{public_profile_id}" if public_profile_id is not None else None
    completed = 0
    for item in pending:
        matches = any(
            (
                lead_id is not None and item.lead_id == lead_id,
                public_profile_id is not None and item.public_profile_id == public_profile_id,
                profile_key is not None and item.candidate_key == profile_key,
                screening_id is not None and screening_id in (item.screening_ids_json or []),
            )
        )
        if not matches:
            continue
        item.status = "completed"
        item.human_decision = decision
        item.reviewed_at = reviewed_at
        completed += 1
    session.flush()
    return completed


def _eligible_candidates(
    session: Session,
    *,
    source_run_id: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    reviewed_candidate_keys = {
        candidate_key(screening)
        for screening in session.scalars(
            select(LeadScreeningResult).where(
                LeadScreeningResult.human_review_status.is_not(None)
            )
        ).all()
    }
    statement = select(LeadScreeningResult).where(LeadScreeningResult.human_review_status.is_(None))
    if source_run_id is not None:
        run = session.get(SkillRun, source_run_id)
        if run is None:
            raise LookupError("skill run not found")
        screening_ids = [
            int(value)
            for value in (run.checkpoint_json or {}).get("screening_ids", [])
            if str(value).isdigit()
        ]
        if not screening_ids:
            return [], []
        statement = statement.where(LeadScreeningResult.id.in_(screening_ids))
    screenings = [
        screening
        for screening in session.scalars(statement).all()
        if candidate_key(screening) not in reviewed_candidate_keys
    ]
    errors: list[dict[str, str]] = []
    candidates = build_candidates_from_screenings(
        session,
        screenings,
        run_id=source_run_id,
        errors=errors,
    )
    if source_run_id is not None:
        for candidate in candidates:
            candidate["source_run_id"] = source_run_id
    else:
        succeeded_runs = session.scalars(
            select(SkillRun)
            .where(SkillRun.status == "succeeded")
            .order_by(SkillRun.id.desc())
        ).all()
        run_screenings = [
            (
                run.id,
                {
                    int(value)
                    for value in (run.checkpoint_json or {}).get("screening_ids", [])
                    if str(value).isdigit()
                },
            )
            for run in succeeded_runs
        ]
        for candidate in candidates:
            candidate_ids = {int(value) for value in candidate["screening_ids"]}
            candidate["source_run_id"] = next(
                (
                    run_id
                    for run_id, screening_ids in run_screenings
                    if candidate_ids & screening_ids
                ),
                None,
            )
    return candidates, errors


def _by_layer(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        layer: [candidate for candidate in candidates if candidate["layer"] == layer]
        for layer in (
            "priority_review",
            "standard_review",
            "uncertain_review",
            "automatic_exclusion",
        )
    }


def _new_item(
    day: date,
    candidate: dict[str, Any],
    *,
    position: int,
    slot_type: str,
    source_run_id: int | None,
    reason: str | None = None,
    is_emergency: bool = False,
) -> ReviewQueueItem:
    return ReviewQueueItem(
        queue_date=day,
        candidate_key=str(candidate["candidate_key"]),
        representative_screening_id=int(candidate["representative_screening_id"]),
        lead_id=int(candidate["lead_id"]) if candidate.get("lead_id") is not None else None,
        public_profile_id=(
            int(candidate["public_profile_id"])
            if candidate.get("public_profile_id") is not None
            else None
        ),
        source_run_id=(
            source_run_id
            if source_run_id is not None
            else (
                int(candidate["source_run_id"])
                if candidate.get("source_run_id") is not None
                else None
            )
        ),
        screening_ids_json=[int(value) for value in candidate["screening_ids"]],
        layer=str(candidate["layer"]),
        slot_type=slot_type,
        priority_rank=int(candidate["priority_rank"]),
        position=position,
        status="pending",
        is_emergency=is_emergency,
        queue_reason=reason or str(candidate["reason"]),
        exclusion_sample_reason=(
            str(candidate["hard_exclusion_reason"])
            if candidate.get("hard_exclusion_reason") is not None
            else None
        ),
    )


def _queue_items(session: Session, day: date) -> list[ReviewQueueItem]:
    return list(
        session.scalars(
            select(ReviewQueueItem)
            .where(ReviewQueueItem.queue_date == day)
            .order_by(ReviewQueueItem.position, ReviewQueueItem.id)
        ).all()
    )


def _summary(
    items: list[ReviewQueueItem],
    *,
    created: int,
    backlog: int,
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "queue_date": items[0].queue_date.isoformat() if items else None,
        "created": created,
        "total": len(items),
        "quality_control": sum(item.slot_type == "quality_control" for item in items),
        "emergency": sum(item.is_emergency for item in items),
        "backlog": backlog,
        "errors": errors,
        "item_ids": [item.id for item in items],
        "candidate_keys": [item.candidate_key for item in items],
    }


def _item_view(item: ReviewQueueItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "queue_date": item.queue_date.isoformat(),
        "run_id": item.source_run_id,
        "candidate_key": item.candidate_key,
        "lead_id": item.lead_id,
        "screening_id": item.representative_screening_id,
        "screening_ids": list(item.screening_ids_json or []),
        "layer": item.layer,
        "reason": item.queue_reason,
        "exclusion_sample_reason": item.exclusion_sample_reason,
        "position": item.position,
        "slot_type": item.slot_type,
        "status": item.status,
        "emergency": item.is_emergency,
        "human_decision": item.human_decision,
        "miaoda_href": f"/leads?candidate_key={item.candidate_key}",
        "next_action": "继续人工审核" if item.status == "pending" else "查看审核结果",
    }
