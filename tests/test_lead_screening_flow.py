from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.cli import main as cli_main
from integrations.feishu.llm_review import LLM_REVIEW_EVENT_TYPE, apply_llm_review_callback, send_pending_llm_review_cards
from services.lead_screening_flow import (
    advance_llm_done_to_pending_feishu,
    diagnose_lead_screening_workflow,
    recover_stale_lead_screening,
)
from services.llm_lead_screening import LeadScreeningContext, LLMLeadScreeningDecision, run_llm_lead_screening
from storage.database import Base
from storage.models import CollectionEvent, Comment, Content, LeadScreeningResult, PublicProfile


def test_one_real_source_moves_through_llm_feishu_and_review_once(factory: sessionmaker[Session]) -> None:
    comment_id = _seed_real_comment(factory)
    llm_client = FakeLeadScreeningClient()

    with factory() as session:
        llm_result = run_llm_lead_screening(
            session,
            client=llm_client,
            source_entity_types={"comment"},
            source_entity_ids={comment_id},
        )
        session.commit()

    assert llm_result.screened == 1
    assert len(llm_client.contexts) == 1
    with factory() as session:
        screening = session.scalar(select(LeadScreeningResult).where(LeadScreeningResult.comment_id == comment_id))
        assert screening is not None
        screening_id = screening.id
        assert screening.workflow_status == "llm_done"
        assert screening.attempt_count == 0
        assert screening.last_error is None
        assert screening.feishu_message_id is None

        advanced = advance_llm_done_to_pending_feishu(session, screening_ids={screening_id})
        session.commit()
        assert advanced == {"advanced": 1, "skipped": 0}
        assert screening.workflow_status == "pending_feishu"

    feishu_client = FakeReviewCardClient()
    with factory() as session:
        send_result = send_pending_llm_review_cards(
            session,
            client=feishu_client,
            chat_id="oc_review",
            limit=10,
            screening_ids={screening_id},
        )
        session.commit()

    assert send_result == {"sent": 1, "skipped": 0, "failed": 0}
    assert len(feishu_client.sent_cards) == 1
    with factory() as session:
        screening = session.scalar(select(LeadScreeningResult).where(LeadScreeningResult.comment_id == comment_id))
        assert screening is not None
        assert screening.workflow_status == "sent"
        assert screening.feishu_message_id == "om_review_1"

        callback_result = apply_llm_review_callback(
            session,
            _review_payload("evt-1", screening.id, "valid"),
            client=feishu_client,
            verification_token="token",
            now=datetime(2026, 7, 7, tzinfo=UTC),
        )
        duplicate = apply_llm_review_callback(
            session,
            _review_payload("evt-2", screening.id, "valid"),
            client=feishu_client,
            verification_token="token",
            now=datetime(2026, 7, 7, tzinfo=UTC),
        )
        session.commit()

    assert callback_result.applied is True
    assert duplicate.applied is False
    assert duplicate.duplicate is True
    assert len(feishu_client.updated_cards) == 1

    with factory() as session:
        screening = session.scalar(select(LeadScreeningResult).where(LeadScreeningResult.comment_id == comment_id))
        assert screening.workflow_status == "reviewed"
        assert screening.human_review_status == "valid"
        events = session.scalars(select(CollectionEvent).where(CollectionEvent.event_type == LLM_REVIEW_EVENT_TYPE)).all()
        assert len(events) == 1

    second_llm_client = FakeLeadScreeningClient()
    with factory() as session:
        rerun_llm = run_llm_lead_screening(session, client=second_llm_client, source_entity_types={"comment"})
        rerun_send = send_pending_llm_review_cards(session, client=FakeReviewCardClient(), chat_id="oc_review", limit=10)
        session.commit()

    assert rerun_llm.skipped_existing == 1
    assert len(second_llm_client.contexts) == 0
    assert rerun_send == {"sent": 0, "skipped": 0, "failed": 0}


def test_failures_record_last_error_and_attempt_count(factory: sessionmaker[Session]) -> None:
    comment_id = _seed_real_comment(factory)

    with factory() as session:
        result = run_llm_lead_screening(
            session,
            client=FailingLeadScreeningClient("LLM temporarily unavailable"),
            source_entity_types={"comment"},
            source_entity_ids={comment_id},
        )
        session.commit()

    assert result.failed == 1
    with factory() as session:
        screening = session.scalar(select(LeadScreeningResult).where(LeadScreeningResult.comment_id == comment_id))
        assert screening is not None
        assert screening.workflow_status == "pending_llm"
        assert screening.attempt_count == 0
        assert screening.last_error == "LLM temporarily unavailable"
        screening.workflow_status = "pending_feishu"
        session.commit()

    with factory() as session:
        result = send_pending_llm_review_cards(
            session,
            client=FailingReviewCardClient("Feishu timeout"),
            chat_id="oc_review",
            limit=10,
        )
        session.commit()

    assert result == {"sent": 0, "skipped": 0, "failed": 1}
    with factory() as session:
        screening = session.scalar(select(LeadScreeningResult).where(LeadScreeningResult.comment_id == comment_id))
        assert screening.workflow_status == "pending_feishu"
        assert screening.attempt_count == 1
        assert screening.last_error == "Feishu timeout"


def test_llm_limit_counts_actual_work_not_existing_rows(factory: sessionmaker[Session]) -> None:
    first_comment_id, second_comment_id = _seed_two_comments_with_first_reviewed(factory)
    llm_client = FakeLeadScreeningClient()

    with factory() as session:
        result = run_llm_lead_screening(
            session,
            client=llm_client,
            source_entity_types={"comment"},
            limit=1,
        )
        session.commit()

    assert result.screened == 1
    assert result.skipped_existing == 1
    assert [context.source_entity_id for context in llm_client.contexts] == [second_comment_id]
    with factory() as session:
        first = session.scalar(select(LeadScreeningResult).where(LeadScreeningResult.comment_id == first_comment_id))
        second = session.scalar(select(LeadScreeningResult).where(LeadScreeningResult.comment_id == second_comment_id))
        assert first is not None
        assert first.workflow_status == "reviewed"
        assert second is not None
        assert second.workflow_status == "llm_done"


def test_stale_sending_is_diagnosed_and_manual_recovery_is_traceable(factory: sessionmaker[Session]) -> None:
    comment_id = _seed_real_comment(factory)
    now = datetime(2026, 7, 7, tzinfo=UTC)
    with factory() as session:
        screening = LeadScreeningResult(
            platform="xhs",
            source_entity_type="comment",
            source_entity_id=comment_id,
            comment_id=comment_id,
            review_status="needs_review",
            workflow_status="sending",
            attempt_count=3,
            last_error=None,
            updated_at=now - timedelta(hours=2),
        )
        session.add(screening)
        session.commit()
        screening_id = screening.id

    with factory() as session:
        diagnostics = diagnose_lead_screening_workflow(session, now=now, sending_timeout=timedelta(minutes=30))

    assert diagnostics["counts_by_status"]["sending"] == 1
    assert diagnostics["issue_counts"]["stale_sending"] == 1
    assert diagnostics["issue_counts"]["empty_error_abnormal_state"] == 1
    assert diagnostics["issues"][0]["recommended_action"] == "manual_check"

    with factory() as session:
        recovered = recover_stale_lead_screening(
            session,
            screening_id=screening_id,
            from_status="sending",
            to_status="send_uncertain",
            reason="HTTP result unknown after worker restart",
            operator="ops",
            now=now,
        )
        session.commit()

    assert recovered is True
    with factory() as session:
        screening = session.get(LeadScreeningResult, screening_id)
        assert screening.workflow_status == "send_uncertain"
        assert screening.last_error == "HTTP result unknown after worker restart"
        event = session.scalar(select(CollectionEvent).where(CollectionEvent.event_type == "lead_screening_manual_recovery"))
        assert event is not None
        assert event.event_data["from_status"] == "sending"
        assert event.event_data["to_status"] == "send_uncertain"
        assert event.event_data["operator"] == "ops"


def test_manual_recovery_does_not_overwrite_newer_state(factory: sessionmaker[Session]) -> None:
    comment_id = _seed_real_comment(factory)
    now = datetime(2026, 7, 7, tzinfo=UTC)
    with factory() as session:
        screening = LeadScreeningResult(
            platform="xhs",
            source_entity_type="comment",
            source_entity_id=comment_id,
            comment_id=comment_id,
            review_status="needs_review",
            workflow_status="sent",
            feishu_message_id="om_already_sent",
            updated_at=now,
        )
        session.add(screening)
        session.commit()
        screening_id = screening.id

    with factory() as session:
        recovered = recover_stale_lead_screening(
            session,
            screening_id=screening_id,
            from_status="sending",
            to_status="pending_feishu",
            reason="manual stale retry",
            operator="ops",
            now=now,
        )
        session.commit()

    assert recovered is False
    with factory() as session:
        screening = session.get(LeadScreeningResult, screening_id)
        assert screening.workflow_status == "sent"
        assert screening.feishu_message_id == "om_already_sent"
        assert session.scalar(select(CollectionEvent).where(CollectionEvent.event_type == "lead_screening_manual_recovery")) is None


def test_lead_flow_once_cli_runs_the_next_state_only(
    factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_real_comment(factory)

    class FakeDefaultClient(FakeLeadScreeningClient):
        pass

    fake_feishu = FakeReviewCardClient()
    monkeypatch.setattr("apps.cli.SessionLocal", factory)
    monkeypatch.setattr("services.llm_lead_screening.OpenAICompatibleLeadScreeningClient", FakeDefaultClient)
    monkeypatch.setattr("apps.cli.FeishuIMClient", lambda: fake_feishu)

    assert cli_main(["--json", "lead-flow-once", "--source", "comment", "--limit", "1"]) == 0
    first_output = json.loads(capsys.readouterr().out)
    assert first_output["lead_flow"]["step"] == "llm"
    assert "workflow_counts" in first_output["lead_flow"]
    assert set(first_output["lead_flow"]["workflow_counts"]) >= {
        "pending_llm",
        "llm_done",
        "pending_feishu",
        "sending",
        "sent",
        "reviewed",
        "failed",
    }
    with factory() as session:
        assert session.scalar(select(LeadScreeningResult)).workflow_status == "llm_done"

    assert cli_main(["--json", "lead-flow-once", "--source", "comment", "--limit", "1"]) == 0
    assert '"step": "advance_to_pending_feishu"' in capsys.readouterr().out
    with factory() as session:
        assert session.scalar(select(LeadScreeningResult)).workflow_status == "pending_feishu"

    assert cli_main(["--json", "lead-flow-once", "--source", "comment", "--limit", "1", "--chat-id", "oc_review"]) == 0
    assert '"step": "feishu_send"' in capsys.readouterr().out
    with factory() as session:
        assert session.scalar(select(LeadScreeningResult)).workflow_status == "sent"
    assert len(fake_feishu.sent_cards) == 1


class FakeLeadScreeningClient:
    def __init__(self) -> None:
        self.contexts: list[LeadScreeningContext] = []

    def screen(self, context: LeadScreeningContext) -> LLMLeadScreeningDecision:
        self.contexts.append(context)
        return LLMLeadScreeningDecision(
            valuable=True,
            demand_type="course",
            intent_strength="high",
            judgment_evidence=("真实评论询问试听和价格",),
            confidence=0.88,
            reason="有明确咨询意向。",
            review_required=True,
            raw_json={"reason": "有明确咨询意向。"},
            model_name="fake-llm",
        )


class FailingLeadScreeningClient:
    def __init__(self, message: str) -> None:
        self.message = message

    def screen(self, context: LeadScreeningContext) -> LLMLeadScreeningDecision:
        raise RuntimeError(self.message)


class FakeReviewCardClient:
    def __init__(self) -> None:
        self.sent_cards: list[dict[str, Any]] = []
        self.updated_cards: list[dict[str, Any]] = []

    def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]:
        self.sent_cards.append(card)
        return {"message_id": "om_review_1", "chat_id": chat_id}

    def update_interactive_card(self, *, token: str, card: dict[str, Any]) -> dict[str, Any]:
        self.updated_cards.append({"token": token, "card": card})
        return {"ok": True}


class FailingReviewCardClient(FakeReviewCardClient):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]:
        raise RuntimeError(self.message)


def _seed_real_comment(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="real-user-1", display_name="真实家长")
        session.add(profile)
        session.flush()
        content = Content(
            platform="xhs",
            platform_content_id="real-note-1",
            content_type="note",
            author_profile_id=profile.id,
            title="PET 冲刺班怎么选",
            body_text="孩子准备二刷 PET，很多家长在比较课程。",
        )
        session.add(content)
        session.flush()
        comment = Comment(
            platform="xhs",
            platform_comment_id="real-comment-1",
            content_id=content.id,
            author_profile_id=profile.id,
            body_text="老师，PET 冲刺班多少钱，可以先试听吗？",
        )
        session.add(comment)
        session.commit()
        return comment.id


def _seed_two_comments_with_first_reviewed(factory: sessionmaker[Session]) -> tuple[int, int]:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="real-user-1", display_name="真实家长")
        session.add(profile)
        session.flush()
        content = Content(
            platform="xhs",
            platform_content_id="real-note-1",
            content_type="note",
            author_profile_id=profile.id,
            title="PET 冲刺班怎么选",
            body_text="孩子准备二刷 PET，很多家长在比较课程。",
        )
        session.add(content)
        session.flush()
        first = Comment(
            platform="xhs",
            platform_comment_id="real-comment-1",
            content_id=content.id,
            author_profile_id=profile.id,
            body_text="老师，PET 冲刺班多少钱，可以先试听吗？",
        )
        second = Comment(
            platform="xhs",
            platform_comment_id="real-comment-2",
            content_id=content.id,
            author_profile_id=profile.id,
            body_text="老师，二刷 PET 可以报冲刺班吗？",
        )
        session.add_all([first, second])
        session.flush()
        session.add(
            LeadScreeningResult(
                platform="xhs",
                source_entity_type="comment",
                source_entity_id=first.id,
                comment_id=first.id,
                public_profile_id=profile.id,
                review_status="needs_review",
                workflow_status="reviewed",
                human_review_status="valid",
            )
        )
        session.commit()
        return first.id, second.id


def _review_payload(event_id: str, screening_id: int, action: str) -> dict[str, Any]:
    return {
        "token": "token",
        "header": {"event_id": event_id},
        "event": {
            "operator": {"open_id": "ou_reviewer"},
            "token": "card-update-token",
            "context": {"open_message_id": "om_review_1", "open_chat_id": "oc_review"},
            "action": {
                "value": {
                    "screening_result_id": screening_id,
                    "action": action,
                }
            },
        },
    }


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
