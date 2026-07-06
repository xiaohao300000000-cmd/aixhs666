from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.cli import main as cli_main
from services.llm_lead_screening import (
    LeadScreeningContext,
    LLMLeadScreeningDecision,
    run_llm_lead_screening,
)
from storage.database import Base
from storage.models import Comment, Content, Lead, LeadEvidence, LeadScreeningResult, PublicProfile


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


class FakeLeadScreeningClient:
    def __init__(self, decisions: list[LLMLeadScreeningDecision]) -> None:
        self.decisions = decisions
        self.contexts: list[LeadScreeningContext] = []

    def screen(self, context: LeadScreeningContext) -> LLMLeadScreeningDecision:
        self.contexts.append(context)
        return self.decisions.pop(0)


def test_llm_screening_uses_post_comment_and_parent_context(factory: sessionmaker[Session]) -> None:
    comment_id = _seed_comment_thread(factory)
    client = FakeLeadScreeningClient(
        [
            LLMLeadScreeningDecision(
                valuable=True,
                demand_type="price",
                intent_strength="high",
                judgment_evidence=("当前评论询问价格和试听",),
                confidence=0.86,
                reason="家长已经在比较课程成本和体验课。",
            )
        ]
    )

    with factory() as session:
        result = run_llm_lead_screening(
            session,
            client=client,
            source_entity_types={"comment"},
            source_entity_ids={comment_id},
        )
        session.commit()

    assert result.screened == 1
    assert client.contexts[0].post_title == "PET 二刷怎么准备"
    assert client.contexts[0].post_body == "孩子 PET 压线后，家长都在聊冲刺班。"
    assert client.contexts[0].current_comment == "价格多少，可以先试听吗？"
    assert client.contexts[0].parent_comment == "福州哪家 PET 冲刺班靠谱？"

    with factory() as session:
        screening = session.scalar(select(LeadScreeningResult).where(LeadScreeningResult.comment_id == comment_id))
        assert screening is not None
        assert screening.valuable is True
        assert screening.demand_type == "price"
        assert screening.intent_strength == "high"
        assert screening.confidence == 86
        assert screening.judgment_evidence_json == ["当前评论询问价格和试听"]

        lead = session.scalar(select(Lead))
        assert lead is not None
        assert lead.status == "qualified"
        assert lead.demand_type == "price"
        assert lead.intent_score == 86
        assert lead.known_info_json["llm_screening"]["confidence"] == 0.86

        evidence = session.scalar(select(LeadEvidence))
        assert evidence is not None
        assert evidence.comment_id == comment_id
        assert evidence.evidence_text == "价格多少，可以先试听吗？"


def test_uncertain_llm_result_is_saved_for_manual_review(factory: sessionmaker[Session]) -> None:
    _seed_single_comment(factory, body_text="PET 有必要报班吗？")
    client = FakeLeadScreeningClient(
        [
            LLMLeadScreeningDecision(
                valuable=False,
                demand_type="enrollment",
                intent_strength="medium",
                judgment_evidence=("问题像是咨询报班，但语境不足",),
                confidence=0.48,
                reason="置信度不足，需要人工确认。",
            )
        ]
    )

    with factory() as session:
        result = run_llm_lead_screening(session, client=client, source_entity_types={"comment"})
        session.commit()

    assert result.screened == 1
    assert result.needs_review == 1
    with factory() as session:
        lead = session.scalar(select(Lead))
        assert lead is not None
        assert lead.status == "needs_review"
        assert lead.known_info_json["llm_screening"]["review_status"] == "needs_review"
        assert session.scalar(select(LeadScreeningResult)).review_status == "needs_review"


def test_rules_filter_duplicate_and_garbage_text_before_llm(factory: sessionmaker[Session]) -> None:
    _seed_duplicate_and_garbage_comments(factory)
    client = FakeLeadScreeningClient(
        [
            LLMLeadScreeningDecision(
                valuable=True,
                demand_type="institution",
                intent_strength="medium",
                judgment_evidence=("询问机构推荐",),
                confidence=0.72,
                reason="有明确找机构需求。",
            )
        ]
    )

    with factory() as session:
        result = run_llm_lead_screening(session, client=client, source_entity_types={"comment"})
        session.commit()

    assert result.candidates == 3
    assert result.filtered == 2
    assert result.screened == 1
    assert len(client.contexts) == 1
    assert client.contexts[0].current_comment == "PET 哪家机构比较靠谱？"


def test_screening_without_profile_saves_result_without_lead(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        session.add(
            Content(
                platform="xhs",
                platform_content_id="note-no-profile",
                content_type="note",
                title="PET 冲刺班求推荐",
                body_text="孩子二刷 PET，想找冲刺班。",
            )
        )
        session.commit()
    client = FakeLeadScreeningClient(
        [
            LLMLeadScreeningDecision(
                valuable=True,
                demand_type="institution",
                intent_strength="high",
                judgment_evidence=("发帖人在找冲刺班",),
                confidence=0.82,
                reason="有明确需求但作者资料缺失。",
            )
        ]
    )

    with factory() as session:
        result = run_llm_lead_screening(session, client=client, source_entity_types={"content"})
        session.commit()

    assert result.screened == 1
    assert result.accepted == 1
    assert result.leads_created == 0
    with factory() as session:
        assert session.scalar(select(LeadScreeningResult)).review_status == "accepted"
        assert session.scalar(select(Lead)) is None


def test_llm_screening_cli_writes_database_results(
    factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_single_comment(factory, body_text="PET 冲刺班多少钱，可以试听吗？")

    class FakeDefaultClient(FakeLeadScreeningClient):
        def __init__(self) -> None:
            super().__init__(
                [
                    LLMLeadScreeningDecision(
                        valuable=True,
                        demand_type="price",
                        intent_strength="high",
                        judgment_evidence=("询问价格和试听",),
                        confidence=0.9,
                        reason="明确询价。",
                    )
                ]
            )

    monkeypatch.setattr("apps.cli.SessionLocal", factory)
    monkeypatch.setattr("services.llm_lead_screening.OpenAICompatibleLeadScreeningClient", FakeDefaultClient)

    exit_code = cli_main(["--json", "leads-llm-screen", "--source", "comment"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"screened": 1' in output
    with factory() as session:
        assert session.scalar(select(LeadScreeningResult)).demand_type == "price"
        assert session.scalar(select(Lead)).status == "qualified"


def _seed_comment_thread(factory: sessionmaker[Session]) -> int:
    now = datetime.now(UTC)
    with factory() as session:
        author = _profile("author", "作者")
        parent_user = _profile("parent", "家长A")
        reply_user = _profile("reply", "家长B")
        session.add_all([author, parent_user, reply_user])
        session.flush()
        content = Content(
            platform="xhs",
            platform_content_id="note-thread",
            content_type="note",
            author_profile_id=author.id,
            title="PET 二刷怎么准备",
            body_text="孩子 PET 压线后，家长都在聊冲刺班。",
            published_at=now,
        )
        session.add(content)
        session.flush()
        parent = Comment(
            platform="xhs",
            platform_comment_id="comment-parent",
            content_id=content.id,
            author_profile_id=parent_user.id,
            body_text="福州哪家 PET 冲刺班靠谱？",
            published_at=now,
        )
        session.add(parent)
        session.flush()
        reply = Comment(
            platform="xhs",
            platform_comment_id="comment-reply",
            content_id=content.id,
            parent_comment_id=parent.id,
            author_profile_id=reply_user.id,
            body_text="价格多少，可以先试听吗？",
            published_at=now,
        )
        session.add(reply)
        session.commit()
        return reply.id


def _seed_single_comment(factory: sessionmaker[Session], *, body_text: str) -> None:
    with factory() as session:
        profile = _profile("user-1", "家长")
        session.add(profile)
        session.flush()
        content = Content(platform="xhs", platform_content_id="note-1", content_type="note", title="PET 讨论", body_text="家长交流")
        session.add(content)
        session.flush()
        session.add(
            Comment(
                platform="xhs",
                platform_comment_id="comment-1",
                content_id=content.id,
                author_profile_id=profile.id,
                body_text=body_text,
            )
        )
        session.commit()


def _seed_duplicate_and_garbage_comments(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        profile = _profile("user-dup", "家长")
        session.add(profile)
        session.flush()
        content = Content(platform="xhs", platform_content_id="note-dup", content_type="note", title="PET 讨论", body_text="家长交流")
        session.add(content)
        session.flush()
        for index, body_text in enumerate(("PET 哪家机构比较靠谱？", "PET 哪家机构比较靠谱？", "哈哈哈"), start=1):
            session.add(
                Comment(
                    platform="xhs",
                    platform_comment_id=f"comment-{index}",
                    content_id=content.id,
                    author_profile_id=profile.id,
                    body_text=body_text,
                )
            )
        session.commit()


def _profile(platform_user_id: str, display_name: str) -> PublicProfile:
    return PublicProfile(platform="xhs", platform_user_id=platform_user_id, display_name=display_name)
