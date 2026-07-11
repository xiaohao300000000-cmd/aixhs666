from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from integrations.feishu.comment_replies import (
    CommentReplySendResult,
    apply_comment_reply_callback,
    build_comment_reply_approval_card,
    create_comment_reply_for_valid_screening,
    is_comment_reply_callback,
)
from services.comment_reply_generation import CommentReplyDraft
from storage.database import Base
from storage.models import Comment, Content, LeadCommentReply, LeadScreeningResult, PublicProfile


class FakeCommentReplyGenerator:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, screening: LeadScreeningResult) -> CommentReplyDraft:
        self.calls += 1
        return CommentReplyDraft(text="可以先从词汇和真题入手，有具体情况也可以私信聊聊。", model_name="fake")


class FakeCardClient:
    def __init__(self, *, fail_update: bool = False) -> None:
        self.sent_cards: list[dict[str, Any]] = []
        self.updated_cards: list[dict[str, Any]] = []
        self.fail_update = fail_update

    def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]:
        self.sent_cards.append({"chat_id": chat_id, "card": card})
        return {"message_id": "om_reply_1", "chat_id": chat_id}

    def update_interactive_card(self, *, token: str, card: dict[str, Any]) -> dict[str, Any]:
        self.updated_cards.append({"token": token, "card": card})
        if self.fail_update:
            raise RuntimeError("card update failed")
        return {"ok": True}


class FakeCommentReplySender:
    def __init__(self, outcomes: list[CommentReplySendResult]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, str]] = []

    @classmethod
    def success(cls, reply_id: str = "platform-reply-1") -> FakeCommentReplySender:
        return cls([CommentReplySendResult(outcome="sent", platform_reply_id=reply_id, response_json={"id": reply_id})])

    def reply_to_comment(self, *, platform_comment_id: str, platform_content_id: str, text: str) -> CommentReplySendResult:
        self.calls.append({"comment_id": platform_comment_id, "content_id": platform_content_id, "text": text})
        return self.outcomes.pop(0)


@pytest.fixture
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    engine.dispose()


def test_valid_comment_screening_creates_one_card(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_comment_screening(factory)
    generator = FakeCommentReplyGenerator()
    card_client = FakeCardClient()
    with factory() as session:
        first = create_comment_reply_for_valid_screening(session, screening_id=screening_id, generator=generator, card_client=card_client, chat_id="oc_review")
        second = create_comment_reply_for_valid_screening(session, screening_id=screening_id, generator=generator, card_client=card_client, chat_id="oc_review")
        session.commit()
    assert first is not None and second is not None
    assert first.id == second.id
    assert first.status == "pending_review"
    assert generator.calls == 1
    assert len(card_client.sent_cards) == 1
    assert "确认回复" in str(card_client.sent_cards[0]["card"])


def test_creation_requires_accepted_valid_comment_with_actual_rows(factory: sessionmaker[Session]) -> None:
    valid_id = _seed_comment_screening(factory)
    with factory() as session:
        valid = session.get(LeadScreeningResult, valid_id)
        assert valid is not None
        valid.review_status = "rejected"
        session.commit()
    with factory() as session:
        assert create_comment_reply_for_valid_screening(session, screening_id=valid_id, generator=FakeCommentReplyGenerator(), card_client=FakeCardClient(), chat_id="oc") is None
    wrong_type = _seed_comment_screening(factory, suffix="2", source_type="content")
    with factory() as session:
        assert create_comment_reply_for_valid_screening(session, screening_id=wrong_type, generator=FakeCommentReplyGenerator(), card_client=FakeCardClient(), chat_id="oc") is None
    missing_rows = _seed_comment_screening(factory, suffix="3")
    with factory() as session:
        screening = session.get(LeadScreeningResult, missing_rows)
        assert screening is not None
        screening.comment_id = None
        session.commit()
    with factory() as session:
        assert create_comment_reply_for_valid_screening(session, screening_id=missing_rows, generator=FakeCommentReplyGenerator(), card_client=FakeCardClient(), chat_id="oc") is None


def test_callback_sends_once_and_marks_sent(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    sender = FakeCommentReplySender.success("reply-1")
    result = apply_comment_reply_callback(factory, _payload(reply_id, "最终回复"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    duplicate = apply_comment_reply_callback(factory, _payload(reply_id, "最终回复"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    assert result.status == "sent"
    assert result.applied is True
    assert duplicate.duplicate is True
    assert len(sender.calls) == 1
    with factory() as session:
        saved = session.get(LeadCommentReply, reply_id)
        assert saved is not None
        assert saved.status == "sent"
        assert saved.approved_text == "最终回复"
        assert saved.platform_reply_id == "reply-1"
        assert saved.attempt_count == 1


def test_failed_send_can_retry_but_normal_confirm_cannot(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    sender = FakeCommentReplySender([
        CommentReplySendResult(outcome="failed", error="temporary"),
        CommentReplySendResult(outcome="sent", platform_reply_id="reply-2"),
    ])
    failed = apply_comment_reply_callback(factory, _payload(reply_id, "第一次"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    duplicate_confirm = apply_comment_reply_callback(factory, _payload(reply_id, "第二次"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    retried = apply_comment_reply_callback(factory, _payload(reply_id, "第二次", action="retry"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    assert failed.status == "failed"
    assert duplicate_confirm.duplicate is True
    assert retried.status == "sent"
    assert len(sender.calls) == 2


def test_result_unknown_is_duplicate_protected(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    sender = FakeCommentReplySender([CommentReplySendResult(outcome="result_unknown", error="timeout")])
    first = apply_comment_reply_callback(factory, _payload(reply_id, "最终回复"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    duplicate = apply_comment_reply_callback(factory, _payload(reply_id, "最终回复", action="retry"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    assert first.status == "result_unknown"
    assert duplicate.duplicate is True
    assert len(sender.calls) == 1


@pytest.mark.parametrize("text", ["", "加微信详聊", "保证提分"])
def test_invalid_final_text_is_rejected_without_claim(factory: sessionmaker[Session], text: str) -> None:
    reply_id = _seed_pending_reply(factory)
    sender = FakeCommentReplySender.success()
    with pytest.raises(ValueError):
        apply_comment_reply_callback(factory, _payload(reply_id, text), card_client=FakeCardClient(), sender=sender, verification_token="token")
    assert sender.calls == []
    with factory() as session:
        assert session.get(LeadCommentReply, reply_id).status == "pending_review"


def test_send_result_is_persisted_before_card_update(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    result = apply_comment_reply_callback(factory, _payload(reply_id, "最终回复"), card_client=FakeCardClient(fail_update=True), sender=FakeCommentReplySender.success(), verification_token="token")
    assert result.status == "sent"
    with factory() as session:
        saved = session.get(LeadCommentReply, reply_id)
        assert saved.status == "sent"
        assert "card update failed" in saved.feishu_sync_error


def test_conditional_claim_loss_does_not_send(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    with factory() as session:
        session.execute(update(LeadCommentReply).where(LeadCommentReply.id == reply_id).values(status="sending"))
        session.commit()
    sender = FakeCommentReplySender.success()
    result = apply_comment_reply_callback(factory, _payload(reply_id, "最终回复"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    assert result.duplicate is True
    assert result.status == "sending"
    assert sender.calls == []


def test_callback_identification_and_card_rendering(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    payload = _payload(reply_id, "最终回复")
    assert is_comment_reply_callback(payload) is True
    assert is_comment_reply_callback({"event": {"action": {"name": "send_outreach_1"}}}) is False
    with factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        screening = session.get(LeadScreeningResult, reply.screening_result_id)
        card = build_comment_reply_approval_card(reply, screening)
    assert "comment_reply_text" in str(card)


def _seed_comment_screening(factory: sessionmaker[Session], *, suffix: str = "1", source_type: str = "comment") -> int:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id=f"u{suffix}", display_name="家长")
        session.add(profile)
        session.flush()
        content = Content(platform="xhs", platform_content_id=f"note-{suffix}", content_type="note", author_profile_id=profile.id, title="KET备考", url=f"https://www.xiaohongshu.com/explore/note-{suffix}")
        session.add(content)
        session.flush()
        comment = Comment(platform="xhs", platform_comment_id=f"comment-{suffix}", content_id=content.id, author_profile_id=profile.id, body_text="怎么入门")
        session.add(comment)
        session.flush()
        screening = LeadScreeningResult(platform="xhs", source_entity_type=source_type, source_entity_id=comment.id, content_id=content.id, comment_id=comment.id, public_profile_id=profile.id, review_status="accepted", workflow_status="reviewed", human_review_status="valid", context_json={"current_comment": comment.body_text, "post_title": content.title, "source_url": content.url})
        session.add(screening)
        session.commit()
        return int(screening.id)


def _seed_pending_reply(factory: sessionmaker[Session]) -> int:
    screening_id = _seed_comment_screening(factory)
    with factory() as session:
        reply = create_comment_reply_for_valid_screening(session, screening_id=screening_id, generator=FakeCommentReplyGenerator(), card_client=FakeCardClient(), chat_id="oc_review")
        session.commit()
        return int(reply.id)


def _payload(reply_id: int, text: str, *, action: str = "confirm") -> dict[str, Any]:
    return {"token": "token", "event": {"token": "update-token", "operator": {"open_id": "ou_reviewer"}, "context": {"open_message_id": "om_reply_1", "open_chat_id": "oc_review"}, "action": {"name": f"{action}_comment_reply_{reply_id}", "form_value": {"comment_reply_text": text}}}}
