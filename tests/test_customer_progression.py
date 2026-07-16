from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from services.customer_progression import progress_operator_lead
from services.daily_review_queue import review_queue_progress
from storage.database import Base
from storage.models import (
    CollectionTask,
    Comment,
    Content,
    CustomerFollowupRecord,
    CustomerTimelineEvent,
    Lead,
    LeadScreeningResult,
    PublicProfile,
    ReviewQueueItem,
)


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed(session: Session) -> Lead:
    profile = PublicProfile(platform="xhs", platform_user_id="progression-user", display_name="PET 家长")
    session.add(profile)
    session.flush()
    lead = Lead(platform="xhs", public_profile_id=profile.id, status="needs_enrichment")
    session.add(lead)
    session.flush()
    session.add(
        LeadScreeningResult(
            platform="xhs",
            source_entity_type="comment",
            source_entity_id=501,
            public_profile_id=profile.id,
            review_status="needs_review",
            qualification_decision="needs_review",
        )
    )
    session.commit()
    return lead


def test_promote_sets_customer_facts_and_timeline() -> None:
    factory = _factory()
    with factory() as session:
        lead = _seed(session)

        result = progress_operator_lead(
            session,
            lead.id,
            action="promote",
            reason="需求明确",
            reviewer_id="operator-1",
            idempotency_key="review-1",
        )
        session.commit()

        assert result.customer_id == lead.id
        assert result.customer_stage == "awaiting_first_contact"
        assert result.next_action == "prepare_public_reply"
        assert result.timeline_event_type == "candidate_promoted"
        assert result.crm_sync_status == "pending"
        assert result.followup_record_id is not None
        assert lead.status == "qualified"
        assert lead.followup_status == "pending"
        assert lead.crm_stage == "awaiting_first_contact"
        assert lead.crm_sync_version == 1
        assert lead.recommended_next_step == "准备首次公开回复"
        event = session.scalar(select(CustomerTimelineEvent))
        assert event is not None
        assert event.event_key == "customer-progression:review-1"
        followup = session.scalar(select(CustomerFollowupRecord))
        assert followup is not None
        assert followup.event_key == "customer-followup:customer-progression:review-1:first-contact"
        assert followup.action_type == "待首次联系"
        assert followup.result == "pending"


def test_duplicate_progression_reuses_timeline_event() -> None:
    factory = _factory()
    with factory() as session:
        lead = _seed(session)
        first = progress_operator_lead(
            session,
            lead.id,
            action="promote",
            reason="需求明确",
            reviewer_id="operator-1",
            idempotency_key="review-1",
        )
        session.commit()
        second = progress_operator_lead(
            session,
            lead.id,
            action="promote",
            reason="需求明确",
            reviewer_id="operator-1",
            idempotency_key="review-1",
        )

        assert second.timeline_event_id == first.timeline_event_id
        assert second.idempotent_replay is True
        assert len(session.scalars(select(CustomerTimelineEvent)).all()) == 1
        assert len(session.scalars(select(CustomerFollowupRecord)).all()) == 1
        assert lead.crm_sync_version == 1


def test_promote_eligible_comment_queues_one_draft_prepare_task() -> None:
    factory = _factory()
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="eligible-comment")
        session.add(profile)
        session.flush()
        content = Content(platform="xhs", platform_content_id="note-1", content_type="note", author_profile_id=profile.id)
        session.add(content)
        session.flush()
        comment = Comment(platform="xhs", platform_comment_id="comment-1", content_id=content.id, author_profile_id=profile.id)
        lead = Lead(platform="xhs", public_profile_id=profile.id, status="needs_enrichment")
        session.add_all([comment, lead])
        session.flush()
        screening = LeadScreeningResult(
            platform="xhs",
            source_entity_type="comment",
            source_entity_id=comment.id,
            content_id=content.id,
            comment_id=comment.id,
            public_profile_id=profile.id,
            review_status="accepted",
            human_review_status="valid",
        )
        session.add(screening)
        session.commit()

        progress_operator_lead(session, lead.id, action="promote", idempotency_key="eligible-promote")
        session.commit()
        progress_operator_lead(session, lead.id, action="promote", idempotency_key="eligible-promote")
        session.commit()

        tasks = session.scalars(select(CollectionTask).where(CollectionTask.task_type == "comment_reply_prepare")).all()
        assert len(tasks) == 1
        assert tasks[0].target_id == str(lead.id)
        assert tasks[0].payload_json["screening_id"] == screening.id


def test_progression_completes_matching_queue_position_exactly_once() -> None:
    factory = _factory()
    business_day = date(2026, 7, 16)
    with factory() as session:
        lead = _seed(session)
        screening = session.scalar(select(LeadScreeningResult))
        assert screening is not None
        item = ReviewQueueItem(
            queue_date=business_day,
            candidate_key=f"profile:{lead.public_profile_id}",
            representative_screening_id=screening.id,
            lead_id=lead.id,
            public_profile_id=lead.public_profile_id,
            screening_ids_json=[screening.id],
            layer="priority_review",
            slot_type="business",
            priority_rank=492,
            position=1,
            status="pending",
            is_emergency=False,
            queue_reason="强需求信号",
        )
        session.add(item)
        session.commit()

        first = progress_operator_lead(
            session,
            lead.id,
            action="promote",
            reason="需求明确",
            reviewer_id="operator-1",
            idempotency_key="queue-review-1",
        )
        session.commit()
        second = progress_operator_lead(
            session,
            lead.id,
            action="promote",
            reason="需求明确",
            reviewer_id="operator-1",
            idempotency_key="queue-review-1",
        )
        session.commit()

        assert first.idempotent_replay is False
        assert second.idempotent_replay is True
        assert item.status == "completed"
        assert item.human_decision == "promote"
        assert item.reviewed_at is not None
        assert review_queue_progress(session, queue_date=business_day) == {
            "completed": 1,
            "target": 1,
            "pending": 0,
            "quality_control": 0,
        }


def test_defer_requires_reason_and_future_time() -> None:
    factory = _factory()
    with factory() as session:
        lead = _seed(session)
        with pytest.raises(ValueError, match="reason is required"):
            progress_operator_lead(session, lead.id, action="defer", idempotency_key="defer-1")
        with pytest.raises(ValueError, match="defer_until is required"):
            progress_operator_lead(
                session,
                lead.id,
                action="defer",
                reason="等待新证据",
                idempotency_key="defer-2",
            )

        defer_until = datetime.now(UTC) + timedelta(days=3)
        result = progress_operator_lead(
            session,
            lead.id,
            action="defer",
            reason="等待新证据",
            idempotency_key="defer-3",
            defer_until=defer_until,
        )
        assert result.customer_stage == "deferred"
        assert lead.next_followup_at == defer_until
