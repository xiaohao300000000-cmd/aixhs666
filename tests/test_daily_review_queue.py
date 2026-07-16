from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from services.daily_review_queue import (
    append_emergency_candidate,
    business_date,
    extend_daily_review_queue,
    prepare_daily_review_queue,
)
from storage.database import Base
from storage.models import LeadScreeningResult, PublicProfile, ReviewQueueItem


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_review_queue_item_persists_business_day_identity_and_audit_fields() -> None:
    factory = _factory()
    with factory() as session:
        item = ReviewQueueItem(
            queue_date=date(2026, 7, 16),
            candidate_key="profile:42",
            screening_ids_json=[10, 11],
            layer="uncertain_review",
            slot_type="quality_control",
            priority_rank=300,
            position=1,
            status="pending",
            is_emergency=False,
            queue_reason="低置信度保留人工判断",
            exclusion_sample_reason=None,
        )
        session.add(item)
        session.commit()

        stored = session.scalar(select(ReviewQueueItem))
        assert stored is not None
        assert stored.candidate_key == "profile:42"
        assert stored.screening_ids_json == [10, 11]
        assert stored.human_decision is None
        assert stored.reviewed_at is None


def test_review_queue_item_is_unique_per_business_day_and_candidate() -> None:
    factory = _factory()
    with factory() as session:
        common = {
            "queue_date": date(2026, 7, 16),
            "candidate_key": "profile:42",
            "screening_ids_json": [10],
            "layer": "standard_review",
            "slot_type": "business",
            "priority_rank": 200,
            "status": "pending",
            "is_emergency": False,
            "queue_reason": "普通候选",
        }
        session.add_all(
            [ReviewQueueItem(position=1, **common), ReviewQueueItem(position=2, **common)]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_review_queue_has_date_status_position_read_index() -> None:
    factory = _factory()
    index_names = {
        item["name"] for item in inspect(factory.kw["bind"]).get_indexes("review_queue_items")
    }

    assert "ix_review_queue_items_date_status_position" in index_names


def test_business_date_uses_asia_shanghai_boundary() -> None:
    assert business_date(datetime(2026, 7, 16, 16, 30, tzinfo=UTC)) == date(2026, 7, 17)


def test_default_plan_uses_five_qc_and_45_business_slots_without_priority_cap() -> None:
    factory = _factory()
    business_day = date(2026, 7, 16)
    with factory() as session:
        _seed_screenings(session, "priority", 35)
        _seed_screenings(session, "uncertain", 4)
        _seed_screenings(session, "excluded", 2)
        _seed_screenings(session, "standard", 20)
        session.flush()

        result = prepare_daily_review_queue(session, queue_date=business_day)
        session.commit()

        items = session.scalars(
            select(ReviewQueueItem).order_by(ReviewQueueItem.position)
        ).all()
        assert result["created"] == 50
        assert len(items) == 50
        assert [item.slot_type for item in items[:5]] == ["quality_control"] * 5
        assert [item.layer for item in items[:5]] == [
            "uncertain_review",
            "uncertain_review",
            "uncertain_review",
            "uncertain_review",
            "automatic_exclusion",
        ]
        assert sum(item.layer == "priority_review" for item in items) == 35
        assert result["backlog"] == 11


def test_qc_shortage_samples_exclusions_then_backfills_standard() -> None:
    factory = _factory()
    with factory() as session:
        _seed_screenings(session, "uncertain", 2)
        _seed_screenings(session, "excluded", 2)
        _seed_screenings(session, "standard", 50)
        session.flush()

        prepare_daily_review_queue(session, queue_date=date(2026, 7, 16))
        session.commit()
        qc = session.scalars(
            select(ReviewQueueItem)
            .where(ReviewQueueItem.slot_type == "quality_control")
            .order_by(ReviewQueueItem.position)
        ).all()

        assert [item.layer for item in qc] == [
            "uncertain_review",
            "uncertain_review",
            "automatic_exclusion",
            "automatic_exclusion",
            "standard_review",
        ]
        assert qc[2].exclusion_sample_reason == "明确机构账号"


def test_same_profile_merges_and_reviewed_candidate_does_not_reenter_pending() -> None:
    factory = _factory()
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="merged")
        reviewed = PublicProfile(platform="xhs", platform_user_id="reviewed")
        session.add_all([profile, reviewed])
        session.flush()
        session.add_all(
            [
                _screening(1, "priority", public_profile_id=profile.id),
                _screening(2, "standard", public_profile_id=profile.id),
                _screening(3, "priority", public_profile_id=reviewed.id, human_review_status="valid"),
            ]
        )
        session.flush()

        result = prepare_daily_review_queue(session, queue_date=date(2026, 7, 16))
        session.commit()

        items = session.scalars(select(ReviewQueueItem)).all()
        assert result["created"] == 1
        assert len(items) == 1
        assert items[0].candidate_key == f"profile:{profile.id}"
        assert items[0].screening_ids_json == [1, 2]


def test_rebuild_is_stable_and_continue_20_never_duplicates() -> None:
    factory = _factory()
    business_day = date(2026, 7, 16)
    with factory() as session:
        _seed_screenings(session, "standard", 5)
        _seed_screenings(session, "priority", 80)
        session.flush()

        first = prepare_daily_review_queue(session, queue_date=business_day)
        session.commit()
        first_items = session.scalars(
            select(ReviewQueueItem).order_by(ReviewQueueItem.position)
        ).all()
        first_identity = [(item.id, item.candidate_key, item.position) for item in first_items]

        second = prepare_daily_review_queue(session, queue_date=business_day)
        continued = extend_daily_review_queue(session, queue_date=business_day, additional=20)
        repeated = extend_daily_review_queue(session, queue_date=business_day, additional=20)
        session.commit()

        items = session.scalars(
            select(ReviewQueueItem).order_by(ReviewQueueItem.position)
        ).all()
        assert first["created"] == 50
        assert second["created"] == 0
        assert first_identity == [
            (item.id, item.candidate_key, item.position) for item in items[:50]
        ]
        assert continued["created"] == 20
        assert repeated["created"] == 15
        assert len(items) == 85
        assert len({item.candidate_key for item in items}) == 85


def test_priority_only_continuation_and_emergency_can_exceed_default_budget() -> None:
    factory = _factory()
    business_day = date(2026, 7, 16)
    with factory() as session:
        _seed_screenings(session, "standard", 55)
        _seed_screenings(session, "priority", 10)
        session.flush()
        prepare_daily_review_queue(session, queue_date=business_day)
        session.commit()

        priority_extension = extend_daily_review_queue(
            session,
            queue_date=business_day,
            additional=20,
            priority_only=True,
        )
        backlog_screening = session.scalar(
            select(LeadScreeningResult).where(LeadScreeningResult.source_entity_id == 1)
        )
        assert backlog_screening is not None
        emergency = append_emergency_candidate(
            session,
            backlog_screening.id,
            queue_date=business_day,
            reason="用户明确询问今天试听",
        )
        session.commit()

        items = session.scalars(select(ReviewQueueItem)).all()
        assert priority_extension["created"] == 0
        assert len(items) == 51
        assert emergency.is_emergency is True
        assert emergency.slot_type == "emergency"
        assert emergency.position == 51


def test_one_bad_candidate_is_visible_without_aborting_the_daily_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory()
    with factory() as session:
        _seed_screenings(session, "standard", 2)
        session.flush()

        from services import skill_run_report

        original = skill_run_report._group_view

        def fail_one(session_arg, run_id, key, screenings):
            if key == "source:comment:1":
                raise ValueError("malformed candidate")
            return original(session_arg, run_id, key, screenings)

        monkeypatch.setattr(skill_run_report, "_group_view", fail_one)

        result = prepare_daily_review_queue(session, queue_date=date(2026, 7, 16))

        assert result["created"] == 1
        assert result["errors"] == [
            {"candidate_key": "source:comment:1", "error": "malformed candidate"}
        ]


def _seed_screenings(session: Session, kind: str, count: int) -> None:
    start = int(session.scalar(select(LeadScreeningResult.id).order_by(LeadScreeningResult.id.desc())) or 0)
    for offset in range(1, count + 1):
        source_id = start + offset
        session.add(_screening(source_id, kind))
    session.flush()


def _screening(
    source_id: int,
    kind: str,
    *,
    public_profile_id: int | None = None,
    human_review_status: str | None = None,
) -> LeadScreeningResult:
    values = {
        "priority": {"intent_strength": "high", "confidence": 92, "review_status": "accepted"},
        "standard": {"intent_strength": "medium", "confidence": 76, "review_status": "accepted"},
        "uncertain": {
            "intent_strength": "low",
            "confidence": 45,
            "review_status": "needs_review",
            "qualification_reason_codes_json": ["location_unknown"],
        },
        "excluded": {
            "intent_strength": "medium",
            "confidence": 90,
            "review_status": "rejected",
            "qualification_reason_codes_json": ["institution_account"],
        },
    }[kind]
    return LeadScreeningResult(
        platform="xhs",
        source_entity_type="comment",
        source_entity_id=source_id,
        public_profile_id=public_profile_id,
        valuable=kind != "excluded",
        judgment_evidence_json=[f"evidence-{source_id}"],
        qualification_decision="rejected" if kind == "excluded" else "needs_review",
        human_review_status=human_review_status,
        **values,
    )
