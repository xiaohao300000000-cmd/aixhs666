from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime

from sqlalchemy import select

from apps.worker.skill_run import run_skill_run_task
from scheduler import TaskStatus
from services.skill_runtime import SKILL_TASK_TYPE
from storage.database import SessionLocal
from storage.models import CollectionTask


def run_once() -> bool:
    with SessionLocal() as session:
        statement = select(CollectionTask).where(CollectionTask.task_type == SKILL_TASK_TYPE, CollectionTask.status.in_((TaskStatus.PENDING.value, TaskStatus.RETRY.value))).order_by(CollectionTask.priority.desc(), CollectionTask.id.asc()).limit(1)
        if session.bind.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        task = session.scalar(statement)
        if task is None:
            session.commit()
            return False
        task.status = TaskStatus.RUNNING.value
        task.worker_id = "skill-run-worker"
        task.started_at = datetime.now(UTC)
        session.commit()
        run_skill_run_task(session, task=task, session_factory=SessionLocal)
        session.commit()
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run only persisted Skill Runtime tasks.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    while True:
        processed = run_once()
        if args.once:
            return 0
        if not processed:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
