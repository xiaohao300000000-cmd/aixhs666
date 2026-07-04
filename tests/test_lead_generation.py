from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.cli import main as cli_main
from services.lead_generation import generate_leads_from_history, generate_leads_for_profiles, rebuild_auto_leads_from_history
from storage.database import Base
from storage.models import Comment, Content, EnrichmentTask, Lead, LeadEvidence, PublicProfile


@pytest.fixture()
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    yield SessionLocal
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_lead_models_persist_business_objects(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        profile = _profile(region_text="福州")
        session.add(profile)
        session.flush()
        lead = Lead(
            platform="xhs",
            public_profile_id=profile.id,
            status="needs_enrichment",
            region_text="福州",
            demand_type="exam_retry",
            product="PET",
            intent_stage="recovery",
            intent_score=74,
            information_completeness=60,
            known_info_json={"region": "福州", "product": "PET"},
            missing_info_json=["contact"],
            recommended_next_step="补充公开联系方式后人工判断是否可跟进",
        )
        session.add(lead)
        session.flush()
        evidence = LeadEvidence(
            lead_id=lead.id,
            source_entity_type="comment",
            source_entity_id=12,
            evidence_text="孩子 PET 压线没过，想找二刷冲刺班",
            demand_type="exam_retry",
            intent_stage="recovery",
            score_contribution=74,
        )
        task = EnrichmentTask(
            lead_id=lead.id,
            task_type="find_contact",
            status="pending",
            reason="缺少公开联系方式",
        )
        session.add_all([evidence, task])
        session.commit()

    with factory() as session:
        saved = session.scalar(select(Lead).where(Lead.platform == "xhs"))
        assert saved is not None
        assert saved.profile.display_name == "福州家长"
        assert saved.evidence_items[0].evidence_text.startswith("孩子 PET")
        assert saved.enrichment_tasks[0].task_type == "find_contact"


def test_generate_leads_from_history_merges_profile_evidence(factory: sessionmaker[Session]) -> None:
    profile_id = _seed_ket_pet_history(factory)

    with factory() as session:
        result = generate_leads_from_history(session)
        session.commit()

    assert result.leads_created == 1
    assert result.evidence_created == 2
    assert result.enrichment_tasks_created >= 1
    with factory() as session:
        lead = session.scalar(select(Lead).where(Lead.public_profile_id == profile_id))
        assert lead is not None
        assert lead.product == "PET"
        assert lead.demand_type == "exam_retry"
        assert lead.intent_score >= 70
        assert lead.status in {"needs_enrichment", "qualified"}
        assert len(lead.evidence_items) == 2
        assert lead.known_info_json["region"] == "福州"
        assert "contact" in lead.missing_info_json


def test_generate_leads_is_idempotent_and_preserves_manual_status(factory: sessionmaker[Session]) -> None:
    profile_id = _seed_ket_pet_history(factory)

    with factory() as session:
        first = generate_leads_from_history(session)
        lead = session.scalar(select(Lead).where(Lead.public_profile_id == profile_id))
        assert lead is not None
        lead.status = "handled"
        session.commit()
    with factory() as session:
        second = generate_leads_from_history(session)
        session.commit()

    assert first.leads_created == 1
    assert second.leads_created == 0
    with factory() as session:
        lead = session.scalar(select(Lead).where(Lead.public_profile_id == profile_id))
        assert lead is not None
        assert lead.status == "handled"
        assert session.query(Lead).count() == 1
        assert session.query(LeadEvidence).count() == 2
        task_types = [task.task_type for task in session.scalars(select(EnrichmentTask)).all()]
        assert sorted(task_types) == sorted(set(task_types))


def test_rebuild_auto_leads_preserves_ignored_manual_leads(factory: sessionmaker[Session]) -> None:
    profile_id = _seed_ket_pet_history(factory)
    with factory() as session:
        generate_leads_from_history(session)
        lead = session.scalar(select(Lead).where(Lead.public_profile_id == profile_id))
        assert lead is not None
        lead.status = "ignored"
        session.commit()

    with factory() as session:
        result = rebuild_auto_leads_from_history(session)
        session.commit()

    assert result.leads_created == 0
    with factory() as session:
        lead = session.scalar(select(Lead).where(Lead.public_profile_id == profile_id))
        assert lead is not None
        assert lead.status == "ignored"
        assert session.query(LeadEvidence).count() == 2


def test_rebuild_auto_leads_preserves_qualified_manual_leads(factory: sessionmaker[Session]) -> None:
    profile_id = _seed_ket_pet_history(factory)
    with factory() as session:
        generate_leads_from_history(session)
        lead = session.scalar(select(Lead).where(Lead.public_profile_id == profile_id))
        assert lead is not None
        lead.status = "qualified"
        session.commit()

    with factory() as session:
        result = rebuild_auto_leads_from_history(session)
        session.commit()

    assert result.leads_created == 0
    with factory() as session:
        lead = session.scalar(select(Lead).where(Lead.public_profile_id == profile_id))
        assert lead is not None
        assert lead.status == "qualified"
        assert session.query(LeadEvidence).count() == 2


def test_generate_leads_for_profiles_limits_scope(factory: sessionmaker[Session]) -> None:
    target_profile_id = _seed_ket_pet_history(factory)
    with factory() as session:
        other = _profile(platform_user_id="other", display_name="路人")
        session.add(other)
        session.flush()
        content = Content(
            platform="xhs",
            platform_content_id="other-note",
            content_type="note",
            author_profile_id=other.id,
            title="KET 备考",
            body_text="想问 KET 暑假班怎么选",
        )
        session.add(content)
        session.commit()
        other_id = other.id

    with factory() as session:
        result = generate_leads_for_profiles(session, {target_profile_id})
        session.commit()

    assert result.leads_created == 1
    with factory() as session:
        assert session.scalar(select(Lead).where(Lead.public_profile_id == target_profile_id)) is not None
        assert session.scalar(select(Lead).where(Lead.public_profile_id == other_id)) is None


def test_advice_content_without_user_need_does_not_create_lead(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        profile = _profile(platform_user_id="teacher-1", display_name="英语老师")
        session.add(profile)
        session.flush()
        session.add(
            Content(
                platform="xhs",
                platform_content_id="teacher-note",
                content_type="note",
                author_profile_id=profile.id,
                title="教了9年 PET 总结出来的十条建议",
                body_text="PET 备考时间不建议超过一年，希望给迷茫的家长一些方向。",
            )
        )
        session.commit()

    with factory() as session:
        result = generate_leads_from_history(session)
        session.commit()

    assert result.leads_created == 0
    with factory() as session:
        assert session.query(Lead).count() == 0


def test_guide_content_with_rhetorical_question_and_fee_does_not_create_lead(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        profile = _profile(platform_user_id="teacher-2", display_name="备考博主")
        session.add(profile)
        session.flush()
        session.add(
            Content(
                platform="xhs",
                platform_content_id="guide-note",
                content_type="note",
                author_profile_id=profile.id,
                title="除了雅思你可能有更优解",
                body_text=(
                    "很多朋友想考一份语言证书，但雅思真的适配所有人吗？"
                    "费用：KET约1150元，PET约1350元。"
                    "刷PET真题有利于重塑阅读逻辑。#KET #PET"
                ),
            )
        )
        session.commit()

    with factory() as session:
        result = generate_leads_from_history(session)
        session.commit()

    assert result.leads_created == 0
    with factory() as session:
        assert session.query(Lead).count() == 0


def test_parent_experience_content_without_request_does_not_create_lead(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        profile = _profile(platform_user_id="parent-blogger", display_name="经验家长")
        session.add(profile)
        session.flush()
        session.add(
            Content(
                platform="xhs",
                platform_content_id="parent-guide",
                content_type="note",
                author_profile_id=profile.id,
                title="因为儿子 KET 过了，普及一下备考强度",
                body_text="三年级普娃去年拿下 KET，整理备考顺序、教材和学习建议给大家参考。",
            )
        )
        session.commit()

    with factory() as session:
        result = generate_leads_from_history(session)
        session.commit()

    assert result.leads_created == 0
    with factory() as session:
        assert session.query(Lead).count() == 0


def test_teacher_or_provider_content_does_not_create_lead(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        profile = _profile(platform_user_id="provider", display_name="课程老师")
        session.add(profile)
        session.flush()
        session.add_all(
            [
                Content(
                    platform="xhs",
                    platform_content_id="provider-note-1",
                    content_type="note",
                    author_profile_id=profile.id,
                    title="老天奶！差1分没过 KET",
                    body_text="上周有个孩子差1分没过 KET，一生气整理了 KET 扣分点。",
                ),
                Content(
                    platform="xhs",
                    platform_content_id="provider-note-2",
                    content_type="note",
                    author_profile_id=profile.id,
                    title="暑假托管机构问我能不能教小学 KET",
                    body_text="机构问我能不能教 KET 小班教学任务，想请懂行的人给点教学大纲建议。",
                ),
            ]
        )
        session.commit()

    with factory() as session:
        result = generate_leads_from_history(session)
        session.commit()

    assert result.leads_created == 0
    with factory() as session:
        assert session.query(Lead).count() == 0


def test_provider_and_resource_comments_do_not_create_leads(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        provider = _profile(platform_user_id="provider-comment", display_name="独立老师")
        resource_user = _profile(platform_user_id="resource-user", display_name="资料用户")
        session.add_all([provider, resource_user])
        session.flush()
        content = Content(
            platform="xhs",
            platform_content_id="source-note",
            content_type="note",
            title="PET 备考经验",
            body_text="PET 备考资料整理。",
        )
        session.add(content)
        session.flush()
        session.add_all(
            [
                Comment(
                    platform="xhs",
                    platform_comment_id="provider-comment",
                    content_id=content.id,
                    author_profile_id=provider.id,
                    body_text="我是独立老师，家长总逼着我带 KET/PET，生源也因此丢了一些。",
                ),
                Comment(
                    platform="xhs",
                    platform_comment_id="resource-comment",
                    content_id=content.id,
                    author_profile_id=resource_user.id,
                    body_text="PET核心词汇能分享吗？",
                ),
            ]
        )
        session.commit()

    with factory() as session:
        result = generate_leads_from_history(session)
        session.commit()

    assert result.leads_created == 0
    with factory() as session:
        assert session.query(Lead).count() == 0


def test_institution_promo_and_no_exam_comments_do_not_create_leads(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        promo_user = _profile(platform_user_id="promo-user", display_name="推广用户")
        no_need_user = _profile(platform_user_id="no-need-user", display_name="不报班家长")
        session.add_all([promo_user, no_need_user])
        session.flush()
        content = Content(
            platform="xhs",
            platform_content_id="comment-source",
            content_type="note",
            title="PET 讨论",
            body_text="PET 家长讨论区。",
        )
        session.add(content)
        session.flush()
        session.add_all(
            [
                Comment(
                    platform="xhs",
                    platform_comment_id="promo-comment",
                    content_id=content.id,
                    author_profile_id=promo_user.id,
                    body_text=(
                        "我家三娃家庭，大娃当年就是跟着专业机构系统规划KET/PET，"
                        "靠谱机构帮孩子避开盲目刷题，现在二娃也在同团队稳步规划。"
                    ),
                ),
                Comment(
                    platform="xhs",
                    platform_comment_id="no-need-comment",
                    content_id=content.id,
                    author_profile_id=no_need_user.id,
                    body_text="家里没报英文班，节约钱和时间，没有报班，不为考试，什么pet都无所谓。",
                ),
            ]
        )
        session.commit()

    with factory() as session:
        result = generate_leads_from_history(session)
        session.commit()

    assert result.leads_created == 0
    with factory() as session:
        assert session.query(Lead).count() == 0


def test_parent_followup_comments_create_leads(factory: sessionmaker[Session]) -> None:
    comments = (
        "请问PET阅读怎么提高呢？",
        "老师，线上带PET吗？",
        "请问考完pet您给孩子报什么课程了么？",
    )
    with factory() as session:
        content = Content(
            platform="xhs",
            platform_content_id="parent-question-source",
            content_type="note",
            title="PET 家长问答",
            body_text="PET 讨论区。",
        )
        session.add(content)
        session.flush()
        for index, body_text in enumerate(comments, start=1):
            profile = _profile(platform_user_id=f"parent-question-{index}", display_name=f"家长{index}")
            session.add(profile)
            session.flush()
            session.add(
                Comment(
                    platform="xhs",
                    platform_comment_id=f"parent-question-comment-{index}",
                    content_id=content.id,
                    author_profile_id=profile.id,
                    body_text=body_text,
                )
            )
        session.commit()

    with factory() as session:
        result = generate_leads_from_history(session)
        session.commit()

    assert result.leads_created == 3
    assert result.evidence_created == 3
    with factory() as session:
        assert session.query(Lead).count() == 3


def test_generate_leads_persists_intent_metadata_and_fallback_stage(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        profile = _profile(platform_user_id="intent-fallback", display_name="跟进家长")
        session.add(profile)
        session.flush()
        content = Content(
            platform="xhs",
            platform_content_id="intent-fallback-note",
            content_type="note",
            title="PET 家长交流",
            body_text="孩子 PET 学习交流。",
        )
        session.add(content)
        session.flush()
        session.add(
            Comment(
                platform="xhs",
                platform_comment_id="intent-fallback-comment",
                content_id=content.id,
                author_profile_id=profile.id,
                body_text="老师，线上带PET",
            )
        )
        session.commit()

    with factory() as session:
        result = generate_leads_from_history(session)
        session.commit()

    assert result.leads_created == 1
    with factory() as session:
        lead = session.scalar(select(Lead).where(Lead.public_profile_id == profile.id))
        assert lead is not None
        assert lead.demand_type == "planning"
        assert lead.intent_stage == "planning"
        assert lead.known_info_json["human_need"] == "家长在咨询KET/PET相关学习安排"
        assert lead.known_info_json["recommendation_reason"]
        assert lead.known_info_json["suggested_next_step"] == lead.recommended_next_step
        for token in ("exam_retry", "institution", "course", "high", "medium"):
            assert token not in lead.known_info_json["recommendation_reason"]


def test_leads_backfill_cli_outputs_generation_counts(
    factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_ket_pet_history(factory)
    monkeypatch.setattr("apps.cli.SessionLocal", factory)

    exit_code = cli_main(["--json", "leads-backfill"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"leads_created": 1' in output
    assert '"evidence_created": 2' in output


def _seed_ket_pet_history(factory: sessionmaker[Session]) -> int:
    now = datetime.now(UTC)
    with factory() as session:
        profile = _profile(region_text="福州")
        session.add(profile)
        session.flush()
        content = Content(
            platform="xhs",
            platform_content_id="note-1",
            content_type="note",
            author_profile_id=profile.id,
            title="福州 PET 二刷求推荐",
            body_text="孩子 PET 压线没过，想找暑假冲刺班，哪家机构靠谱？",
            region_text="福州",
            published_at=now - timedelta(hours=2),
            url="https://example.test/note-1",
        )
        session.add(content)
        session.flush()
        comment = Comment(
            platform="xhs",
            platform_comment_id="comment-1",
            content_id=content.id,
            author_profile_id=profile.id,
            body_text="价格多少，可以先试听吗？",
            published_at=now - timedelta(hours=1),
        )
        session.add(comment)
        session.commit()
        return profile.id


def _profile(
    *,
    platform_user_id: str = "u-1",
    display_name: str = "福州家长",
    region_text: str | None = None,
) -> PublicProfile:
    return PublicProfile(
        platform="xhs",
        platform_user_id=platform_user_id,
        display_name=display_name,
        profile_url=f"https://example.test/user/{platform_user_id}",
        region_text=region_text,
    )
