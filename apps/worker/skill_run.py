from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from scheduler import complete_task, fail_task
from services.skill_runtime import execute_skill_run
from storage.models import CollectionTask

SKILL_RUN_TASK_TYPES = {"skill_run_execute"}


def run_skill_run_task(session: Session, *, task: CollectionTask, session_factory: sessionmaker[Session]) -> CollectionTask:
    try:
        run_id = int(task.target_id or (task.payload_json or {}).get("skill_run_id"))
    except (TypeError, ValueError) as exc:
        fail_task(session, task.id, error="invalid skill run target id")
        raise ValueError("invalid skill run target id") from exc
    session.commit()
    def update_card(updated_run_id: int) -> None:
        from services.feishu_task_center import update_skill_run_message
        with session_factory() as projection_session:
            update_skill_run_message(projection_session, updated_run_id)

    run = execute_skill_run(session_factory, run_id, progress_callback=update_card)
    refreshed = session.get(CollectionTask, task.id)
    if refreshed is None:
        raise ValueError(f"collection task not found: {task.id}")
    if run.status in {"succeeded", "cancelled"}:
        return complete_task(session, refreshed.id)
    failed = fail_task(session, refreshed.id, error=run.error_message or "skill run failed")
    raise RuntimeError(failed.last_error)
