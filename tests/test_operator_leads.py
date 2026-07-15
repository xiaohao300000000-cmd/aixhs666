from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from services.operator_leads import list_operator_leads, review_operator_lead
from storage.database import Base
from storage.models import Lead, LeadEvidence, LeadScreeningResult, PublicProfile


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed(session: Session) -> Lead:
    profile = PublicProfile(
        platform="xhs",
        platform_user_id="operator-user",
        display_name="福州家长",
        profile_url="https://example.com/user",
        region_text="福州",
    )
    session.add(profile)
    session.flush()
    lead = Lead(
        platform="xhs",
        public_profile_id=profile.id,
        status="needs_enrichment",
        region_text="福州",
        demand_type="考试培训",
        product="PET",
        intent_stage="比较机构",
        intent_score=82,
        information_completeness=70,
        recommended_next_step="人工确认",
    )
    session.add(lead)
    session.flush()
    session.add(
        LeadEvidence(
            lead_id=lead.id,
            source_entity_type="comment",
            source_entity_id=91,
            evidence_text="孩子 PET 压线没过，想找二刷冲刺班",
            score_contribution=35,
        )
    )
    session.add(
        LeadScreeningResult(
            platform="xhs",
            source_entity_type="comment",
            source_entity_id=91,
            public_profile_id=profile.id,
            valuable=True,
            demand_type="考试培训",
            intent_strength="high",
            confidence=88,
            judgment_evidence_json=["明确表达二刷需求"],
            context_json={"source_url": "https://example.com/note"},
            review_status="needs_review",
            qualification_decision="needs_review",
            qualification_reason_codes_json=["evidence_sufficient"],
            qualification_policy_version="campaign-v3",
        )
    )
    session.flush()
    return lead


def test_list_operator_leads_projects_queue_and_screening_context() -> None:
    factory = _factory()
    with factory() as session:
        lead = _seed(session)
        session.commit()

        payload = list_operator_leads(session, status_filter="pending", limit=20)

        assert payload["total"] == 1
        assert payload["items"][0]["id"] == lead.id
        assert payload["items"][0]["display_name"] == "福州家长"
        assert payload["items"][0]["evidence"][0]["text"] == "孩子 PET 压线没过，想找二刷冲刺班"
        assert payload["items"][0]["screening"]["confidence"] == 88
        assert payload["items"][0]["screening"]["policy_version"] == "campaign-v3"


def test_review_operator_lead_updates_fact_and_human_audit() -> None:
    factory = _factory()
    with factory() as session:
        lead = _seed(session)
        session.commit()

        result = review_operator_lead(
            session,
            lead.id,
            action="valid",
            reason="购买意图明确",
            owner_name="张兆尊",
            reviewer_id="ou_operator",
        )
        session.commit()

        screening = session.query(LeadScreeningResult).one()
        assert result["status"] == "qualified"
        assert result["owner_name"] == "张兆尊"
        assert screening.human_review_status == "valid"
        assert screening.qualification_human_reason == "购买意图明确"
        assert screening.human_reviewer_id == "ou_operator"
        assert isinstance(screening.human_reviewed_at, datetime)
        assert screening.human_reviewed_at.replace(tzinfo=UTC).tzinfo is not None


def test_review_operator_lead_requires_reason_for_watch_and_invalid() -> None:
    factory = _factory()
    with factory() as session:
        lead = _seed(session)
        session.commit()

        try:
            review_operator_lead(session, lead.id, action="invalid", reason=None)
        except ValueError as exc:
            assert "reason is required" in str(exc)
        else:
            raise AssertionError("invalid review without reason should fail")

        watched = review_operator_lead(session, lead.id, action="watch", reason="等待家长补充预算")
        assert watched["status"] == "watch"

