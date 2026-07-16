from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from threading import Barrier, Lock
import time
from typing import Any

import pytest
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from integrations.feishu.comment_replies import (
    CommentReplyPreSubmitError,
    CommentReplySendResult,
    CommentReplyWorkflowError,
    apply_comment_reply_callback,
    build_comment_reply_approval_card,
    adopt_reconciled_comment_reply_card,
    create_comment_reply_for_valid_screening,
    enqueue_comment_reply_callback,
    execute_approved_comment_reply,
    confirm_comment_reply_not_sent,
    is_comment_reply_callback,
    reconcile_stale_comment_reply,
)
from services.comment_reply_generation import CommentReplyDraft
from storage.database import Base
from storage.models import CollectionTask, Comment, ContactCommandOperation, Content, CustomerFollowupRecord, CustomerTimelineEvent, Lead, LeadCommentReply, LeadScreeningResult, PublicProfile


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


class ConcurrentCardClient(FakeCardClient):
    def __init__(self) -> None:
        super().__init__()
        self.lock = Lock()

    def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]:
        with self.lock:
            return super().send_interactive_card(chat_id=chat_id, card=card)


class FakeCommentReplySender:
    def __init__(self, outcomes: list[CommentReplySendResult]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, str]] = []

    @classmethod
    def success(cls, reply_id: str = "platform-reply-1") -> FakeCommentReplySender:
        return cls([CommentReplySendResult(outcome="sent", platform_reply_id=reply_id, response_json={"id": reply_id})])

    def reply_to_comment(
        self,
        *,
        platform_comment_id: str,
        platform_content_id: str,
        target_url: str | None,
        text: str,
    ) -> CommentReplySendResult:
        self.calls.append(
            {
                "comment_id": platform_comment_id,
                "content_id": platform_content_id,
                "target_url": target_url,
                "text": text,
            }
        )
        return self.outcomes.pop(0)


class RaisingSender:
    def __init__(self, exception: Exception) -> None:
        self.exception = exception

    def reply_to_comment(self, **_: str) -> CommentReplySendResult:
        raise self.exception


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


@pytest.fixture
def file_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'workflow.db'}", connect_args={"check_same_thread": False})
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
    assert "确认话术（不会发送）" in str(card_client.sent_cards[0]["card"])


def test_comment_reply_callback_approves_then_enqueues_one_persistent_send_task(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)

    first = enqueue_comment_reply_callback(factory, _payload(reply_id, "最终回复"), verification_token="token")
    duplicate = enqueue_comment_reply_callback(factory, _payload(reply_id, "最终回复"), verification_token="token")

    assert first.status == "approved"
    assert "发送公开回复" in str(first.card)
    assert "最终回复" in str(first.card)
    assert first.applied is True
    assert duplicate.duplicate is True
    with factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        tasks = list(session.scalars(select(CollectionTask).where(CollectionTask.task_type == "comment_reply_send")))
    assert reply is not None
    assert reply.status == "approved"
    assert reply.attempt_count == 0
    assert len(tasks) == 0

    queued = enqueue_comment_reply_callback(
        factory,
        _payload(reply_id, "最终回复", action="send"),
        verification_token="token",
    )
    duplicate_send = enqueue_comment_reply_callback(
        factory,
        _payload(reply_id, "最终回复", action="send"),
        verification_token="token",
    )
    assert queued.status == "queued"
    assert duplicate_send.duplicate is True
    with factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        tasks = list(session.scalars(select(CollectionTask).where(CollectionTask.task_type == "comment_reply_send")))
    assert reply.status == "queued"
    assert len(tasks) == 1
    assert tasks[0].target_id == str(reply_id)


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
    assert sender.calls[0]["target_url"] == "https://www.xiaohongshu.com/explore/note-1"
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


def test_result_unknown_requires_explicit_not_sent_confirmation_before_one_retry(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    sender = FakeCommentReplySender([
        CommentReplySendResult(outcome="result_unknown", error="timeout"),
        CommentReplySendResult(outcome="sent", platform_reply_id="reply-2"),
    ])
    apply_comment_reply_callback(factory, _payload(reply_id, "最终回复"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    blocked = apply_comment_reply_callback(factory, _payload(reply_id, "最终回复", action="retry"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    card_client = FakeCardClient()
    confirmed = confirm_comment_reply_not_sent(factory, reply_id=reply_id, operator="ops@example.com", reason="checked XHS comment thread", card_client=card_client)
    retried = apply_comment_reply_callback(factory, _payload(reply_id, "最终回复", action="retry"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    duplicate = apply_comment_reply_callback(factory, _payload(reply_id, "最终回复", action="retry"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    assert blocked.duplicate is True
    assert confirmed.status == "failed"
    assert confirmed.card_status == "replaced"
    assert card_client.sent_cards[0]["card"]["body"]["elements"][-1]["elements"][-1]["name"] == f"retry_comment_reply_{reply_id}"
    assert retried.status == "sent"
    assert duplicate.duplicate is True
    assert len(sender.calls) == 2
    with factory() as session:
        saved = session.get(LeadCommentReply, reply_id)
        assert saved.attempt_count == 2


def test_synchronous_sender_delay_still_duplicate_protects_followup_request(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    started = Barrier(2)

    class DelayedSender(FakeCommentReplySender):
        def reply_to_comment(self, **kwargs: Any) -> CommentReplySendResult:
            started.wait()
            time.sleep(0.02)
            return super().reply_to_comment(**kwargs)

    sender = DelayedSender([CommentReplySendResult(outcome="sent", platform_reply_id="reply-delayed")])
    with ThreadPoolExecutor(max_workers=1) as executor:
        first_future = executor.submit(apply_comment_reply_callback, factory, _payload(reply_id, "最终回复"), card_client=FakeCardClient(), sender=sender, verification_token="token")
        started.wait()
        duplicate = apply_comment_reply_callback(factory, _payload(reply_id, "最终回复"), card_client=FakeCardClient(), sender=sender, verification_token="token")
        first = first_future.result()
    assert first.status == "sent"
    assert duplicate.duplicate is True
    assert len(sender.calls) == 1


def test_late_unknown_completion_cannot_overwrite_confirmed_retry(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    with factory() as session:
        session.execute(update(LeadCommentReply).where(LeadCommentReply.id == reply_id).values(status="result_unknown", attempt_count=1))
        session.commit()
    confirm_comment_reply_not_sent(factory, reply_id=reply_id, operator="ops", reason="not present on platform", card_client=FakeCardClient())
    sender = FakeCommentReplySender([CommentReplySendResult(outcome="sent", platform_reply_id="reply-new")])
    apply_comment_reply_callback(factory, _payload(reply_id, "最终回复", action="retry"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    with factory() as session:
        stale = session.execute(
            update(LeadCommentReply)
            .where(LeadCommentReply.id == reply_id, LeadCommentReply.status == "sending", LeadCommentReply.attempt_count == 1)
            .values(status="result_unknown", last_error="late timeout")
        ).rowcount
        session.commit()
        saved = session.get(LeadCommentReply, reply_id)
        assert stale == 0
        assert saved.status == "sent"
        assert saved.platform_reply_id == "reply-new"


def test_confirm_not_sent_card_failure_is_partial_and_never_creates_duplicate(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    with factory() as session:
        session.execute(update(LeadCommentReply).where(LeadCommentReply.id == reply_id).values(status="result_unknown"))
        session.commit()
    failing = FakeCardClient()
    failing.send_interactive_card = lambda **_: (_ for _ in ()).throw(RuntimeError("ambiguous card send failure"))
    first = confirm_comment_reply_not_sent(factory, reply_id=reply_id, operator="ops", reason="verified absent", card_client=failing)
    second_client = FakeCardClient()
    second = confirm_comment_reply_not_sent(factory, reply_id=reply_id, operator="ops", reason="verified absent", card_client=second_client)
    assert first.status == "failed"
    assert first.card_status == "replacement_unknown"
    assert first.reconciliation_required is True
    assert second.card_status == "replacement_unknown"
    assert second_client.sent_cards == []
    with factory() as session:
        saved = session.get(LeadCommentReply, reply_id)
        assert saved.status == "failed"
        assert saved.feishu_card_status == "retry_card_creating"
        assert "ambiguous card send failure" in saved.feishu_sync_error


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
    class ObservingFailingCardClient(FakeCardClient):
        def update_interactive_card(self, *, token: str, card: dict[str, Any]) -> dict[str, Any]:
            with factory() as session:
                saved = session.get(LeadCommentReply, reply_id)
                assert saved.status == "sent"
                assert saved.platform_reply_id == "platform-reply-1"
            raise RuntimeError("card update failed")

    result = apply_comment_reply_callback(factory, _payload(reply_id, "最终回复"), card_client=ObservingFailingCardClient(), sender=FakeCommentReplySender.success(), verification_token="token")
    assert result.status == "sent"
    with factory() as session:
        saved = session.get(LeadCommentReply, reply_id)
        lead = session.get(Lead, saved.lead_id)
        assert saved.status == "sent"
        assert "card update failed" in saved.feishu_sync_error
        assert lead.crm_stage == "contact_sent_waiting_reply"
        assert lead.last_contact_result == "public_reply_sent"
        assert session.query(CustomerFollowupRecord).filter_by(lead_id=lead.id, result="sent").count() == 1


@pytest.mark.parametrize("outcome", ["sent", "failed", "result_unknown"])
def test_worker_result_uses_contact_command_and_persists_customer_facts(factory: sessionmaker[Session], outcome: str) -> None:
    reply_id = _seed_pending_reply(factory, suffix=f"result-{outcome}")
    enqueue_comment_reply_callback(factory, _payload(reply_id, "最终回复"), verification_token="token")
    enqueue_comment_reply_callback(factory, _payload(reply_id, "最终回复", action="send"), verification_token="token")
    sender = FakeCommentReplySender([CommentReplySendResult(outcome=outcome, error="safe failure" if outcome != "sent" else None)])

    result = execute_approved_comment_reply(
        factory,
        reply_id=reply_id,
        draft_revision=1,
        update_token=None,
        card_client=FakeCardClient(),
        sender=sender,
    )

    assert result.status == outcome
    with factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        assert reply.status == outcome
        assert session.query(ContactCommandOperation).filter_by(operation_scope="record_contact_result", entity_id=reply_id).count() == 1
        assert session.query(CustomerFollowupRecord).filter_by(lead_id=reply.lead_id, result=outcome).count() == 1
        assert session.query(CustomerTimelineEvent).filter_by(lead_id=reply.lead_id, event_type=f"contact_result_{outcome}").count() == 1


def test_result_revision_fence_rejects_stale_worker_payload_without_sender_call(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory, suffix="stale-payload")
    enqueue_comment_reply_callback(factory, _payload(reply_id, "最终回复"), verification_token="token")
    enqueue_comment_reply_callback(factory, _payload(reply_id, "最终回复", action="send"), verification_token="token")
    sender = FakeCommentReplySender.success()

    result = execute_approved_comment_reply(factory, reply_id=reply_id, draft_revision=99, update_token=None, card_client=FakeCardClient(), sender=sender)

    assert result.duplicate is True
    assert sender.calls == []
    with factory() as session:
        assert session.get(LeadCommentReply, reply_id).status == "queued"


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


def test_callback_rejects_invalid_token_and_stored_context_mismatch(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    with pytest.raises(ValueError, match="token"):
        apply_comment_reply_callback(factory, _payload(reply_id, "最终回复", token="wrong"), card_client=FakeCardClient(), sender=FakeCommentReplySender.success(), verification_token="token")
    with pytest.raises(ValueError, match="message"):
        apply_comment_reply_callback(factory, _payload(reply_id, "最终回复", message_id="forged"), card_client=FakeCardClient(), sender=FakeCommentReplySender.success(), verification_token="token")
    with pytest.raises(ValueError, match="chat"):
        apply_comment_reply_callback(factory, _payload(reply_id, "最终回复", chat_id="forged"), card_client=FakeCardClient(), sender=FakeCommentReplySender.success(), verification_token="token")


@pytest.mark.parametrize("name", ["confirm_comment_reply_1_extra", "confirm_comment_reply_-1", "xconfirm_comment_reply_1", "retry_comment_reply_abc"])
def test_callback_rejects_malformed_or_forged_actions(factory: sessionmaker[Session], name: str) -> None:
    reply_id = _seed_pending_reply(factory)
    payload = _payload(reply_id, "最终回复")
    payload["event"]["action"]["name"] = name
    assert is_comment_reply_callback(payload) is False
    with pytest.raises(ValueError, match="callback"):
        apply_comment_reply_callback(factory, payload, card_client=FakeCardClient(), sender=FakeCommentReplySender.success(), verification_token="token")


def test_direct_event_shape_is_supported_and_operator_is_required(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    wrapped = _payload(reply_id, "最终回复")
    direct = {"token": wrapped["token"], **wrapped["event"]}
    assert is_comment_reply_callback(direct) is True
    result = apply_comment_reply_callback(factory, direct, card_client=FakeCardClient(), sender=FakeCommentReplySender.success(), verification_token="update-token")
    assert result.status == "sent"
    other_id = _seed_pending_reply(factory, suffix="2")
    missing_operator = _payload(other_id, "最终回复")
    missing_operator["event"].pop("operator")
    with pytest.raises(ValueError, match="operator"):
        apply_comment_reply_callback(factory, missing_operator, card_client=FakeCardClient(), sender=FakeCommentReplySender.success(), verification_token="token")


def test_stale_send_completion_does_not_overwrite_new_attempt(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)

    class StealingSender:
        def reply_to_comment(self, **_: str) -> CommentReplySendResult:
            with factory() as session:
                session.execute(update(LeadCommentReply).where(LeadCommentReply.id == reply_id).values(attempt_count=2, status="sending"))
                session.commit()
            return CommentReplySendResult(outcome="sent", platform_reply_id="stale")

    result = apply_comment_reply_callback(factory, _payload(reply_id, "最终回复"), card_client=FakeCardClient(), sender=StealingSender(), verification_token="token")
    assert result.status == "sending"
    assert result.reconciliation_required is True
    with factory() as session:
        saved = session.get(LeadCommentReply, reply_id)
        assert saved.status == "sending"
        assert saved.attempt_count == 2
        assert saved.platform_reply_id is None


def test_explicit_reconciliation_recovers_only_stale_claims(factory: sessionmaker[Session]) -> None:
    card_id = _seed_pending_reply(factory)
    send_id = _seed_pending_reply(factory, suffix="2")
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    with factory() as session:
        session.execute(
            update(LeadCommentReply)
            .where(LeadCommentReply.id == card_id)
            .values(
                feishu_message_id=None,
                feishu_card_status="card_creating",
                feishu_chat_id="card-claim:stale",
                updated_at=now - timedelta(minutes=20),
            )
        )
        session.execute(
            update(LeadCommentReply)
            .where(LeadCommentReply.id == send_id)
            .values(status="sending", last_attempt_at=now - timedelta(minutes=20))
        )
        session.commit()

    card = reconcile_stale_comment_reply(factory, reply_id=card_id, now=now, card_timeout=timedelta(minutes=10), send_timeout=timedelta(minutes=10))
    sending = reconcile_stale_comment_reply(factory, reply_id=send_id, now=now, card_timeout=timedelta(minutes=10), send_timeout=timedelta(minutes=10))
    assert card.applied is True and card.status == "pending_review"
    assert sending.applied is True and sending.status == "result_unknown"
    assert sending.reconciliation_required is True
    with factory() as session:
        card_reply = session.get(LeadCommentReply, card_id)
        send_reply = session.get(LeadCommentReply, send_id)
        assert card_reply.feishu_card_status == "card_result_unknown"
        assert "reconciliation required" in card_reply.feishu_sync_error
        assert send_reply.status == "result_unknown"
        assert "operator reconciliation" in send_reply.last_error


def test_card_result_unknown_never_resends_and_adoption_enables_callback(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    with factory() as session:
        session.execute(
            update(LeadCommentReply)
            .where(LeadCommentReply.id == reply_id)
            .values(feishu_message_id=None, feishu_card_status="card_creating", feishu_chat_id="card-claim:old", updated_at=now - timedelta(minutes=20))
        )
        session.commit()
    reconcile_stale_comment_reply(factory, reply_id=reply_id, now=now, card_timeout=timedelta(minutes=10), send_timeout=timedelta(minutes=10))
    blocked_client = FakeCardClient()
    with factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        create_comment_reply_for_valid_screening(session, screening_id=reply.screening_result_id, generator=FakeCommentReplyGenerator(), card_client=blocked_client, chat_id="oc_review")
    assert blocked_client.sent_cards == []

    second_blocked_client = FakeCardClient()
    with factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        create_comment_reply_for_valid_screening(session, screening_id=reply.screening_result_id, generator=FakeCommentReplyGenerator(), card_client=second_blocked_client, chat_id="oc_review")
    assert second_blocked_client.sent_cards == []

    adopted = adopt_reconciled_comment_reply_card(factory, reply_id=reply_id, message_id="om_located", chat_id="oc_located", operator="ou_admin", reason="located in Feishu message history")
    assert adopted.applied is True
    with factory() as session:
        saved = session.get(LeadCommentReply, reply_id)
        assert saved.feishu_card_status == "card_pending"
        assert saved.feishu_message_id == "om_located"
        assert saved.feishu_chat_id == "oc_located"
        assert saved.feishu_sync_error == "operator ou_admin adopted reconciled card: located in Feishu message history"
    sender = FakeCommentReplySender.success()
    result = apply_comment_reply_callback(factory, _payload(reply_id, "最终回复", message_id="om_located", chat_id="oc_located"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    assert result.status == "sent"
    assert len(sender.calls) == 1


def test_late_original_card_completion_cannot_overwrite_adopted_card(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    with factory() as session:
        session.execute(update(LeadCommentReply).where(LeadCommentReply.id == reply_id).values(feishu_message_id=None, feishu_card_status="card_creating", feishu_chat_id="card-claim:old", updated_at=now - timedelta(minutes=20)))
        session.commit()
    reconcile_stale_comment_reply(factory, reply_id=reply_id, now=now, card_timeout=timedelta(minutes=10), send_timeout=timedelta(minutes=10))
    adopt_reconciled_comment_reply_card(factory, reply_id=reply_id, message_id="om_adopted", chat_id="oc_adopted", operator="ou_admin", reason="located original card")
    with factory() as session:
        updated = session.execute(
            update(LeadCommentReply)
            .where(LeadCommentReply.id == reply_id, LeadCommentReply.feishu_card_status == "card_creating", LeadCommentReply.feishu_chat_id == "card-claim:old")
            .values(feishu_message_id="om_late_original", feishu_card_status="card_pending")
        ).rowcount
        session.commit()
    assert updated == 0
    with factory() as session:
        saved = session.get(LeadCommentReply, reply_id)
        assert saved.feishu_message_id == "om_adopted"
        assert saved.feishu_chat_id == "oc_adopted"


def test_card_result_unknown_stays_unknown_without_located_card(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    with factory() as session:
        session.execute(update(LeadCommentReply).where(LeadCommentReply.id == reply_id).values(feishu_message_id=None, feishu_card_status="card_result_unknown"))
        session.commit()
    with pytest.raises(ValueError, match="message_id"):
        adopt_reconciled_comment_reply_card(factory, reply_id=reply_id, message_id="", chat_id="oc_review", operator="ou_admin", reason="not located")
    with factory() as session:
        saved = session.get(LeadCommentReply, reply_id)
        assert saved.feishu_card_status == "card_result_unknown"
        assert saved.feishu_message_id is None


def test_reconciliation_does_not_change_fresh_or_completed_card_claim(factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(factory)
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    with factory() as session:
        session.execute(
            update(LeadCommentReply)
            .where(LeadCommentReply.id == reply_id)
            .values(feishu_card_status="card_creating", updated_at=now, feishu_message_id="om_existing")
        )
        session.commit()
    result = reconcile_stale_comment_reply(factory, reply_id=reply_id, now=now, card_timeout=timedelta(minutes=10), send_timeout=timedelta(minutes=10))
    assert result.applied is False
    with factory() as session:
        assert session.get(LeadCommentReply, reply_id).feishu_card_status == "card_creating"


def test_sender_exception_contract_and_unsupported_outcome_are_durable(factory: sessionmaker[Session]) -> None:
    failed_id = _seed_pending_reply(factory)
    failed = apply_comment_reply_callback(factory, _payload(failed_id, "最终回复"), card_client=FakeCardClient(), sender=RaisingSender(CommentReplyPreSubmitError("not submitted")), verification_token="token")
    assert failed.status == "failed"
    unknown_id = _seed_pending_reply(factory, suffix="2")
    unknown = apply_comment_reply_callback(factory, _payload(unknown_id, "最终回复"), card_client=FakeCardClient(), sender=RaisingSender(RuntimeError("after submit maybe")), verification_token="token")
    assert unknown.status == "result_unknown"
    unsupported_id = _seed_pending_reply(factory, suffix="3")
    unsupported = apply_comment_reply_callback(factory, _payload(unsupported_id, "最终回复"), card_client=FakeCardClient(), sender=FakeCommentReplySender([CommentReplySendResult(outcome="mystery")]), verification_token="token")
    assert unsupported.status == "result_unknown"
    with factory() as session:
        assert session.get(LeadCommentReply, unsupported_id).status == "result_unknown"
    malformed_id = _seed_pending_reply(factory, suffix="4")
    class MalformedSender:
        def reply_to_comment(self, **_: str) -> object:
            return object()
    malformed = apply_comment_reply_callback(factory, _payload(malformed_id, "最终回复"), card_client=FakeCardClient(), sender=MalformedSender(), verification_token="token")
    assert malformed.status == "result_unknown"
    with factory() as session:
        assert session.get(LeadCommentReply, malformed_id).status == "result_unknown"


def test_concurrent_callbacks_only_one_claims_send(file_factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(file_factory)
    sender = FakeCommentReplySender.success()
    def invoke() -> Any:
        return apply_comment_reply_callback(file_factory, _payload(reply_id, "最终回复"), card_client=FakeCardClient(), sender=sender, verification_token="token")
    with _claim_boundary_barrier(file_factory, "status="):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: invoke(), range(2)))
    assert len(sender.calls) == 1
    assert sorted(result.duplicate for result in results) == [False, True]


def test_concurrent_card_creation_has_one_external_send(file_factory: sessionmaker[Session]) -> None:
    reply_id = _seed_pending_reply(file_factory)
    with file_factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        screening_id = reply.screening_result_id
        reply.feishu_message_id = None
        reply.feishu_card_status = "card_failed"
        session.commit()
    card_client = ConcurrentCardClient()
    def create() -> Any:
        with file_factory() as session:
            return create_comment_reply_for_valid_screening(session, screening_id=screening_id, generator=FakeCommentReplyGenerator(), card_client=card_client, chat_id="oc_review")
    with _claim_boundary_barrier(file_factory, "feishu_card_status="):
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: create(), range(2)))
    assert replies[0].id == replies[1].id
    assert len(card_client.sent_cards) == 1


@pytest.mark.postgres
def test_postgres_conditional_send_claim_race() -> None:
    database_url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is not set")
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    postgres_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    suffix = f"pg-{datetime.now(UTC).timestamp()}"
    try:
        reply_id = _seed_pending_reply(postgres_factory, suffix=suffix)
        sender = FakeCommentReplySender.success()
        with _claim_boundary_barrier(postgres_factory, "status="):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: apply_comment_reply_callback(postgres_factory, _payload(reply_id, "最终回复"), card_client=FakeCardClient(), sender=sender, verification_token="token"), range(2)))
        assert len(sender.calls) == 1
        assert sorted(result.duplicate for result in results) == [False, True]
    finally:
        engine.dispose()


def test_card_creation_failure_is_retryable_but_card_creating_is_not_blindly_resent(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_comment_screening(factory)
    failing = FakeCardClient()
    failing.send_interactive_card = lambda **_: (_ for _ in ()).throw(RuntimeError("send card failed"))
    with factory() as session:
        with pytest.raises(RuntimeError, match="send card failed"):
            create_comment_reply_for_valid_screening(session, screening_id=screening_id, generator=FakeCommentReplyGenerator(), card_client=failing, chat_id="oc_review")
    with factory() as session:
        saved = session.scalar(select(LeadCommentReply))
        assert saved.feishu_card_status == "card_failed"
    retry_client = FakeCardClient()
    with factory() as session:
        create_comment_reply_for_valid_screening(session, screening_id=screening_id, generator=FakeCommentReplyGenerator(), card_client=retry_client, chat_id="oc_review")
    assert len(retry_client.sent_cards) == 1
    with factory() as session:
        saved = session.scalar(select(LeadCommentReply))
        saved.feishu_message_id = None
        saved.feishu_card_status = "card_creating"
        session.commit()
    no_resend = FakeCardClient()
    with factory() as session:
        create_comment_reply_for_valid_screening(session, screening_id=screening_id, generator=FakeCommentReplyGenerator(), card_client=no_resend, chat_id="oc_review")
    assert no_resend.sent_cards == []


def test_card_response_without_message_id_stays_reconciliation_only(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_comment_screening(factory)
    card_client = FakeCardClient()
    card_client.send_interactive_card = lambda **_: {"chat_id": "oc_review"}
    with factory() as session:
        create_comment_reply_for_valid_screening(session, screening_id=screening_id, generator=FakeCommentReplyGenerator(), card_client=card_client, chat_id="oc_review")
    with factory() as session:
        saved = session.scalar(select(LeadCommentReply))
        assert saved.feishu_card_status == "card_creating"
        assert "reconciliation" in saved.feishu_sync_error
    retry_client = FakeCardClient()
    with factory() as session:
        create_comment_reply_for_valid_screening(session, screening_id=screening_id, generator=FakeCommentReplyGenerator(), card_client=retry_client, chat_id="oc_review")
    assert retry_client.sent_cards == []


def test_missing_lead_is_actionable_and_sends_no_card(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_comment_screening(factory, suffix="missing-lead")
    with factory() as session:
        lead = session.scalar(select(Lead).join(PublicProfile).where(PublicProfile.platform_user_id == "umissing-lead"))
        session.delete(lead)
        session.commit()
    card_client = FakeCardClient()
    with factory() as session, pytest.raises(CommentReplyWorkflowError, match="create or backfill the lead"):
        create_comment_reply_for_valid_screening(session, screening_id=screening_id, generator=FakeCommentReplyGenerator(), card_client=card_client, chat_id="oc_review")
    assert card_client.sent_cards == []


def test_existing_reply_without_lead_is_backfilled_before_return(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_comment_screening(factory, suffix="legacy-link")
    with factory() as session:
        screening = session.get(LeadScreeningResult, screening_id)
        reply = LeadCommentReply(
            screening_result_id=screening.id,
            target_comment_id=screening.comment_id,
            target_platform_comment_id="comment-legacy-link",
            target_content_id=screening.content_id,
            target_platform_content_id="note-legacy-link",
            draft_text="已有草稿",
            status="pending_review",
        )
        session.add(reply)
        session.commit()
    with factory() as session:
        saved = create_comment_reply_for_valid_screening(session, screening_id=screening_id, generator=FakeCommentReplyGenerator(), card_client=FakeCardClient(), chat_id="oc_review")
        assert saved.lead_id is not None


def test_approval_card_contains_customer_post_and_demand_context(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_comment_screening(factory, suffix="card-context")
    card_client = FakeCardClient()
    with factory() as session:
        create_comment_reply_for_valid_screening(session, screening_id=screening_id, generator=FakeCommentReplyGenerator(), card_client=card_client, chat_id="oc_review")
    card_text = json.dumps(card_client.sent_cards[0]["card"], ensure_ascii=False)
    assert "家长" in card_text
    assert "家长询问备考入门" in card_text
    assert "https://www.xiaohongshu.com/explore/note-card-context" in card_text


def test_stale_card_completion_does_not_overwrite_new_creation_claim(factory: sessionmaker[Session]) -> None:
    screening_id = _seed_comment_screening(factory)

    class StealingCardClient(FakeCardClient):
        def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]:
            with factory() as session:
                reply = session.scalar(select(LeadCommentReply))
                session.execute(
                    update(LeadCommentReply)
                    .where(LeadCommentReply.id == reply.id)
                    .values(feishu_chat_id="card-claim:new-owner", feishu_sync_error="new owner")
                )
                session.commit()
            return {"message_id": "om_stale", "chat_id": chat_id}

    with factory() as session:
        create_comment_reply_for_valid_screening(
            session,
            screening_id=screening_id,
            generator=FakeCommentReplyGenerator(),
            card_client=StealingCardClient(),
            chat_id="oc_review",
        )
    with factory() as session:
        saved = session.scalar(select(LeadCommentReply))
        assert saved.feishu_card_status == "card_creating"
        assert saved.feishu_chat_id == "card-claim:new-owner"
        assert saved.feishu_message_id is None
        assert saved.feishu_sync_error == "new owner"


def _seed_comment_screening(factory: sessionmaker[Session], *, suffix: str = "1", source_type: str = "comment") -> int:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id=f"u{suffix}", display_name="家长")
        session.add(profile)
        session.flush()
        session.add(Lead(platform="xhs", public_profile_id=profile.id, status="qualified"))
        content = Content(platform="xhs", platform_content_id=f"note-{suffix}", content_type="note", author_profile_id=profile.id, title="KET备考", url=f"https://www.xiaohongshu.com/explore/note-{suffix}")
        session.add(content)
        session.flush()
        comment = Comment(platform="xhs", platform_comment_id=f"comment-{suffix}", content_id=content.id, author_profile_id=profile.id, body_text="怎么入门")
        session.add(comment)
        session.flush()
        screening = LeadScreeningResult(platform="xhs", source_entity_type=source_type, source_entity_id=comment.id, content_id=content.id, comment_id=comment.id, public_profile_id=profile.id, review_status="accepted", workflow_status="reviewed", human_review_status="valid", demand_type="KET入门", qualification_human_reason="家长询问备考入门", context_json={"current_comment": comment.body_text, "post_title": content.title, "source_url": content.url, "customer_name": profile.display_name})
        session.add(screening)
        session.commit()
        return int(screening.id)


def _seed_pending_reply(factory: sessionmaker[Session], *, suffix: str = "1") -> int:
    screening_id = _seed_comment_screening(factory, suffix=suffix)
    with factory() as session:
        reply = create_comment_reply_for_valid_screening(session, screening_id=screening_id, generator=FakeCommentReplyGenerator(), card_client=FakeCardClient(), chat_id="oc_review")
        session.commit()
        return int(reply.id)


def _payload(reply_id: int, text: str, *, action: str = "confirm", token: str = "token", message_id: str = "om_reply_1", chat_id: str = "oc_review") -> dict[str, Any]:
    return {"token": token, "event": {"token": "update-token", "operator": {"open_id": "ou_reviewer"}, "context": {"open_message_id": message_id, "open_chat_id": chat_id}, "action": {"name": f"{action}_comment_reply_{reply_id}", "form_value": {"comment_reply_text": text}}}}


@contextmanager
def _claim_boundary_barrier(factory: sessionmaker[Session], assignment: str) -> Iterator[None]:
    barrier = Barrier(2)
    engine = factory.kw["bind"]
    seen = 0
    seen_lock = Lock()

    def wait_at_claim(_conn: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _executemany: bool) -> None:
        nonlocal seen
        normalized = "".join(statement.lower().split())
        if not normalized.startswith("updatelead_comment_repliesset") or assignment not in normalized:
            return
        with seen_lock:
            if seen >= 2:
                return
            seen += 1
        barrier.wait(timeout=5)

    event.listen(engine, "before_cursor_execute", wait_at_claim)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", wait_at_claim)
