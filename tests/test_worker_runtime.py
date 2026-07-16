from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import storage.models  # noqa: F401
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.main import WorkerConfig, WorkerRunner, build_parser
from collectors import MockPlatformAdapter
from integrations.feishu.comment_replies import CommentReplySendResult
from scheduler import TaskStatus, claim_next_task, create_task
from storage.database import Base
from storage.models import CollectionTask, Content, CustomerFollowupRecord, CustomerTimelineEvent, DiscoveryRelation, Lead, LeadCommentReply, PublicProfile, Query, Snapshot


def test_worker_once_processes_search_task_and_commits(tmp_path: Path) -> None:
    factory = _session_factory()
    with factory() as session:
        query = _query(session, "admissions")
        create_task(session, task_type="search", platform="xhs", query_id=query.id)
        session.commit()

    runner = _runner(factory, tmp_path)
    result = runner.run_once()

    assert result is not None
    with factory() as session:
        task = session.get(CollectionTask, result.id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED.value
        assert session.scalar(select(Content).where(Content.platform_content_id == "note-ai-001")) is not None
        assert session.scalar(select(DiscoveryRelation)) is not None


def test_worker_resumes_partial_search_task(tmp_path: Path) -> None:
    factory = _session_factory()
    with factory() as session:
        query = _query(session, "ai-study")
        create_task(session, task_type="search", platform="xhs", query_id=query.id, payload_json={"limit": 1})
        session.commit()

    runner = _runner(factory, tmp_path)
    first = runner.run_once()
    second = runner.run_once()

    assert first is not None
    assert second is not None
    with factory() as session:
        task = session.get(CollectionTask, first.id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED.value
        content_ids = list(session.scalars(select(Content.platform_content_id).order_by(Content.platform_content_id)))
        assert content_ids == ["note-ai-001", "note-ai-002"]


def test_worker_handles_unsupported_task_without_exiting(tmp_path: Path) -> None:
    factory = _session_factory()
    with factory() as session:
        unsupported = create_task(
            session,
            task_type="unsupported",
            platform="xhs",
            priority=10,
            max_attempts=1,
        )
        query = _query(session, "admissions")
        create_task(session, task_type="search", platform="xhs", query_id=query.id, priority=0)
        session.commit()

    runner = _runner(factory, tmp_path)
    failed = runner.run_once()
    processed = runner.run_once()

    assert failed is not None
    assert processed is not None
    with factory() as session:
        failed_task = session.get(CollectionTask, unsupported.id)
        assert failed_task is not None
        assert failed_task.status == TaskStatus.FAILED.value
        assert failed_task.last_error == "unsupported task type: unsupported"
        search_task = session.get(CollectionTask, processed.id)
        assert search_task is not None
        assert search_task.status == TaskStatus.COMPLETED.value


def test_worker_recovers_timed_out_task_before_claiming(tmp_path: Path) -> None:
    factory = _session_factory()
    old_now = datetime(2026, 1, 1, tzinfo=UTC)
    with factory() as session:
        query = _query(session, "admissions")
        task = create_task(session, task_type="search", platform="xhs", query_id=query.id, now=old_now)
        claim_next_task(session, worker_id="stale-worker", now=old_now)
        task.started_at = old_now - timedelta(hours=2)
        session.commit()

    runner = _runner(factory, tmp_path, task_timeout_minutes=30)
    result = runner.run_once()

    assert result is not None
    with factory() as session:
        task = session.get(CollectionTask, result.id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED.value
        assert task.last_error is None


def test_worker_processes_profile_task(tmp_path: Path) -> None:
    factory = _session_factory()
    with factory() as session:
        create_task(session, task_type="profile", platform="xhs", target_id="user-author-001")
        session.commit()

    runner = _runner(factory, tmp_path)
    result = runner.run_once()

    assert result is not None
    with factory() as session:
        task = session.get(CollectionTask, result.id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED.value
        profile = session.scalar(select(PublicProfile).where(PublicProfile.platform_user_id == "user-author-001"))
        assert profile is not None
        assert profile.display_name == "AI Admissions Lab"
        snapshot = session.scalar(select(Snapshot).where(Snapshot.entity_type == "profile"))
        assert snapshot is not None
        assert Path(snapshot.object_storage_path).exists()


def test_worker_dispatches_comment_reply_send_task_once(monkeypatch, tmp_path: Path) -> None:
    factory = _session_factory()
    calls: list[tuple[int, int, str | None]] = []
    monkeypatch.setenv("COMMENT_REPLY_BROWSER_MODE", "remote_cdp")
    monkeypatch.setenv("COMMENT_REPLY_CDP_URL", "http://100.124.24.8:19223")
    with factory() as session:
        reply = LeadCommentReply(
            screening_result_id=1,
            target_comment_id=1,
            target_platform_comment_id="comment-1",
            target_content_id=1,
            target_platform_content_id="note-1",
            draft_text="草稿",
            approved_text="最终回复",
            status="approved_to_send",
        )
        session.add(reply)
        session.flush()
        create_task(
            session,
            task_type="comment_reply_send",
            platform="xhs",
            target_id=str(reply.id),
            payload_json={"update_token": "card-token", "draft_revision": 1},
            max_attempts=1,
        )
        session.commit()

    class Result:
        status = "sent"

    def execute(session_factory, *, reply_id, draft_revision, update_token, card_client, sender):
        del session_factory, card_client, sender
        calls.append((reply_id, draft_revision, update_token))
        with factory() as session:
            reply = session.get(LeadCommentReply, reply_id)
            assert reply is not None
            reply.status = "sent"
            session.commit()
        return Result()

    monkeypatch.setattr("apps.worker.comment_reply_send.execute_approved_comment_reply", execute)
    monkeypatch.setattr("apps.worker.comment_reply_send.push_customer_followup", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.worker.comment_reply_send.FeishuIMClient", object)
    monkeypatch.setattr("apps.worker.comment_reply_send.XiaohongshuCommentReplySender", lambda config: object())

    runner = _runner(factory, tmp_path)
    first = runner.run_once()
    second = runner.run_once()

    assert first is not None
    assert second is None
    assert calls == [(1, 1, "card-token")]
    with factory() as session:
        task = session.get(CollectionTask, first.id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED.value
        reply = session.get(LeadCommentReply, 1)
        assert reply is not None
        assert reply.status == "sent"


def test_worker_projection_failure_keeps_core_result_and_never_resends(monkeypatch, tmp_path: Path) -> None:
    factory = _session_factory()
    sender_calls: list[str] = []
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="projection-failure")
        session.add(profile)
        session.flush()
        lead = Lead(platform="xhs", public_profile_id=profile.id, status="qualified")
        session.add(lead)
        session.flush()
        reply = LeadCommentReply(
            lead_id=lead.id,
            target_platform_comment_id="comment-projection",
            target_platform_content_id="note-projection",
            target_url="https://www.xiaohongshu.com/explore/note-projection",
            draft_text="最终回复",
            approved_text="最终回复",
            draft_revision=1,
            approved_revision=1,
            status="queued",
        )
        session.add(reply)
        session.flush()
        create_task(session, task_type="comment_reply_send", platform="xhs", target_id=str(reply.id), payload_json={"draft_revision": 1}, max_attempts=1)
        session.commit()

    class Sender:
        def reply_to_comment(self, **_: str) -> CommentReplySendResult:
            sender_calls.append("sent")
            return CommentReplySendResult(outcome="sent", platform_reply_id="platform-projection")

    monkeypatch.setattr("apps.worker.comment_reply_send._remote_comment_reply_sender", lambda: Sender())
    monkeypatch.setattr("apps.worker.comment_reply_send.FeishuIMClient", object)
    monkeypatch.setattr("apps.worker.comment_reply_send.push_customer_followup", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.worker.comment_reply_send.sync_customer_crm", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Base projection unavailable")))

    runner = _runner(factory, tmp_path)
    first = runner.run_once()
    second = runner.run_once()

    assert first is not None
    assert second is None
    assert sender_calls == ["sent"]
    with factory() as session:
        reply = session.scalar(select(LeadCommentReply).where(LeadCommentReply.target_platform_comment_id == "comment-projection"))
        lead = session.get(Lead, reply.lead_id)
        assert reply.status == "sent"
        assert lead.crm_stage == "contact_sent_waiting_reply"
        assert lead.last_contact_result == "public_reply_sent"
        assert session.query(CustomerFollowupRecord).filter_by(lead_id=lead.id, result="sent").count() == 1
        assert session.query(CustomerTimelineEvent).filter_by(lead_id=lead.id, event_type="contact_result_sent").count() == 1


def test_worker_dispatches_comment_reply_prepare_without_browser_sender(monkeypatch, tmp_path: Path) -> None:
    factory = _session_factory()
    calls: list[int] = []
    with factory() as session:
        create_task(
            session,
            task_type="comment_reply_prepare",
            platform="xhs",
            target_id="7",
            payload_json={"screening_id": 9, "chat_id": "oc_test"},
            max_attempts=3,
        )
        session.commit()

    def prepare(session_factory, *, screening_id, chat_id):
        del session_factory, chat_id
        calls.append(screening_id)

    monkeypatch.setattr("apps.worker.comment_reply_prepare.prepare_comment_reply", prepare)
    runner = _runner(factory, tmp_path)
    result = runner.run_once()

    assert result is not None
    assert calls == [9]
    with factory() as session:
        assert session.get(CollectionTask, result.id).status == TaskStatus.COMPLETED.value


def test_worker_refuses_local_browser_for_comment_reply_send(monkeypatch, tmp_path: Path) -> None:
    factory = _session_factory()
    calls: list[int] = []
    monkeypatch.setenv("COMMENT_REPLY_BROWSER_MODE", "local")
    monkeypatch.delenv("COMMENT_REPLY_CDP_URL", raising=False)
    with factory() as session:
        reply = LeadCommentReply(
            screening_result_id=1,
            target_comment_id=1,
            target_platform_comment_id="comment-1",
            target_content_id=1,
            target_platform_content_id="note-1",
            draft_text="草稿",
            approved_text="最终回复",
            status="approved_to_send",
        )
        session.add(reply)
        session.flush()
        create_task(
            session,
            task_type="comment_reply_send",
            platform="xhs",
            target_id=str(reply.id),
            payload_json={"draft_revision": 1},
            max_attempts=1,
        )
        session.commit()

    def execute(*args, **kwargs):
        del args, kwargs
        calls.append(1)
        return type("Result", (), {"status": "sent"})()

    monkeypatch.setattr("apps.worker.comment_reply_send.execute_approved_comment_reply", execute)
    monkeypatch.setattr("apps.worker.comment_reply_send.push_customer_followup", lambda *args, **kwargs: None)

    runner = _runner(factory, tmp_path)
    processed = runner.run_once()

    assert processed is not None
    assert calls == []
    with factory() as session:
        task = session.get(CollectionTask, processed.id)
        assert task is not None
        assert task.status == TaskStatus.FAILED.value
        assert task.last_error == "comment reply send tasks require COMMENT_REPLY_BROWSER_MODE=remote_cdp"
        reply = session.get(LeadCommentReply, 1)
        assert reply is not None
        assert reply.status == "approved_to_send"


def test_worker_requires_remote_cdp_url_for_comment_reply_send(monkeypatch, tmp_path: Path) -> None:
    factory = _session_factory()
    calls: list[int] = []
    monkeypatch.setenv("COMMENT_REPLY_BROWSER_MODE", "remote_cdp")
    monkeypatch.delenv("COMMENT_REPLY_CDP_URL", raising=False)
    with factory() as session:
        reply = LeadCommentReply(
            screening_result_id=1,
            target_comment_id=1,
            target_platform_comment_id="comment-1",
            target_content_id=1,
            target_platform_content_id="note-1",
            draft_text="草稿",
            approved_text="最终回复",
            status="approved_to_send",
        )
        session.add(reply)
        session.flush()
        create_task(
            session,
            task_type="comment_reply_send",
            platform="xhs",
            target_id=str(reply.id),
            payload_json={"draft_revision": 1},
            max_attempts=1,
        )
        session.commit()

    def execute(*args, **kwargs):
        del args, kwargs
        calls.append(1)
        return type("Result", (), {"status": "sent"})()

    monkeypatch.setattr("apps.worker.comment_reply_send.execute_approved_comment_reply", execute)
    monkeypatch.setattr("apps.worker.comment_reply_send.push_customer_followup", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.worker.comment_reply_send.XiaohongshuCommentReplySender", lambda config: object())

    runner = _runner(factory, tmp_path)
    processed = runner.run_once()

    assert processed is not None
    assert calls == []
    with factory() as session:
        task = session.get(CollectionTask, processed.id)
        assert task is not None
        assert task.status == TaskStatus.FAILED.value
        assert task.last_error == "comment reply send tasks require COMMENT_REPLY_CDP_URL"
        reply = session.get(LeadCommentReply, 1)
        assert reply is not None
        assert reply.status == "approved_to_send"


def test_worker_cli_parser_supports_once_and_worker_id() -> None:
    args = build_parser().parse_args(["--once", "--worker-id", "worker-test", "--poll-interval", "0.1"])

    assert args.once is True
    assert args.worker_id == "worker-test"
    assert args.poll_interval == 0.1


def _runner(
    factory: sessionmaker[Session],
    tmp_path: Path,
    *,
    task_timeout_minutes: int = 20,
) -> WorkerRunner:
    config = WorkerConfig(
        worker_id="worker-test",
        poll_interval_seconds=0,
        task_timeout_minutes=task_timeout_minutes,
        snapshot_root=tmp_path,
        once=True,
    )
    return WorkerRunner(
        session_factory=factory,
        adapter=MockPlatformAdapter(),
        config=config,
        sleep=lambda _seconds: None,
    )


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _query(session: Session, query_text: str) -> Query:
    query = Query(
        query_text=query_text,
        platform="xhs",
        query_type="seed",
        status="active",
        source="test",
    )
    session.add(query)
    session.flush()
    return query
