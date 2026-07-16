from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from threading import Barrier, Lock

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from storage.database import Base
from storage import models
from storage.models import CollectionTask, Comment, ContactCommandOperation, Content, CustomerTimelineEvent, Lead, LeadCommentReply, LeadScreeningResult, PublicProfile


def _reply(session: Session, *, status: str = "pending_review", suffix: str = "") -> LeadCommentReply:
    unique = f"-{suffix}" if suffix else ""
    profile = PublicProfile(platform="xhs", platform_user_id=f"user-{status}{unique}")
    session.add(profile)
    session.flush()
    lead = Lead(platform="xhs", public_profile_id=profile.id, status="qualified")
    session.add(lead)
    session.flush()
    reply = LeadCommentReply(
        lead_id=lead.id,
        target_platform_comment_id=f"comment-{status}{unique}",
        target_platform_content_id=f"content-{status}{unique}",
        target_url="https://www.xiaohongshu.com/explore/content",
        draft_text="原始草稿",
        status=status,
    )
    session.add(reply)
    session.commit()
    return reply


def _qualified_comment_lead(session: Session, *, suffix: str) -> Lead:
    profile = PublicProfile(platform="xhs", platform_user_id=f"prepare-user-{suffix}")
    session.add(profile)
    session.flush()
    lead = Lead(platform="xhs", public_profile_id=profile.id, status="qualified")
    content = Content(
        platform="xhs",
        platform_content_id=f"prepare-content-{suffix}",
        content_type="note",
        author_profile_id=profile.id,
        url=f"https://www.xiaohongshu.com/explore/prepare-{suffix}",
    )
    session.add_all([lead, content])
    session.flush()
    comment = Comment(
        platform="xhs",
        platform_comment_id=f"prepare-comment-{suffix}",
        content_id=content.id,
        author_profile_id=profile.id,
        body_text="孩子怎么规划？",
    )
    session.add(comment)
    session.flush()
    session.add(
        LeadScreeningResult(
            platform="xhs",
            source_entity_type="comment",
            source_entity_id=comment.id,
            content_id=content.id,
            comment_id=comment.id,
            public_profile_id=profile.id,
            review_status="accepted",
            human_review_status="valid",
            workflow_status="reviewed",
        )
    )
    session.commit()
    return lead


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


def test_prepare_target_unavailable_has_stable_result_shape(factory: sessionmaker[Session]) -> None:
    from services.contact_commands import prepare_contact_draft

    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="prepare-no-target")
        session.add(profile)
        session.flush()
        lead = Lead(platform="xhs", public_profile_id=profile.id, status="qualified")
        session.add(lead)
        session.commit()

        result = prepare_contact_draft(session, customer_id=lead.id, idempotency_key="prepare-no-target")

        assert result == {
            "status": "target_unavailable",
            "customer_id": lead.id,
            "screening_id": None,
            "task_id": None,
            "task_status": None,
            "failure_reason": None,
        }


@pytest.mark.parametrize(
    ("stored_status", "expected_status"),
    [("pending", "pending"), ("running", "running"), ("retry", "retry"), ("failed", "failed"), ("completed", "completed")],
)
def test_prepare_replay_observes_persistent_task_without_exposing_worker_secrets(
    factory: sessionmaker[Session],
    stored_status: str,
    expected_status: str,
) -> None:
    from services.contact_commands import prepare_contact_draft

    key = f"prepare-observe-{stored_status}"
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id=f"prepare-{stored_status}")
        session.add(profile)
        session.flush()
        lead = Lead(platform="xhs", public_profile_id=profile.id, status="qualified")
        task = CollectionTask(
            task_type="comment_reply_prepare",
            platform="xhs",
            target_id="pending",
            status=stored_status,
            last_error="Traceback token=secret CDP cookie=xhs_cookie at /private/path",
        )
        session.add_all([lead, task])
        session.flush()
        task.target_id = str(lead.id)
        session.add(
            ContactCommandOperation(
                operation_scope="prepare_contact_draft",
                entity_id=lead.id,
                idempotency_key_hash=hashlib.sha256(key.encode()).hexdigest(),
                request_json={"customer_id": lead.id},
                result_json={"status": "queued", "customer_id": lead.id, "screening_id": 9, "task_id": task.id},
            )
        )
        session.commit()

        result = prepare_contact_draft(session, customer_id=lead.id, idempotency_key=key)

        assert result["task_status"] == expected_status
        assert result["failure_reason"] == ("草稿生成失败，请检查任务中心后重新生成。" if stored_status == "failed" else None)
        assert "secret" not in str(result)
        assert "cookie" not in str(result).lower()


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


def test_reapproving_same_revision_with_new_key_is_stable(factory: sessionmaker[Session]) -> None:
    from services.contact_commands import approve_contact_draft

    with factory() as session:
        reply = _reply(session)
        first = approve_contact_draft(session, reply_id=reply.id, draft_revision=1, operator="op", idempotency_key="approve-1")
        second = approve_contact_draft(session, reply_id=reply.id, draft_revision=1, operator="op", idempotency_key="approve-2")
        session.commit()

        assert second == first
        assert session.query(models.CustomerTimelineEvent).filter_by(event_type="contact_draft_approved").count() == 1


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
        with pytest.raises(ValueError, match="cannot be edited"):
            edit_contact_draft(session, reply_id=reply.id, draft_revision=2, text="v3", operator="op", idempotency_key="edit-2")


@pytest.mark.parametrize("status", ["queued", "approved_to_send", "sending", "result_unknown", "sent", "cancelled"])
def test_draft_edit_rejects_every_send_fenced_state(factory: sessionmaker[Session], status: str) -> None:
    from services.contact_commands import edit_contact_draft

    with factory() as session:
        reply = _reply(session, status=status)
        original_revision = reply.draft_revision
        with pytest.raises(ValueError, match="cannot be edited"):
            edit_contact_draft(session, reply_id=reply.id, draft_revision=original_revision, text="不能覆盖发送版本", operator="op", idempotency_key=f"edit-{status}")
        assert reply.draft_revision == original_revision
        assert reply.status == status


def test_sending_revision_cannot_change_and_its_original_result_remains_fenced(factory: sessionmaker[Session]) -> None:
    from services.contact_commands import edit_contact_draft, record_contact_result, send_approved_contact

    with factory() as session:
        reply = _reply(session, status="sending")
        reply.approved_text = reply.draft_text
        reply.approved_revision = 1
        reply.attempt_count = 1
        with pytest.raises(ValueError, match="cannot be edited"):
            edit_contact_draft(session, reply_id=reply.id, draft_revision=1, text="恶意新版本", operator="op", idempotency_key="edit-during-send")

        result = record_contact_result(session, reply_id=reply.id, attempt_count=1, draft_revision=1, outcome="sent", platform_reply_id="platform-1", idempotency_key="result-1")
        assert result["status"] == "sent"
        with pytest.raises(ValueError):
            send_approved_contact(session, reply_id=reply.id, draft_revision=1, confirmed=True, operator="op", idempotency_key="send-again")
        assert session.query(CollectionTask).filter_by(task_type="comment_reply_send").count() == 0


@pytest.mark.postgres
def test_postgres_different_send_keys_persist_exactly_one_task_and_queue_event() -> None:
    from services.contact_commands import send_approved_contact

    database_url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is required for the send serialization test")
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    postgres_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with postgres_factory() as session:
        reply = _reply(session, status="approved", suffix="different-keys")
        reply.approved_text = reply.draft_text
        reply.approved_revision = reply.draft_revision
        session.commit()
        reply_id = reply.id

    boundary = Barrier(2)
    observed_threads: set[int] = set()
    observed_lock = Lock()

    @event.listens_for(engine, "before_cursor_execute")
    def synchronize_reply_reads(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:  # type: ignore[no-untyped-def]
        if "FROM lead_comment_replies" not in statement:
            return
        from threading import get_ident

        thread_id = get_ident()
        with observed_lock:
            if thread_id in observed_threads:
                return
            observed_threads.add(thread_id)
        boundary.wait(timeout=10)

    def enqueue(key: str) -> str:
        with postgres_factory() as session:
            try:
                result = send_approved_contact(
                    session,
                    reply_id=reply_id,
                    draft_revision=1,
                    confirmed=True,
                    operator="concurrent-operator",
                    idempotency_key=key,
                )
                session.commit()
                return str(result["status"])
            except ValueError:
                session.rollback()
                return "state_conflict"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(enqueue, ("miaoda-send", "feishu-send")))
        with postgres_factory() as session:
            task_count = session.scalar(select(func.count()).select_from(CollectionTask).where(CollectionTask.task_type == "comment_reply_send"))
            queue_events = list(session.scalars(select(CustomerTimelineEvent).where(CustomerTimelineEvent.event_type == "contact_send_queued")))
        assert sorted(results) == ["queued", "state_conflict"]
        assert task_count == 1
        assert len(queue_events) == 1
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_reply_reads)
        engine.dispose()


@pytest.mark.postgres
def test_postgres_preloaded_reply_different_send_keys_refresh_after_lock() -> None:
    from services.contact_commands import send_approved_contact

    database_url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is required for preloaded send serialization")
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    postgres_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with postgres_factory() as session:
        reply = _reply(session, status="approved", suffix="preloaded")
        reply.approved_text = reply.draft_text
        reply.approved_revision = reply.draft_revision
        session.commit()
        reply_id = reply.id
        lead_id = reply.lead_id

    lock_boundary = Barrier(2)
    observed_threads: set[int] = set()
    observed_lock = Lock()
    refresh_guarantees: list[bool] = []

    @event.listens_for(engine, "before_cursor_execute")
    def synchronize_lock_reads(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:  # type: ignore[no-untyped-def]
        normalized = statement.lower()
        if "from lead_comment_replies" not in normalized or "for update" not in normalized:
            return
        orm_options = _context.execution_options.get("_sa_orm_load_options")
        refresh_guarantees.append(bool(getattr(orm_options, "_populate_existing", False)))
        from threading import get_ident

        thread_id = get_ident()
        with observed_lock:
            if thread_id in observed_threads:
                return
            observed_threads.add(thread_id)
        lock_boundary.wait(timeout=10)

    preload_boundary = Barrier(2)

    def enqueue(key: str) -> str:
        with postgres_factory() as session:
            assert session.get(LeadCommentReply, reply_id).status == "approved"
            preload_boundary.wait(timeout=10)
            try:
                result = send_approved_contact(
                    session,
                    reply_id=reply_id,
                    draft_revision=1,
                    confirmed=True,
                    operator="preloaded-entry",
                    idempotency_key=key,
                )
                session.commit()
                return str(result["status"])
            except ValueError:
                session.rollback()
                return "state_conflict"
            except Exception as exc:  # pragma: no cover - asserted as a RED failure value
                session.rollback()
                return f"unexpected:{type(exc).__name__}"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(enqueue, ("preloaded-miaoda", "preloaded-feishu")))
        with postgres_factory() as session:
            task_count = session.scalar(
                select(func.count()).select_from(CollectionTask).where(
                    CollectionTask.task_type == "comment_reply_send",
                    CollectionTask.target_id == str(reply_id),
                )
            )
            event_count = session.scalar(
                select(func.count()).select_from(CustomerTimelineEvent).where(
                    CustomerTimelineEvent.lead_id == lead_id,
                    CustomerTimelineEvent.event_type == "contact_send_queued",
                )
            )
        assert sorted(results) == ["queued", "state_conflict"]
        assert refresh_guarantees and all(refresh_guarantees)
        assert task_count == 1
        assert event_count == 1
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_lock_reads)
        engine.dispose()


@pytest.mark.postgres
def test_postgres_same_send_key_concurrently_replays_first_result() -> None:
    from services.contact_commands import send_approved_contact

    database_url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is required for concurrent idempotency replay")
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    postgres_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with postgres_factory() as session:
        reply = _reply(session, status="approved", suffix="same-key")
        reply.approved_text = reply.draft_text
        reply.approved_revision = reply.draft_revision
        session.commit()
        reply_id = reply.id

    boundary = Barrier(2)
    observed_threads: set[int] = set()
    observed_lock = Lock()

    @event.listens_for(engine, "before_cursor_execute")
    def synchronize_lock_reads(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:  # type: ignore[no-untyped-def]
        normalized = statement.lower()
        if "from lead_comment_replies" not in normalized or "for update" not in normalized:
            return
        from threading import get_ident

        thread_id = get_ident()
        with observed_lock:
            if thread_id in observed_threads:
                return
            observed_threads.add(thread_id)
        boundary.wait(timeout=10)

    def enqueue() -> tuple[str, int | None]:
        with postgres_factory() as session:
            try:
                result = send_approved_contact(
                    session,
                    reply_id=reply_id,
                    draft_revision=1,
                    confirmed=True,
                    operator="same-request",
                    idempotency_key="same-concurrent-send-key",
                )
                session.commit()
                return str(result["status"]), int(result["task_id"])
            except Exception as exc:  # pragma: no cover - asserted as a RED failure value
                session.rollback()
                return f"{type(exc).__name__}:{exc}", None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: enqueue(), range(2)))
        assert [status for status, _ in results] == ["queued", "queued"]
        assert len({task_id for _, task_id in results}) == 1
        with postgres_factory() as session:
            operation_count = session.scalar(
                select(func.count()).select_from(ContactCommandOperation).where(
                    ContactCommandOperation.operation_scope == "send_approved_contact",
                    ContactCommandOperation.entity_id == reply_id,
                )
            )
        assert operation_count == 1
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_lock_reads)
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.parametrize("keys", [("same-prepare", "same-prepare"), ("promotion-prepare", "miaoda-prepare")])
def test_postgres_concurrent_prepare_keys_share_one_persistent_task(keys: tuple[str, str]) -> None:
    from services.contact_commands import prepare_contact_draft

    database_url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is required for prepare serialization")
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    postgres_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    suffix = hashlib.sha256("|".join(keys).encode()).hexdigest()[:10]
    with postgres_factory() as session:
        lead = _qualified_comment_lead(session, suffix=suffix)
        customer_id = lead.id

    boundary = Barrier(2)
    observed_threads: set[int] = set()
    observed_lock = Lock()

    @event.listens_for(engine, "before_cursor_execute")
    def synchronize_lead_reads(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:  # type: ignore[no-untyped-def]
        if "from leads" not in statement.lower():
            return
        from threading import get_ident

        thread_id = get_ident()
        with observed_lock:
            if thread_id in observed_threads:
                return
            observed_threads.add(thread_id)
        boundary.wait(timeout=10)

    def prepare(key: str) -> tuple[str, int | None]:
        with postgres_factory() as session:
            try:
                result = prepare_contact_draft(session, customer_id=customer_id, idempotency_key=key)
                session.commit()
                return str(result["status"]), int(result["task_id"])
            except Exception as exc:  # pragma: no cover - asserted as a RED failure value
                session.rollback()
                return f"{type(exc).__name__}:{exc}", None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(prepare, keys))
        assert [status for status, _ in results] == ["queued", "queued"]
        assert len({task_id for _, task_id in results}) == 1
        with postgres_factory() as session:
            task_count = session.scalar(
                select(func.count()).select_from(CollectionTask).where(
                    CollectionTask.task_type == "comment_reply_prepare",
                    CollectionTask.target_id == str(customer_id),
                )
            )
            operation_count = session.scalar(
                select(func.count()).select_from(ContactCommandOperation).where(
                    ContactCommandOperation.operation_scope == "prepare_contact_draft",
                    ContactCommandOperation.entity_id == customer_id,
                )
            )
        assert task_count == 1
        assert operation_count == len(set(keys))
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_lead_reads)
        engine.dispose()


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
