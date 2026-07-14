from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.comment_collection import COMMENT_TASK_TYPES, run_comment_task
from apps.worker.comment_reply_send import COMMENT_REPLY_SEND_TASK_TYPES, run_comment_reply_send_task
from apps.worker.detail_collection import DETAIL_TASK_TYPES, run_detail_task
from apps.worker.profile_collection import PROFILE_TASK_TYPES, run_profile_task
from apps.worker.resume import start_partial_task
from apps.worker.search_collection import SEARCH_TASK_TYPES, run_search_task
from collectors import MediaCrawlerXiaohongshuAdapter, MockPlatformAdapter, PlatformAdapter, XiaohongshuAdapter
from scheduler import TaskStatus, claim_next_task, fail_task, recover_timed_out_tasks
from storage.database import SessionLocal
from storage.models import CollectionTask, WorkerHeartbeat


logger = logging.getLogger(__name__)

TASK_TYPES_WITH_PARTIAL_RESUME = SEARCH_TASK_TYPES | COMMENT_TASK_TYPES


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    worker_id: str
    poll_interval_seconds: float
    task_timeout_minutes: int
    snapshot_root: Path
    once: bool = False

    @classmethod
    def from_env(
        cls,
        *,
        worker_id: str | None = None,
        poll_interval_seconds: float | None = None,
        task_timeout_minutes: int | None = None,
        snapshot_root: str | Path | None = None,
        once: bool = False,
    ) -> "WorkerConfig":
        return cls(
            worker_id=worker_id or os.getenv("WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}",
            poll_interval_seconds=(
                poll_interval_seconds
                if poll_interval_seconds is not None
                else float(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "5"))
            ),
            task_timeout_minutes=(
                task_timeout_minutes
                if task_timeout_minutes is not None
                else int(os.getenv("WORKER_TASK_TIMEOUT_MINUTES", "20"))
            ),
            snapshot_root=Path(snapshot_root or os.getenv("WORKER_SNAPSHOT_ROOT", ".runtime/storage-snapshots")),
            once=once,
        )


class WorkerRunner:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        adapter: PlatformAdapter,
        config: WorkerConfig,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session_factory = session_factory
        self.adapter = adapter
        self.config = config
        self._sleep = sleep
        self._stop_requested = False

    def request_stop(self, signum: int | None = None, frame: object | None = None) -> None:
        del frame
        if signum is None:
            logger.info("worker stop requested")
        else:
            logger.info("worker stop requested by signal %s", signum)
        self._stop_requested = True

    def run(self) -> None:
        while not self._stop_requested:
            processed = self.run_once()
            if self.config.once:
                break
            if processed is None and not self._stop_requested:
                self._sleep(self.config.poll_interval_seconds)

    def run_once(self) -> CollectionTask | None:
        with self.session_factory() as session:
            self._heartbeat(session, status="idle", current_task_id=None)
            self._recover_timed_out_tasks(session)
            task = claim_next_task(session, worker_id=self.config.worker_id)
            if task is None:
                task = self._claim_partial_task(session)
            if task is None:
                session.commit()
                return None
            try:
                self._heartbeat(session, status="running", current_task_id=task.id)
                result = self._dispatch(session, task)
                self._heartbeat(session, status="idle", current_task_id=None, completed_delta=1)
                session.commit()
                return result
            except Exception as exc:
                logger.exception("collection task %s failed", task.id)
                self._heartbeat(
                    session,
                    status="error",
                    current_task_id=None,
                    failed_delta=1,
                    last_error=str(exc),
                )
                try:
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
                return task

    def _heartbeat(
        self,
        session: Session,
        *,
        status: str,
        current_task_id: int | None,
        completed_delta: int = 0,
        failed_delta: int = 0,
        last_error: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        heartbeat = session.get(WorkerHeartbeat, self.config.worker_id)
        if heartbeat is None:
            heartbeat = WorkerHeartbeat(
                worker_id=self.config.worker_id,
                started_at=now,
                completed_task_count=0,
                failed_task_count=0,
            )
            session.add(heartbeat)
        heartbeat.status = status
        heartbeat.current_task_id = current_task_id
        heartbeat.last_heartbeat_at = now
        heartbeat.completed_task_count = (heartbeat.completed_task_count or 0) + completed_delta
        heartbeat.failed_task_count = (heartbeat.failed_task_count or 0) + failed_delta
        if last_error is not None:
            heartbeat.last_error = last_error
        heartbeat.metadata_json = {
            "adapter": type(self.adapter).__name__,
            "snapshot_root": str(self.config.snapshot_root),
            "task_timeout_minutes": self.config.task_timeout_minutes,
        }
        session.flush()

    def _recover_timed_out_tasks(self, session: Session) -> None:
        recovered = recover_timed_out_tasks(
            session,
            timeout_after=timedelta(minutes=self.config.task_timeout_minutes),
            recovery_status=TaskStatus.RETRY,
            error_message="worker heartbeat expired",
        )
        if recovered:
            logger.info("recovered %s timed out task(s)", len(recovered))

    def _claim_partial_task(self, session: Session) -> CollectionTask | None:
        partial = session.scalar(
            select(CollectionTask)
            .where(CollectionTask.status == TaskStatus.PARTIAL.value)
            .where(CollectionTask.task_type.in_(TASK_TYPES_WITH_PARTIAL_RESUME))
            .order_by(CollectionTask.priority.desc(), CollectionTask.finished_at.asc(), CollectionTask.id.asc())
            .limit(1)
        )
        if partial is None:
            return None
        return start_partial_task(
            session,
            task_id=partial.id,
            worker_id=self.config.worker_id,
            allowed_task_types=TASK_TYPES_WITH_PARTIAL_RESUME,
        )

    def _dispatch(self, session: Session, task: CollectionTask) -> CollectionTask:
        if task.task_type in SEARCH_TASK_TYPES:
            return run_search_task(
                session,
                task=task,
                adapter=self.adapter,
                snapshot_root=self.config.snapshot_root,
            )
        if task.task_type in DETAIL_TASK_TYPES:
            return run_detail_task(
                session,
                task=task,
                adapter=self.adapter,
                snapshot_root=self.config.snapshot_root,
            )
        if task.task_type in COMMENT_TASK_TYPES:
            return run_comment_task(
                session,
                task=task,
                adapter=self.adapter,
                snapshot_root=self.config.snapshot_root,
            )
        if task.task_type in PROFILE_TASK_TYPES:
            return run_profile_task(
                session,
                task=task,
                adapter=self.adapter,
                snapshot_root=self.config.snapshot_root,
            )
        if task.task_type in COMMENT_REPLY_SEND_TASK_TYPES:
            return run_comment_reply_send_task(
                session,
                task=task,
                session_factory=self.session_factory,
            )
        fail_task(session, task.id, error=f"unsupported task type: {task.task_type}")
        raise ValueError(f"unsupported task type: {task.task_type}")


def load_adapter(platform: str) -> PlatformAdapter:
    adapter_name = os.getenv("WORKER_ADAPTER", "mediacrawler").strip().casefold()
    if adapter_name == "mock":
        return MockPlatformAdapter(platform=platform)
    if platform != "xhs":
        raise ValueError(f"unsupported platform for real adapter: {platform}")
    if adapter_name in {"mediacrawler", "media_crawler"}:
        return MediaCrawlerXiaohongshuAdapter()
    if adapter_name not in {"xiaohongshu", "xhs", "playwright"}:
        raise ValueError(f"unsupported WORKER_ADAPTER: {adapter_name}")
    return XiaohongshuAdapter()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the collection worker.")
    parser.add_argument("--once", action="store_true", help="Process at most one task and exit.")
    parser.add_argument("--worker-id", default=os.getenv("WORKER_ID"), help="Stable worker identifier.")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        help="Polling interval in seconds when no task is available.",
    )
    parser.add_argument(
        "--task-timeout-minutes",
        type=int,
        default=None,
        help="Recover running tasks older than this many minutes.",
    )
    parser.add_argument("--platform", default=os.getenv("WORKER_PLATFORM", "xhs"), help="Platform to collect.")
    parser.add_argument(
        "--snapshot-root",
        default=os.getenv("WORKER_SNAPSHOT_ROOT"),
        help="Directory for normalized storage snapshots.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=os.getenv("WORKER_LOG_LEVEL", "INFO"))
    args = build_parser().parse_args(argv)
    config = WorkerConfig.from_env(
        worker_id=args.worker_id,
        poll_interval_seconds=args.poll_interval,
        task_timeout_minutes=args.task_timeout_minutes,
        snapshot_root=args.snapshot_root,
        once=args.once,
    )
    adapter = load_adapter(args.platform)
    runner = WorkerRunner(session_factory=SessionLocal, adapter=adapter, config=config)
    signal.signal(signal.SIGINT, runner.request_stop)
    signal.signal(signal.SIGTERM, runner.request_stop)
    try:
        runner.run()
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
