from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from storage.database import Base
from storage import models
from storage.models import CollectionTask, Lead, LeadCommentReply, PublicProfile


def _reply(session: Session, *, status: str = "pending_review") -> LeadCommentReply:
    profile = PublicProfile(platform="xhs", platform_user_id=f"user-{status}")
    session.add(profile)
    session.flush()
    lead = Lead(platform="xhs", public_profile_id=profile.id, status="qualified")
    session.add(lead)
    session.flush()
    reply = LeadCommentReply(
        lead_id=lead.id,
        target_platform_comment_id=f"comment-{status}",
        target_platform_content_id=f"content-{status}",
        target_url="https://www.xiaohongshu.com/explore/content",
        draft_text="原始草稿",
        status=status,
    )
    session.add(reply)
    session.commit()
    return reply


@pytest.fixture()
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_contact_reply_starts_at_revision_one(factory: sessionmaker[Session]) -> None:
    assert hasattr(models, "ContactCommandOperation")
    ContactCommandOperation = models.ContactCommandOperation
    LeadCommentReply = models.LeadCommentReply
    with factory() as session:
        reply = LeadCommentReply(
            target_platform_comment_id="comment-1",
            target_platform_content_id="content-1",
            draft_text="先了解一下孩子目前最卡的题型。",
        )
        session.add(reply)
        session.commit()

        assert reply.draft_revision == 1
        assert reply.approved_revision is None
        assert reply.queued_at is None


def test_contact_operation_scope_entity_and_key_hash_are_unique(factory: sessionmaker[Session]) -> None:
    assert hasattr(models, "ContactCommandOperation")
    ContactCommandOperation = models.ContactCommandOperation
    with factory() as session:
        session.add(
            ContactCommandOperation(
                operation_scope="edit_contact_draft",
                entity_id=41,
                idempotency_key_hash="a" * 64,
                request_json={"draft_revision": 1},
                result_json={"draft_revision": 2},
            )
        )
        session.commit()
        session.add(
            ContactCommandOperation(
                operation_scope="edit_contact_draft",
                entity_id=41,
                idempotency_key_hash="a" * 64,
                request_json={"draft_revision": 1},
                result_json={"draft_revision": 2},
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_edit_invalidates_approval_and_increments_revision(factory: sessionmaker[Session]) -> None:
    from services.contact_commands import approve_contact_draft, edit_contact_draft

    with factory() as session:
        reply = _reply(session)
        approve_contact_draft(session, reply_id=reply.id, draft_revision=1, operator="op", idempotency_key="approve-1")
        result = edit_contact_draft(session, reply_id=reply.id, draft_revision=1, text="修改后的草稿", operator="op", idempotency_key="edit-1")
        session.commit()
        assert result["draft_revision"] == 2
        assert result["status"] == "awaiting_approval"
        assert reply.approved_revision == 1
        assert reply.approved_text == "原始草稿"


def test_approve_freezes_exact_revision_without_queueing(factory: sessionmaker[Session]) -> None:
    from services.contact_commands import approve_contact_draft

    with factory() as session:
        reply = _reply(session)
        result = approve_contact_draft(session, reply_id=reply.id, draft_revision=1, operator="op", idempotency_key="approve-1")
        session.commit()
        assert result["status"] == "approved"
        assert reply.approved_revision == 1
        assert reply.approved_text == reply.draft_text
        assert session.query(CollectionTask).count() == 0


def test_send_requires_confirmation_and_replays_one_task(factory: sessionmaker[Session]) -> None:
    from services.contact_commands import approve_contact_draft, send_approved_contact

    with factory() as session:
        reply = _reply(session)
        approve_contact_draft(session, reply_id=reply.id, draft_revision=1, operator="op", idempotency_key="approve")
        with pytest.raises(ValueError, match="confirmed"):
            send_approved_contact(session, reply_id=reply.id, draft_revision=1, confirmed=False, operator="op", idempotency_key="send")
        first = send_approved_contact(session, reply_id=reply.id, draft_revision=1, confirmed=True, operator="op", idempotency_key="send")
        second = send_approved_contact(session, reply_id=reply.id, draft_revision=1, confirmed=True, operator="op", idempotency_key="send")
        session.commit()
        assert first == second
        assert first["status"] == "queued"
        assert session.query(CollectionTask).filter_by(task_type="comment_reply_send").count() == 1


def test_stale_approval_and_terminal_sent_are_rejected(factory: sessionmaker[Session]) -> None:
    from services.contact_commands import approve_contact_draft, edit_contact_draft, send_approved_contact

    with factory() as session:
        reply = _reply(session)
        approve_contact_draft(session, reply_id=reply.id, draft_revision=1, operator="op", idempotency_key="approve")
        edit_contact_draft(session, reply_id=reply.id, draft_revision=1, text="v2", operator="op", idempotency_key="edit")
        with pytest.raises(ValueError, match="stale|approved"):
            send_approved_contact(session, reply_id=reply.id, draft_revision=1, confirmed=True, operator="op", idempotency_key="send")
        reply.status = "sent"
        with pytest.raises(ValueError, match="terminal"):
            edit_contact_draft(session, reply_id=reply.id, draft_revision=2, text="v3", operator="op", idempotency_key="edit-2")


def test_result_unknown_requires_manual_not_sent_confirmation(factory: sessionmaker[Session]) -> None:
    from services.contact_commands import confirm_contact_not_sent, record_contact_result

    with factory() as session:
        reply = _reply(session, status="sending")
        reply.attempt_count = 1
        reply.approved_revision = 1
        reply.approved_text = reply.draft_text
        record_contact_result(session, reply_id=reply.id, attempt_count=1, draft_revision=1, outcome="result_unknown", error="timeout", idempotency_key="result")
        assert reply.status == "result_unknown"
        with pytest.raises(ValueError, match="reason"):
            confirm_contact_not_sent(session, reply_id=reply.id, operator="op", reason="", idempotency_key="recover")
        result = confirm_contact_not_sent(session, reply_id=reply.id, operator="op", reason="已打开目标页面核对未发送", idempotency_key="recover")
        assert result["status"] == "failed"
        assert session.query(CollectionTask).filter_by(task_type="comment_reply_send").count() == 0
