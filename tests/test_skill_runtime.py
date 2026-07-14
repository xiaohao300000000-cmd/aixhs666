from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from services.skill_runtime import (
    copy_skill_run,
    create_skill_run,
    preview_skill_run,
    queue_skill_run,
    request_skill_run_cancel,
    retry_skill_run,
    update_skill_run_parameters,
)
from storage.database import Base
from storage.models import CollectionTask, Comment, Content, SkillRun


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _campaign_id() -> str:
    from services.skill_registry import list_campaign_options
    return list_campaign_options()[0].campaign_id


def test_preview_queue_duplicate_and_cancel() -> None:
    factory = _factory()
    with factory() as session:
        content = Content(platform="xhs", platform_content_id="c1", content_type="note", body_text="需要课程")
        session.add(content)
        session.flush()
        session.add(Comment(platform="xhs", platform_comment_id="m1", content_id=content.id, body_text="想报名"))
        run = create_skill_run(session, requested_by="ou_1", idempotency_key="create:e1")
        update_skill_run_parameters(session, run.id, {"campaign_id": _campaign_id(), "limit": 10})
        preview = preview_skill_run(session, run.id, event_key="preview:e2")
        first = queue_skill_run(session, run.id, event_key="confirm:e3")
        second = queue_skill_run(session, run.id, event_key="confirm:e4")
        cancelled = request_skill_run_cancel(session, run.id, event_key="cancel:e5")
        session.commit()

        assert preview["candidate_count"] == 2
        assert first.id == second.id
        assert cancelled.status == "cancelled"
        assert session.scalar(select(CollectionTask).where(CollectionTask.target_id == str(run.id))) is not None


def test_failed_retry_and_copy_preserve_parameters() -> None:
    factory = _factory()
    with factory() as session:
        run = create_skill_run(session, requested_by="ou_1")
        update_skill_run_parameters(session, run.id, {"campaign_id": _campaign_id(), "limit": 5})
        run.status = "failed"
        run.error_message = "forced"
        retry_task = retry_skill_run(session, run.id, event_key="retry:e1")
        copied = copy_skill_run(session, run.id, requested_by="ou_2", event_key="copy:e2")
        duplicate_copy = copy_skill_run(session, run.id, requested_by="ou_2", event_key="copy:e2")
        session.commit()

        assert retry_task.task_type == "skill_run_execute"
        assert run.status == "queued"
        assert run.retry_count == 1
        assert copied.status == "draft"
        assert copied.parameters_json == run.parameters_json
        assert copied.copied_from_run_id == run.id
        assert duplicate_copy.id == copied.id
