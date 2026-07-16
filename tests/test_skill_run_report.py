from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from services.skill_run_report import (
    build_candidates_from_screenings,
    classify_screening,
    rebuild_skill_run_report,
)
from storage.database import Base
from storage.models import Lead, LeadScreeningResult, PublicProfile, SkillRun


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_skill_run_business_report_is_separate_from_raw_summary_and_checkpoint() -> None:
    factory = _factory()
    with factory() as session:
        run = SkillRun(
            skill_key="screen_historical_leads",
            skill_version=1,
            status="succeeded",
            checkpoint_json={"screening_ids": [1, 2]},
            result_summary_json={"processed_count": 2, "legacy_key": "preserved"},
            business_report_json={"conclusion": "发现 2 条候选"},
        )
        session.add(run)
        session.commit()

        stored = session.scalar(select(SkillRun))
        assert stored is not None
        assert stored.business_report_json == {"conclusion": "发现 2 条候选"}
        assert stored.result_summary_json == {"processed_count": 2, "legacy_key": "preserved"}
        assert stored.checkpoint_json == {"screening_ids": [1, 2]}


def test_soft_uncertainty_signals_never_automatically_exclude() -> None:
    screening = LeadScreeningResult(
        platform="xhs",
        source_entity_type="comment",
        source_entity_id=1,
        valuable=False,
        review_status="rejected",
        intent_strength="low",
        confidence=25,
        qualification_decision="rejected",
        qualification_reason_codes_json=["model_uncertain", "location_unknown", "intent_too_low"],
    )

    classification = classify_screening(screening)

    assert classification.layer == "uncertain_review"
    assert classification.hard_exclusion_reason is None


def test_only_explicit_hard_reason_is_automatic_exclusion() -> None:
    screening = LeadScreeningResult(
        platform="xhs",
        source_entity_type="content",
        source_entity_id=2,
        valuable=False,
        review_status="rejected",
        confidence=95,
        qualification_decision="rejected",
        qualification_reason_codes_json=["institution_account"],
    )

    classification = classify_screening(screening)

    assert classification.layer == "automatic_exclusion"
    assert classification.hard_exclusion_reason == "明确机构账号"


def test_report_merges_same_profile_screenings_and_preserves_raw_audit_facts() -> None:
    factory = _factory()
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="same-person")
        session.add(profile)
        session.flush()
        lead = Lead(platform="xhs", public_profile_id=profile.id, status="needs_enrichment")
        session.add(lead)
        screenings = [
            LeadScreeningResult(
                platform="xhs",
                source_entity_type="comment",
                source_entity_id=101,
                public_profile_id=profile.id,
                valuable=True,
                review_status="accepted",
                intent_strength="high",
                confidence=92,
                judgment_evidence_json=["明确询问 PET 二刷课程"],
                qualification_decision="qualified",
            ),
            LeadScreeningResult(
                platform="xhs",
                source_entity_type="comment",
                source_entity_id=102,
                public_profile_id=profile.id,
                valuable=True,
                review_status="needs_review",
                intent_strength="medium",
                confidence=72,
                judgment_evidence_json=["比较不同机构"],
                qualification_decision="needs_review",
                qualification_reason_codes_json=["location_unknown"],
            ),
        ]
        session.add_all(screenings)
        session.flush()
        raw_summary = {"processed_count": 2, "legacy_key": "preserved"}
        raw_checkpoint = {"screening_ids": [item.id for item in screenings], "next_index": 2}
        run = SkillRun(
            skill_key="screen_historical_leads",
            skill_version=1,
            status="succeeded",
            checkpoint_json=raw_checkpoint,
            result_summary_json=raw_summary,
        )
        session.add(run)
        session.flush()

        first = rebuild_skill_run_report(session, run.id)
        second = rebuild_skill_run_report(session, run.id)
        session.commit()

        assert first == second
        assert first["counts"] == {
            "priority_review": 1,
            "standard_review": 0,
            "uncertain_review": 0,
            "automatic_exclusion": 0,
        }
        assert len(first["candidates"]) == 1
        assert first["candidates"][0]["candidate_key"] == f"profile:{profile.id}"
        assert first["candidates"][0]["screening_ids"] == [screenings[0].id, screenings[1].id]
        assert first["candidates"][0]["lead_id"] == lead.id
        assert run.result_summary_json == raw_summary
        assert run.checkpoint_json == raw_checkpoint


def test_report_explains_when_run_has_no_candidates() -> None:
    factory = _factory()
    with factory() as session:
        run = SkillRun(
            skill_key="screen_historical_leads",
            skill_version=1,
            status="succeeded",
            checkpoint_json={"screening_ids": []},
            result_summary_json={"processed_count": 0},
        )
        session.add(run)
        session.flush()

        report = rebuild_skill_run_report(session, run.id)

        assert report["conclusion"] == "本次运行已完成，但没有发现需要进入人工审核的候选。"
        assert report["queue"]["prepared"] == 0
        assert report["next_action"]["label"] == "查看运行详情"


def test_candidate_sort_prefers_stronger_intent_before_confidence_ties() -> None:
    factory = _factory()
    now = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    with factory() as session:
        stronger_but_older = _screening(
            10,
            intent_strength="high",
            confidence=90,
            updated_at=now,
        )
        weaker_but_newer = _screening(
            20,
            intent_strength="medium",
            confidence=90,
            updated_at=now + timedelta(hours=1),
        )
        session.add_all([stronger_but_older, weaker_but_newer])
        session.flush()

        candidates = build_candidates_from_screenings(
            session,
            [weaker_but_newer, stronger_but_older],
        )

        assert [item["candidate_key"] for item in candidates] == [
            "source:comment:10",
            "source:comment:20",
        ]


def test_candidate_sort_prefers_newer_update_before_stable_id_ties() -> None:
    factory = _factory()
    now = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    with factory() as session:
        newer_with_smaller_id = _screening(
            10,
            intent_strength="medium",
            confidence=90,
            updated_at=now + timedelta(hours=1),
        )
        older_with_larger_id = _screening(
            20,
            intent_strength="medium",
            confidence=90,
            updated_at=now,
        )
        session.add_all([newer_with_smaller_id, older_with_larger_id])
        session.flush()

        candidates = build_candidates_from_screenings(
            session,
            [older_with_larger_id, newer_with_smaller_id],
        )

        assert [item["candidate_key"] for item in candidates] == [
            "source:comment:10",
            "source:comment:20",
        ]
        assert candidates[0]["updated_at"] == "2026-07-16T09:00:00+00:00"


def test_candidate_sort_uses_stable_id_and_key_as_repeatable_final_fallback() -> None:
    factory = _factory()
    updated_at = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    with factory() as session:
        first_inserted = _screening(
            30,
            intent_strength="medium",
            confidence=90,
            updated_at=updated_at,
        )
        second_inserted = _screening(
            10,
            intent_strength="medium",
            confidence=90,
            updated_at=updated_at,
        )
        session.add_all([first_inserted, second_inserted])
        session.flush()

        first = build_candidates_from_screenings(
            session,
            [first_inserted, second_inserted],
        )
        second = build_candidates_from_screenings(
            session,
            [second_inserted, first_inserted],
        )

        assert [item["candidate_key"] for item in first] == [
            "source:comment:10",
            "source:comment:30",
        ]
        assert [item["candidate_key"] for item in second] == [
            item["candidate_key"] for item in first
        ]


def _screening(
    source_id: int,
    *,
    intent_strength: str,
    confidence: int,
    updated_at: datetime,
) -> LeadScreeningResult:
    return LeadScreeningResult(
        platform="xhs",
        source_entity_type="comment",
        source_entity_id=source_id,
        valuable=True,
        review_status="accepted",
        intent_strength=intent_strength,
        confidence=confidence,
        judgment_evidence_json=[f"evidence-{source_id}"],
        qualification_decision="qualified",
        updated_at=updated_at,
    )
